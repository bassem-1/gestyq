from roi import CENTER, FULL, FaceGeom, RoiPlanner, map_face, map_landmarks, rect_to_px, zoom_rect
from head import FaceObs
from synth import cfg

FA = 16 / 9


def planner():
    return RoiPlanner(cfg()["hand"])


def test_zoom_rect_geometry():
    g = FaceGeom(0.5, 0.40, 0.05)
    x, y, w, h = zoom_rect(g, FA, 7.0)
    assert abs(w - 0.35) < 1e-9 and abs(w * FA / (16 / 9) - h) < 1e-9          # 16:9 in pixels
    assert abs(x + w / 2 - 0.5) < 1e-9                                          # centred on the face
    assert abs((0.40 - y) / h - 1 / 3) < 1e-9                                   # face at the upper third
    x, y, w, h = zoom_rect(FaceGeom(0.97, 0.05, 0.05), FA, 7.0)                 # clamped into the frame
    assert x + w <= 1 + 1e-9 and y == 0.0 and x >= 0
    assert zoom_rect(FaceGeom(0.5, 0.5, 0.3), FA, 7.0)[2] == 1.0                # never larger than the frame
    assert rect_to_px((0.25, 0.25, 0.5, 0.5), 1920, 1080) == (480, 270, 960, 540)


def test_map_landmarks_back_to_full_frame():
    rect = (0.3, 0.2, 0.4, 0.4)
    lms = [(0.0, 0.0, 0.1), (1.0, 1.0, -0.2), (0.5, 0.5, 0.0)]
    out = map_landmarks(lms, rect)
    assert out[0][:2] == (0.3, 0.2) and abs(out[1][0] - 0.7) < 1e-9 and abs(out[1][1] - 0.6) < 1e-9
    assert abs(out[2][0] - 0.5) < 1e-9 and abs(out[0][2] - 0.04) < 1e-9 and abs(out[1][2] + 0.08) < 1e-9
    assert map_landmarks(lms, FULL) == lms
    f = FaceObs((0.5, 0.5), (0.0, 0.5), (1.0, 0.5), (0.5, 0.0), (0.5, 1.0))
    m = map_face(f, rect)
    assert abs(m.left[0] - 0.3) < 1e-9 and abs(m.right[0] - 0.7) < 1e-9 and abs(m.chin[1] - 0.6) < 1e-9
    assert map_face(None, rect) is None


def test_zoom_hysteresis():
    p = planner()
    t = 0.0

    def step(frac):
        nonlocal t
        p.observe_face(FaceGeom(0.5, 0.4, frac), t)
        r = p.plan(t, True, FA)
        t += 0.05
        return r
    assert not step(0.30).zoom and step(0.30).rect == FULL
    assert not step(0.17).zoom                       # above far_face_frac 0.16
    assert step(0.10).zoom                           # enter
    assert step(0.18).zoom                           # still zoomed between 0.16 and 0.20
    assert not step(0.22).zoom                       # leave above 0.20
    assert not step(0.18).zoom                       # and not re-entered until < 0.16


def test_roi_is_stable_until_target_shifts_more_than_10_percent():
    p = planner()
    t = 0.0
    p.observe_face(FaceGeom(0.5, 0.4, 0.05), t)
    r0 = p.plan(t, True, FA).rect
    for i in range(1, 40):                           # tiny jitter: ROI must not move
        t += 0.03
        p.observe_face(FaceGeom(0.5 + 0.004 * (-1) ** i, 0.4, 0.05), t)
        assert p.plan(t, True, FA).rect == r0
    for i in range(60):                              # the person walks sideways: ROI follows, smoothly
        t += 0.03
        p.observe_face(FaceGeom(0.5 - 0.004 * i, 0.4, 0.05), t)
        r = p.plan(t, True, FA).rect
    assert r != r0 and r[0] < r0[0] - 0.05 and abs(r[2] - r0[2]) < 0.05


def test_no_face_no_hand_alternates_full_and_center_crop():
    p = planner()
    rects = [p.plan(0.1 * i, False, FA).rect for i in range(30)]
    assert set(rects[:9]) == {FULL}                  # within the first second: full frame only
    tail = rects[12:]
    assert FULL in tail and CENTER in tail
    assert all(a != b for a, b in zip(tail, tail[1:]))
    q = planner()                                    # a recently seen hand keeps the full frame
    assert {q.plan(0.1 * i, i % 5 == 0, FA).rect for i in range(40)} == {FULL}


def test_face_lost_keeps_zoom_while_hand_seen_then_drops():
    p = planner()
    p.observe_face(FaceGeom(0.5, 0.4, 0.05), 0.0)
    assert p.plan(0.0, True, FA).zoom
    assert p.plan(1.5, True, FA).zoom                # face gone, hand still tracked
    assert not p.plan(3.0, False, FA).zoom           # no hand for > 1 s


def to_crop(lms, rect):
    """Full-frame normalised -> crop-normalised (what the detector would report for the crop)."""
    rx, ry, rw, rh = rect
    return [((x - rx) / rw, (y - ry) / rh, z / rw) for x, y, z in lms]


def test_crop_and_full_frame_landmarks_round_trip():
    full = [(0.31, 0.42, 0.01), (0.5, 0.5, -0.02), (0.69, 0.58, 0.0), (0.4, 0.45, 0.03)]
    for rect in ((0.3, 0.2, 0.4, 0.4), (0.0, 0.0, 0.5, 0.5), (0.55, 0.45, 0.45, 0.55), (0.25, 0.3, 0.5, 0.5)):
        back = map_landmarks(to_crop(full, rect), rect)
        assert all(abs(a - b) < 1e-9 for p, q in zip(full, back) for a, b in zip(p, q))


def test_pixel_crop_matches_the_normalised_rect():
    import numpy as np
    W, H = 1920, 1080
    rect = zoom_rect(FaceGeom(0.45, 0.35, 0.06), W / H, 7.0)
    x, y, w, h = rect_to_px(rect, W, H)
    assert 0 <= x and x + w <= W and 0 <= y and y + h <= H
    frame = np.zeros((H, W), np.uint8)
    px, py = 900, 400                                            # a bright point in the full frame
    frame[py, px] = 255
    crop = frame[y:y + h, x:x + w]
    cy, cx = np.unravel_index(int(crop.argmax()), crop.shape)
    nx, ny = (cx + 0.5) / w, (cy + 0.5) / h                      # where a detector reports it in the crop
    fx, fy = map_landmarks([(nx, ny, 0.0)], (x / W, y / H, w / W, h / H))[0][:2]
    assert abs(fx * W - (px + 0.5)) < 1e-6 and abs(fy * H - (py + 0.5)) < 1e-6


def test_pipeline_returns_full_frame_hands_and_face_whatever_the_crop():
    import numpy as np
    from tracking import HandObs
    from vision import Pipeline

    class Det:                                    # reports a hand at the centre of whatever crop it is shown
        def image(self, bgr): return bgr
        def hands(self, img, ts): return [HandObs([(0.5, 0.5, 0.0)] * 21, "Left", 0.9)]
        def face(self, img, ts):
            return FaceObs((0.5, 0.5), (0.4, 0.5), (0.6, 0.5), (0.5, 0.3), (0.5, 0.7), None, (0.4, 0.3, 0.6, 0.7)), None

    c = cfg()
    pipe = Pipeline(c, Det())
    raw = np.zeros((1080, 1920, 3), np.uint8)
    hands, face, _, plan = pipe.run(raw, 0.0, 1, 1)             # first frame: the face is 0.2 of the frame, near
    assert not plan.zoom and abs(hands[0].lms[0][0] - 0.5) < 1e-9 and abs(face.nose[0] - 0.5) < 1e-9
    # a far user: the detector's face is 0.2 wide in the CROP, so ~0.05 of the frame once mapped back
    pipe.planner.observe_face(FaceGeom(0.45, 0.35, 0.05), 0.1)
    hands, face, _, plan = pipe.run(raw, 0.1, 2, 2)
    assert plan.zoom and plan.rect != FULL
    rx, ry, rw, rh = plan.rect
    assert abs(hands[0].lms[0][0] - (rx + rw / 2)) < 1e-9 and abs(hands[0].lms[0][1] - (ry + rh / 2)) < 1e-9
    assert abs(face.right[0] - face.left[0] - 0.2 * rw) < 1e-9 and abs(face.box[2] - face.box[0] - 0.2 * rw) < 1e-9
    assert 0 <= face.box[0] and face.box[2] <= 1
