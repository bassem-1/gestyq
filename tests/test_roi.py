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
