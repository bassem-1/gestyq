#!/usr/bin/env python3
"""gestyq tuning tool. No actions, no AppKit: an OpenCV window (main thread) showing the MIRRORED
camera with landmarks, each hand's assigned role + vote, finger states, pinch ratio, gesture label,
head yaw/pitch proxies vs baseline and head events.   keys: q quit | s toggle swap_hands | r reset head
"""
import time

import cv2

import config
from gestures import GestureEngine
from head import HeadTracker
from roi import FULL, face_geom
from vision import Camera, Detectors, Pipeline, downscale, ensure_models

CONN = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
        (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]
COL = {"right": (60, 60, 255), "left": (255, 200, 60)}     # BGR
WHITE = (255, 255, 255)


def put(img, text, x, y, color=WHITE, scale=0.5):
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def main():
    cfg = config.load()
    cfg["head_level"] = max(int(cfg.get("head_level", 2)), 1)
    ensure_models()
    cam, det = Camera(cfg), Detectors(cfg)
    if not cam.open():
        raise SystemExit("no camera")
    engine, head, pipe = GestureEngine(cfg), HeadTracker(cfg), Pipeline(cfg, det)
    t0, last_ts, last_f, i = time.monotonic(), -1, -1, 0
    head_event, head_event_t, face = "", 0.0, None
    fps_t, fps = time.monotonic(), 0.0
    try:
        while True:
            ok, raw = cam.read()
            if not ok:
                continue
            now = time.monotonic()
            last_ts = max(last_ts + 1, int((now - t0) * 1000))
            H0, W0 = raw.shape[:2]
            ts_f = None
            if i % cfg["camera"]["face_every"] == 0:
                last_f = max(last_f + 1, last_ts)
                ts_f = last_f
            hands, f, _, plan = pipe.run(raw, now, last_ts, ts_f)     # unmirrored, as in the app
            engine.aspect = W0 / H0
            engine.observe_face(face_geom(f) if f else None, now, plan.zoom)
            engine.update(hands, now, f.box if f else None)
            if ts_f is not None:
                face = f
                for e in head.update(face, now, cfg["head_level"], engine.dragging):
                    head_event, head_event_t = e.value, now
            frame = downscale(raw, cfg["camera"]["process_width"])      # display only
            h, w = frame.shape[:2]
            i += 1
            view = cv2.flip(frame, 1)                    # display only
            for d in engine.debug:
                col = COL[d["role"]]
                pts = [(int((1 - p[0]) * w), int(p[1] * h)) for p in d["lms"]]
                for a, b in CONN:
                    cv2.line(view, pts[a], pts[b], col, 2)
                for p in pts:
                    cv2.circle(view, p, 3, WHITE, -1)
                x, y = pts[0][0] - 40, min(pts[0][1] + 24, h - 100)
                st = "".join(k[0].upper() if v == "ext" else k[0] for k, v in d["fingers"].items())
                put(view, f"{d['role'].upper()}  vote {d['vote']:+.2f} (now {d['score']:+.2f}) mp={d['label_mp']}", x, y, col)
                put(view, f"fingers {st}  pinch {d['ratio']:.2f}{' ON' if d['pinch'] else ''}", x, y + 18, col)
                put(view, f"label {engine.labels.get(d['role'])}  mode {engine.pointer.mode if d['role'] == 'right' else ''}",
                    x, y + 36, col)
            if plan.rect != FULL:                         # zoom crop (mirrored for display)
                rx, ry, rw, rh = plan.rect
                cv2.rectangle(view, (int((1 - rx - rw) * w), int(ry * h)), (int((1 - rx) * w), int((ry + rh) * h)),
                              (0, 255, 255), 2)
            bx, by, bw, bh = engine.pointer.box           # control box
            cv2.rectangle(view, (int((1 - bx - bw) * w), int(by * h)), (int((1 - bx) * w), int((by + bh) * h)),
                          (60, 60, 255), 2)
            put(view, f"face {plan.face_frac:.3f} of frame  zoom {'ON' if plan.zoom else 'off'}"
                      f"  box {'body' if engine.cbox.body(now) else 'fixed'}", 10, h - 30)
            y = 20
            if face is not None:
                nx, ny = int((1 - face.nose[0]) * w), int(face.nose[1] * h)
                cv2.circle(view, (nx, ny), 5, (0, 255, 255), -1)
            put(view, f"head yaw {head.yaw:+.1f} base {(head.base or [0, 0])[0]:+.1f} d {head.d_yaw:+.1f}   "
                      f"pitch {head.pitch:+.1f} base {(head.base or [0, 0])[1]:+.1f} d {head.d_pitch:+.1f}"
                      f"{'' if head.calibrated else '  (calibrating)'}", 10, y)
            put(view, f"fusion sign yaw {head.fuse_yaw.sign:+.0f} pitch {head.fuse_pitch.sign:+.0f}   "
                      f"thresholds {head.thresholds(cfg['head_level'])[0]:.1f}/{head.thresholds(cfg['head_level'])[1]:.1f} deg",
                10, y + 18)
            if now - head_event_t < 1.5:
                put(view, "HEAD EVENT: " + head_event, 10, y + 40, (0, 255, 0), 0.7)
            fps = 0.9 * fps + 0.1 / max(now - fps_t, 1e-3)
            fps_t = now
            put(view, f"{fps:.0f} fps  swap_hands={cfg['swap_hands']}  caption: {engine.caption(now)}", 10, h - 10)
            cv2.imshow("gestyq debug", view)
            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                break
            if k == ord("s"):
                cfg["swap_hands"] = not cfg["swap_hands"]
            if k == ord("r"):
                head.reset()
    finally:
        cam.close()
        det.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
