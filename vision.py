"""Camera + MediaPipe plumbing and the vision thread (camera, detection, gesture engine, actions)."""
import os
import threading
import time
import urllib.request
from dataclasses import replace

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_py
from mediapipe.tasks.python import vision as mp_vision

from gaze import GazeDetector
from gestures import GestureEngine
from head import FaceObs, HeadTracker
from roi import FULL, RoiPlanner, face_geom, map_face, map_landmarks, rect_to_px
from tracking import HandObs

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = {
    "hand": ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/"
             "float16/1/hand_landmarker.task", os.path.join(HERE, "hand_landmarker.task")),
    "face": ("https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/"
             "float16/1/face_landmarker.task", os.path.join(HERE, "face_landmarker.task")),
}
NO_CAMERA_RETRY = 2.0


def ensure_models():
    for url, path in MODELS.values():
        if not os.path.exists(path):
            print("downloading", os.path.basename(path))
            urllib.request.urlretrieve(url, path + ".part")
            os.replace(path + ".part", path)


def list_cameras():
    """[(index, name)] via AVFoundation; falls back to [(0, 'camera 0')]."""
    try:
        import AVFoundation as AV
        devs = AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeVideo)
        return [(i, str(d.localizedName())) for i, d in enumerate(devs)]
    except Exception:
        return [(0, "camera 0")]


def pick_camera(cfg, cams):
    want = cfg.get("camera_name")
    for i, n in cams:
        if want and n == want:
            return i
    for i, n in cams:
        if any(k in n for k in ("FaceTime", "MacBook", "Built-in")):
            return i
    return cams[0][0] if cams else 0


def downscale(frame, pw):
    h, w = frame.shape[:2]
    if w > pw:
        return cv2.resize(frame, (pw, int(round(h * pw / w))), interpolation=cv2.INTER_AREA)
    return frame


class Camera:
    """Requests 1920x1080 (falls back to 1280x720) and returns the NATIVE frame, unmirrored; the
    pipeline crops from it and resizes to `process_width`."""

    def __init__(self, cfg):
        self.cfg, self.cap = cfg, None

    def open(self):
        c = self.cfg["camera"]
        idx = pick_camera(self.cfg, list_cameras())
        cap = cv2.VideoCapture(idx, getattr(cv2, "CAP_AVFOUNDATION", 0))
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FPS, c["fps"])
            sizes = [(c["width"], c["height"])] + ([(1280, 720)] if c["width"] > 1280 else [])
            for i, (w, h) in enumerate(sizes):
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                ok, frame = cap.read()
                if ok and (frame.shape[1] >= 0.95 * w or i == len(sizes) - 1):
                    self.cap = cap
                    return True
        cap.release()
        return False

    def read(self):
        """-> (ok, bgr native frame)."""
        if self.cap is None:
            return False, None
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return False, None
        return True, frame

    def close(self):
        if self.cap is not None:
            self.cap.release()      # camera light off
            self.cap = None


class Detectors:
    def __init__(self, cfg):
        self.cfg, self.hand, self.face_lm = cfg, None, None

    def _hand(self):
        c = self.cfg["hand"]
        self.hand = mp_vision.HandLandmarker.create_from_options(mp_vision.HandLandmarkerOptions(
            base_options=mp_py.BaseOptions(model_asset_path=MODELS["hand"][1]),
            running_mode=mp_vision.RunningMode.VIDEO, num_hands=2,
            min_hand_detection_confidence=c["min_detection_conf"],
            min_hand_presence_confidence=c["min_presence_conf"],
            min_tracking_confidence=c["min_tracking_conf"]))

    def _face(self):
        self.face_lm = mp_vision.FaceLandmarker.create_from_options(mp_vision.FaceLandmarkerOptions(
            base_options=mp_py.BaseOptions(model_asset_path=MODELS["face"][1]),
            running_mode=mp_vision.RunningMode.VIDEO, num_faces=1,
            output_face_blendshapes=True, output_facial_transformation_matrixes=True))

    @staticmethod
    def image(bgr):
        return mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    def hands(self, img, ts):
        if self.hand is None:
            self._hand()
        res = self.hand.detect_for_video(img, ts)
        return [HandObs([(p.x, p.y, p.z) for p in lm], res.handedness[i][0].category_name,
                        float(res.handedness[i][0].score)) for i, lm in enumerate(res.hand_landmarks)]

    def face(self, img, ts):
        """-> (FaceObs | None, blendshape dict | None)"""
        if self.face_lm is None:
            self._face()
        res = self.face_lm.detect_for_video(img, ts)
        if not res.face_landmarks:
            return None, None
        lm = res.face_landmarks[0]
        pt = lambda i: (lm[i].x, lm[i].y)
        mat = res.facial_transformation_matrixes[0] if res.facial_transformation_matrixes else None
        bs = {b.category_name: b.score for b in res.face_blendshapes[0]} if res.face_blendshapes else None
        return FaceObs(pt(1), pt(234), pt(454), pt(10), pt(152), mat), bs

    def close(self):
        for d in (self.hand, self.face_lm):
            if d is not None:
                d.close()
        self.hand = self.face_lm = None


class Pipeline:
    """Native frame -> hands / face in FULL-FRAME normalised coords. Crops the planned ROI from the
    full-resolution frame, so tracks and filters stay continuous when the ROI moves."""

    def __init__(self, cfg, det):
        self.cfg, self.det = cfg, det
        self.planner = RoiPlanner(cfg["hand"])
        self.plan = None
        self._seen = False

    def reset(self):
        self.planner.reset()
        self._seen = False

    def run(self, raw, now, ts, ts_face=None):
        """-> (hands, face, blendshapes, plan). face is None on non-face frames
        and when no face is found."""
        H, W = raw.shape[:2]
        pw = self.cfg["camera"]["process_width"]
        self.plan = plan = self.planner.plan(now, self._seen, W / H)
        rect = plan.rect
        if rect == FULL:
            crop = raw
        else:
            x, y, w, h = rect_to_px(rect, W, H)
            crop = raw[y:y + h, x:x + w]
        ch, cw = crop.shape[:2]
        proc = crop
        if cw != pw:
            proc = cv2.resize(crop, (pw, max(2, int(round(ch * pw / cw)))),
                              interpolation=cv2.INTER_AREA if cw > pw else cv2.INTER_LINEAR)
        img = self.det.image(proc)
        hands = [replace(o, lms=map_landmarks(o.lms, rect)) for o in self.det.hands(img, ts)]
        self._seen = bool(hands)
        face, bs = None, None
        if ts_face is not None:
            face, bs = self.det.face(img, ts_face)
            face = map_face(face, rect)
            if face is not None:
                self.planner.observe_face(face_geom(face), now)
        return hands, face, bs, plan



class VisionThread(threading.Thread):
    def __init__(self, state, cfg, actions):
        super().__init__(daemon=True, name="vision")
        self.state, self.cfg, self.actions = state, cfg, actions
        self.stop_evt = threading.Event()
        self.on_evt = threading.Event()
        self.engine = GestureEngine(cfg)
        self.head = HeadTracker(cfg)
        self.gaze = GazeDetector(cfg)
        self.cam = Camera(cfg)
        self.det = Detectors(cfg)
        self.pipe = Pipeline(cfg, self.det)
        self.reopen = False
        self.t0 = time.monotonic()
        self.last_ts = -1
        self.last_ts_f = -1

    # -- control (any thread)
    def set_enabled(self, on):
        if on:
            self.on_evt.set()
        else:
            self.on_evt.clear()
        self.state.update(enabled=bool(on))

    def reload_camera(self):
        self.reopen = True

    def stop(self):
        self.stop_evt.set()
        self.on_evt.clear()

    # -- helpers
    def _emit(self, evs):
        pulsed = False
        for e in evs:
            self.actions.execute(e)
            pulsed = pulsed or e.pulse
        if pulsed:
            self.state.pulse()

    def _off(self):
        """Release the mouse and the camera device."""
        self._emit(self.engine.release())
        self.actions.release_all()
        self.cam.close()
        self.engine.reset()
        self.head.reset()
        self.gaze.reset()
        self.pipe.reset()
        self.state.update(camera="off", caption="paused", hands=0)

    def _no_camera(self):
        self._emit(self.engine.release())
        self.actions.release_all()
        self.cam.close()
        self.state.update(camera="no camera", caption="no camera", hands=0)

    def _ts(self, now):
        self.last_ts = max(self.last_ts + 1, int((now - self.t0) * 1000))
        return self.last_ts

    # -- main loop
    def run(self):
        try:
            ensure_models()
        except Exception as e:
            print("model download failed:", e)
            self.state.update(camera="no camera", caption="no camera")
            return
        was_on, fails, frame_i = False, 0, 0
        try:
            while not self.stop_evt.is_set():
                if not self.on_evt.is_set():
                    if was_on:
                        self._off()
                        was_on = False
                    self.on_evt.wait(0.1)
                    continue
                if not was_on:
                    was_on, fails = True, 0
                    self.engine.reset(); self.head.reset(); self.gaze.reset(); self.pipe.reset()
                    self.state.update(camera="starting", caption="starting")
                if self.reopen:
                    self.reopen = False
                    self.cam.close()
                if self.cam.cap is None:
                    if not self.cam.open():
                        self._no_camera()
                        self.stop_evt.wait(NO_CAMERA_RETRY)      # auto-retry while on
                        continue
                    fails = 0
                    self.state.update(camera="ok")
                ok, frame = self.cam.read()
                if not ok:
                    fails += 1
                    if fails >= 20:                 # lid closed / camera taken by another app
                        self._no_camera()
                        self.stop_evt.wait(NO_CAMERA_RETRY)
                    else:
                        time.sleep(0.03)
                    continue
                fails = 0
                now = time.monotonic()
                ts = self._ts(now)
                h, w = frame.shape[:2]
                head_lvl = int(self.cfg.get("head_level", 0))
                eye_on = bool(self.cfg.get("eye_corners"))
                ts_f = None
                if frame_i % self.cfg["camera"]["face_every"] == 0:     # always: the face is the scale reference
                    self.last_ts_f = max(self.last_ts_f + 1, ts)
                    ts_f = self.last_ts_f
                hands, face, bs, plan = self.pipe.run(frame, now, ts, ts_f)
                self.engine.aspect = w / h
                self.engine.screen = self.actions.bounds()[2:]
                self.engine.union_aspect = self.actions.desktop.aspect()
                self.engine.union_span = self.actions.desktop.span()
                if ts_f is not None:
                    self.engine.observe_face(face_geom(face) if face else None, now)
                evs = self.engine.update(hands, now)
                if ts_f is not None:
                    if head_lvl > 0:
                        hev = self.head.update(face, now, head_lvl, self.engine.dragging)
                        for e in hev:
                            self.engine.flash("head · " + {"next_app": "next app", "prev_app": "previous app",
                                                                "sleep": "sleep"}[e.value], now, 1.0)
                        evs += hev
                    elif self.head.base is not None:
                        self.head.reset()
                    if eye_on:
                        evs += self.gaze.update(bs, now)
                    else:
                        self.gaze.reset()
                frame_i += 1
                self._emit(evs)
                self.state.update(camera="ok", caption=self.engine.caption(now), hands=len(self.engine.labels))
        finally:
            self._emit(self.engine.release())
            self.actions.release_all()
            self.cam.close()
            self.det.close()
