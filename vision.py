"""Camera + MediaPipe plumbing and the vision thread (camera, detection, gesture engine, actions).

The camera runs ONLY while gestyq is on: off means the camera device is closed (the green light is off), whether
the window is open or not. The window merely receives the live view while the camera is running."""
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
import bindings
import wake
from roi import FULL, RoiPlanner, face_geom, map_face, map_landmarks, merge_hands, rect_to_px
from preview import PREVIEW_FPS, GestureLog, Recorder, camera_wanted
from tracking import HandObs, palm_anchor

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
        self.cfg, self.hand, self.hand_full, self.face_lm = cfg, None, None, None

    def _hand(self):
        c = self.cfg["hand"]
        return mp_vision.HandLandmarker.create_from_options(mp_vision.HandLandmarkerOptions(
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

    def hands(self, img, ts, full=False):
        """full=True: the second landmarker, which only ever sees whole frames (its tracking state must not be
        mixed with the crop's)."""
        if full:
            if self.hand_full is None:
                self.hand_full = self._hand()
            det = self.hand_full
        else:
            if self.hand is None:
                self.hand = self._hand()
            det = self.hand
        res = det.detect_for_video(img, ts)
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
        for d in (self.hand, self.hand_full, self.face_lm):
            if d is not None:
                d.close()
        self.hand = self.hand_full = self.face_lm = None


class Pipeline:
    """Native frame -> hands / face in FULL-FRAME normalised coordinates. The planned ROI (the whole frame,
    or a full-resolution crop around the upper body when the user is far) is resized to `process_width`
    for the detectors and the landmarks are mapped back, so tracks, filters and recordings never see the
    crop. While zoomed, every `full_every`-th frame also runs a whole-frame hand detection and merges it in, so a
    hand that left the crop is found again (the planner then grows the crop around it)."""

    def __init__(self, cfg, det):
        self.cfg, self.det = cfg, det
        self.planner = RoiPlanner(cfg["hand"])
        self.plan = None
        self._seen = False
        self._n = 0

    def reset(self):
        self.planner.reset()
        self._seen = False
        self._n = 0

    def run(self, raw, now, ts, ts_face=None):
        """-> (hands, face, blendshapes, plan). face / blendshapes are None on frames without a face
        pass (ts_face None) and when no face is found."""
        H, W = raw.shape[:2]
        cam = self.cfg["camera"]
        self.plan = plan = self.planner.plan(now, self._seen, W / H)
        rect = plan.rect
        if rect == FULL:
            crop = raw
        else:
            x, y, w, h = rect_to_px(rect, W, H)
            crop = raw[y:y + h, x:x + w]
        ch, cw = crop.shape[:2]
        pw = min(cw, cam.get("zoom_process_width", 1280)) if plan.zoom else cam["process_width"]
        proc = crop
        if cw != pw:
            proc = cv2.resize(crop, (pw, max(2, int(round(ch * pw / cw)))),
                              interpolation=cv2.INTER_AREA if cw > pw else cv2.INTER_LINEAR)
        img = self.det.image(proc)
        hands = [replace(o, lms=map_landmarks(o.lms, rect)) for o in self.det.hands(img, ts)]
        hc = self.cfg["hand"]
        if plan.zoom and rect != FULL and len(hands) < 2:
            self._n += 1
            if self._n % max(1, int(hc.get("full_every", 5))) == 0:
                fw = cam.get("zoom_process_width", 1280)
                full = raw if W <= fw else cv2.resize(raw, (fw, max(2, int(round(H * fw / W)))),
                                                      interpolation=cv2.INTER_AREA)
                hands = merge_hands(hands, self.det.hands(self.det.image(full), ts, full=True), hc.get("merge_dist", 0.06))
        self.planner.observe_hands([o.lms[0][:2] for o in hands], now)
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
        self.on_evt = threading.Event()         # gestyq is ON: the camera runs and actions execute
        self.win_evt = threading.Event()        # the app window is open: publish the live view (never starts the camera)
        self.record_evt = threading.Event()
        self.write_evt = threading.Event()      # the air-writing canvas is up: the engine inks and may type
        self.write_shown = None                 # monotonic time the canvas appeared (arm delay)
        self._ink_pub = None
        self.recorder = Recorder()
        self.glog = GestureLog()
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
        self.asleep, self.asleep_t = False, -1e9          # main display asleep (polled twice a second)
        self.last_wake, self.no_wake_until = -1e9, -1e9
        self.prev_anchors = []

    # -- control (any thread)
    def set_enabled(self, on):
        if on:
            self.on_evt.set()
        else:
            self.on_evt.clear()
        self.state.update(enabled=bool(on))

    def set_window_open(self, open_):
        """Window open = the live view is published while the camera runs. It never turns the camera on."""
        if open_:
            self.win_evt.set()
        else:
            self.win_evt.clear()
            self.record_evt.clear()
        self.state.update(window_open=bool(open_))

    def set_write(self, active, shown_at=None):
        """Main thread: the canvas appeared / went away. Anything recognised after it left is dropped."""
        if active:
            self.write_shown = shown_at
            self.write_evt.set()
        else:
            self.write_evt.clear()
            self.write_shown = None
        self.state.update(write=bool(active))

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
        """Execute events. While the display is asleep nothing but releasing a held drag runs: a click or a key
        would act blind (the hand only wakes the display, see _wake)."""
        pulsed = False
        for e in evs:
            if self.asleep and e.kind != "drag_end":
                continue
            self.actions.execute(e)
            pulsed = pulsed or e.pulse
        if pulsed:
            self.state.pulse()

    def _wake(self, now, hands, evs):
        """Hand movement (or any gesture) wakes a sleeping display, like touching the trackpad."""
        if now - self.asleep_t >= wake.POLL:
            self.asleep_t = now
            self.asleep = self.actions.display_asleep()
        anchors = [palm_anchor(o.lms) for o in hands]
        moving = wake.hands_moved(self.prev_anchors, anchors)
        self.prev_anchors = anchors
        fired = any(e.kind in ("gesture", "head", "gaze", "drag_start", "scroll") for e in evs)
        if now >= self.no_wake_until and wake.should_wake(self.asleep, self.on_evt.is_set(), moving, fired, now,
                                                          self.last_wake):
            self.last_wake = now
            self.actions.wake_display()
            print("wake: display asleep, hand activity", flush=True)

    def _note_sleep_request(self, evs, now):
        """A display_sleep the user asked for must not be undone by the hand that is still in the air."""
        for e in evs:
            gid = bindings.gesture_of(e)
            if gid and bindings.action_for(self.cfg, gid) == "display_sleep":
                self.no_wake_until = now + wake.SLEEP_GRACE

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
        self.prev_anchors = []
        self.write_evt.clear()
        self._ink_pub = None
        self.state.update(camera="off", caption="paused", hands=0, live=None, recording=None, ink=None, write=False)

    def _release(self):
        """Never leave a mouse button held (turning off, display change)."""
        self._emit(self.engine.release())
        self.actions.release_all()

    def _no_camera(self):
        self._release()
        self.cam.close()
        self.state.update(camera="no camera", caption="no camera", hands=0, live=None, camera_uid=None,
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
        self.state.update(live={
            "n": self.pub_n, "t": now, "jpg": buf.tobytes(), "aspect": aspect,
            "debug": [dict(d) for d in self.engine.debug], "head": head, "gestures": self.glog.snapshot(),
            "caption": self.engine.caption(now),
            # unmirrored normalised (x0, y0, w, h): the crop the detectors see (None = whole frame) and, in
            # absolute mode only, the box that maps to the desktop
            "zoom": plan.rect if plan and plan.zoom and plan.rect != FULL else None,
            "box": None if self.engine.relative else tuple(self.engine.pointer.box)},
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
                if not camera_wanted(self.on_evt.is_set()):
                    if was_on:                       # OFF: the camera device closes now, window open or not
                        self._off()
                        was_on = False
                    self.stop_evt.wait(0.1)
                    continue
                if not was_on:
                    was_on, fails = True, 0
                    self.engine.reset(); self.head.reset(); self.gaze.reset(); self.pipe.reset()
                    self.asleep, self.prev_anchors = False, []
                    self.state.update(camera="starting", caption="starting")
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
                self.engine.rects = self.actions.desktop.rects()
                self.engine.union_aspect = self.actions.desktop.aspect()
                self.engine.union_span = self.actions.desktop.span()
                self.engine.pointer.hint = self.actions.location()      # a new hand track starts at the real cursor
                self.engine.observe_face(face_geom(face) if face else None, now, plan.zoom)
                if self.recorder.active:
                    self.recorder.write(now, w / h, hands)      # full-frame normalised, whatever was cropped
                wr = self.write_evt.is_set()
                self.engine.write_active, self.engine.write_shown_at = wr, self.write_shown if wr else None
                evs = self.engine.update(hands, now, face.box if face else None)
                if not wr or not self.write_evt.is_set():       # nothing is typed once the canvas left
                    evs = [e for e in evs if e.kind != "write"]
                n_ink = self.engine.ink["n"] if wr and self.engine.ink else None
                if n_ink != self._ink_pub:
                    self._ink_pub = n_ink
                    self.state.update(ink=self.engine.ink if wr else None)
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
                self._wake(now, hands, evs)
                self._note_sleep_request(evs, now)
                self._emit(evs)
                self.state.update(camera="ok", caption=self.engine.caption(now), hands=len(self.engine.labels))
                if win:
                    self._publish(now, frame, w / h, head_lvl, plan)
                elif self.state.d.get("live") is not None:
                    self.state.update(live=None, recording=None)
        finally:
            self._emit(self.engine.release())
            self.actions.release_all()
            self.recorder.stop()
            self.cam.close()
            self.det.close()
