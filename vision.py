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

import cameras
from gaze import GazeDetector
from gestures import GestureEngine
from head import FaceObs, HeadTracker
from roi import FULL, RoiPlanner, face_geom, map_face, map_landmarks, rect_to_px
from preview import PREVIEW_FPS, GestureLog, Recorder, actions_live, camera_wanted
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


def downscale(frame, pw):
    h, w = frame.shape[:2]
    if w > pw:
        return cv2.resize(frame, (pw, int(round(h * pw / w))), interpolation=cv2.INTER_AREA)
    return frame


class Camera:
    """AVFoundation capture of the chosen device (by uniqueID, see cameras.py) at 1920x1080 or the best the
    device offers. read() returns the NATIVE frame, unmirrored; the Pipeline crops and resizes it."""

    def __init__(self, cfg):
        self.cfg, self.cap = cfg, None
        self.device, self.note = None, ""

    def open(self):
        devs = cameras.list_devices(force=True)
        dev, self.note = cameras.choose(devs, self.cfg)
        if dev is None:
            return False
        cap = cameras.AVCamera()
        if not cap.open(dev.uid, self.cfg["camera"]["width"]):
            cap.close()
            return False
        self.cap, self.device = cap, dev
        print(f"camera {dev.name} {cap.size[0]}x{cap.size[1]}" + (f" ({self.note})" if self.note else ""), flush=True)
        return True

    def read(self):
        """-> (ok, bgr native frame). Aspect = w / h of the returned frame."""
        if self.cap is None:
            return False, None
        return self.cap.read(timeout=0.25)

    def close(self):
        if self.cap is not None:
            self.cap.close()        # camera light off
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
        xs, ys = [p.x for p in lm], [p.y for p in lm]
        box = (min(xs), min(ys), max(xs), max(ys))
        return FaceObs(pt(1), pt(234), pt(454), pt(10), pt(152), mat, box), bs

    def close(self):
        for d in (self.hand, self.face_lm):
            if d is not None:
                d.close()
        self.hand = self.face_lm = None


class Pipeline:
    """Native frame -> hands / face in FULL-FRAME normalised coordinates. The planned ROI (the whole frame,
    or a full-resolution crop around the upper body when the user is far) is resized to `process_width`
    for the detectors and the landmarks are mapped back, so tracks, filters and recordings never see the
    crop."""

    def __init__(self, cfg, det):
        self.cfg, self.det = cfg, det
        self.planner = RoiPlanner(cfg["hand"])
        self.plan = None
        self._seen = False

    def reset(self):
        self.planner.reset()
        self._seen = False

    def run(self, raw, now, ts, ts_face=None):
        """-> (hands, face, blendshapes, plan). face / blendshapes are None on frames without a face
        pass (ts_face None) and when no face is found."""
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
        self.on_evt = threading.Event()         # gestyq is ON: actions execute
        self.win_evt = threading.Event()        # the app window is open: camera + detection for the live view
        self.record_evt = threading.Event()
        self.recorder = Recorder()
        self.glog = GestureLog()
        self.live = False                       # actions currently executing
        self.last_pub = 0.0
        self.pub_n = 0
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

    def set_window_open(self, open_):
        """Window open = camera wanted even while OFF (preview); actions stay off unless enabled."""
        if open_:
            self.win_evt.set()
        else:
            self.win_evt.clear()
            self.record_evt.clear()
        self.state.update(window_open=bool(open_))

    def set_recording(self, on):
        if on:
            self.record_evt.set()
        else:
            self.record_evt.clear()

    def reload_camera(self):
        self.reopen = True

    def stop(self):
        self.stop_evt.set()
        self.on_evt.clear()
        self.win_evt.clear()
        self.record_evt.clear()

    # -- helpers
    def _emit(self, evs):
        pulsed = False
        for e in evs:
            if not self.live:
                continue
            self.actions.execute(e)
            pulsed = pulsed or e.pulse
        if pulsed:
            self.state.pulse()

    def _off(self):
        """Release the mouse and the camera device."""
        self._release()
        self.cam.close()
        self.engine.reset()
        self.head.reset()
        self.gaze.reset()
        self.pipe.reset()
        self.recorder.stop()
        self.glog.clear()
        self.state.update(camera="off", caption="paused", hands=0, preview=None, recording=None)

    def _release(self):
        """Never leave a mouse button held (switching modes, turning off)."""
        was = self.live
        self.live = True
        self._emit(self.engine.release())
        self.live = was
        self.actions.release_all()

    def _no_camera(self):
        self._release()
        self.cam.close()
        self.state.update(camera="no camera", caption="no camera", hands=0, preview=None, camera_uid=None,
                          camera_note="")

    def _publish(self, now, frame, aspect, head_lvl, plan):
        """Window only: mirrored greyscale ~640 px JPEG + debug copies, at PREVIEW_FPS."""
        if now - self.last_pub < 1.0 / PREVIEW_FPS:
            return
        self.last_pub = now
        g = cv2.flip(cv2.cvtColor(downscale(frame, 640), cv2.COLOR_BGR2GRAY), 1)
        ok, buf = cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return
        head = None
        if head_lvl > 0:
            ty, tp = self.head.thresholds(head_lvl)
            head = {"yaw": self.head.d_yaw, "pitch": self.head.d_pitch, "thr_yaw": ty, "thr_pitch": tp,
                    "calibrated": self.head.calibrated}
        self.pub_n += 1
        self.state.update(preview={
            "n": self.pub_n, "t": now, "jpg": buf.tobytes(), "aspect": aspect,
            "debug": [dict(d) for d in self.engine.debug], "head": head, "gestures": self.glog.snapshot(),
            "caption": self.engine.caption(now),
            # unmirrored normalised (x0, y0, w, h): the crop the detectors see (None = whole frame) and the
            # box that maps to the desktop
            "zoom": plan.rect if plan and plan.zoom and plan.rect != FULL else None,
            "box": tuple(self.engine.pointer.box)},
            recording={"active": self.recorder.active, "elapsed": self.recorder.elapsed(now)})

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
        was_on, fails, frame_i, face_box = False, 0, 0, None
        try:
            while not self.stop_evt.is_set():
                if not camera_wanted(self.on_evt.is_set(), self.win_evt.is_set()):
                    if was_on:
                        self.live = False
                        self._off()
                        was_on = False
                    self.stop_evt.wait(0.1)
                    continue
                if not was_on:
                    was_on, fails = True, 0
                    self.live = False
                    self.engine.reset(); self.head.reset(); self.gaze.reset(); self.pipe.reset()
                    self.state.update(camera="starting", caption="starting")
                live = actions_live(self.on_evt.is_set())
                if live != self.live:                 # preview <-> on: drop held buttons, start clean
                    self._release()
                    self.engine.reset(); self.head.reset(); self.gaze.reset()
                    self.live = live
                win = self.win_evt.is_set()
                if self.record_evt.is_set() != self.recorder.active:
                    if self.record_evt.is_set():
                        try:
                            self.recorder.start(time.monotonic())
                        except OSError as e:
                            print("recording failed:", e)
                            self.record_evt.clear()
                    else:
                        self.recorder.stop()
                if not win and self.recorder.active:
                    self.recorder.stop()
                if self.reopen:
                    self.reopen = False
                    self.cam.close()
                if self.cam.cap is None:
                    if not self.cam.open():
                        self._no_camera()
                        self.stop_evt.wait(NO_CAMERA_RETRY)      # auto-retry while on
                        continue
                    fails = 0
                    self.state.update(camera="ok", camera_uid=self.cam.device.uid, camera_name=self.cam.device.name,
                                      camera_note=self.cam.note)
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
                cam = self.cfg["camera"]
                # the face is the head / eye input, and always the near / far reference for the zoom
                every = cam["face_every"] if (head_lvl > 0 or eye_on) else cam.get("zoom_face_every", 6)
                ts_f = None
                if frame_i % every == 0:
                    self.last_ts_f = max(self.last_ts_f + 1, ts)
                    ts_f = self.last_ts_f
                hands, face, bs, plan = self.pipe.run(frame, now, ts, ts_f)
                self.engine.aspect = w / h
                self.engine.screen = self.actions.bounds()[2:]
                self.engine.union_aspect = self.actions.desktop.aspect()
                self.engine.union_span = self.actions.desktop.span()
                self.engine.observe_face(face_geom(face) if face else None, now, plan.zoom)
                if self.recorder.active:
                    self.recorder.write(now, w / h, hands)      # full-frame normalised, whatever was cropped
                evs = self.engine.update(hands, now, face.box if face else None)
                if head_lvl > 0:
                    if ts_f is not None:
                        hev = self.head.update(face, now, head_lvl, self.engine.dragging)
                        for e in hev:
                            self.engine.flash("head · " + {"next_app": "next app", "prev_app": "previous app",
                                                                "sleep": "sleep"}[e.value], now, 1.0)
                        evs += hev
                elif self.head.base is not None:
                    self.head.reset()
                if eye_on and ts_f is not None:
                    evs += self.gaze.update(bs, now)
                elif not eye_on:
                    self.gaze.reset()
                frame_i += 1
                if win:
                    self.glog.add_events(evs, now)
                self._emit(evs)
                self.state.update(camera="ok", caption=self.engine.caption(now), hands=len(self.engine.labels))
                if win:
                    self._publish(now, frame, w / h, head_lvl, plan)
                elif self.state.d.get("preview") is not None:
                    self.state.update(preview=None, recording=None)
        finally:
            self.live = True
            self._emit(self.engine.release())
            self.actions.release_all()
            self.recorder.stop()
            self.cam.close()
            self.det.close()
