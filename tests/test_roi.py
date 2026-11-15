from roi import (CENTER, FULL, FaceGeom, RoiPlanner, contains, grow, inside, map_face, map_landmarks, merge_hands,
                 rect_to_px, zoom_rect)
from tracking import HandObs
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
    assert abs((0.40 - y) / h - 0.2) < 1e-9                                     # eyes a fifth down: head above, waist below
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
    assert not step(0.25).zoom                       # a desk is 0.25-0.35 of the frame: not far
    assert not step(0.23).zoom                       # above far_face_frac 0.22
    assert step(0.20).zoom                           # enter
    assert step(0.25).zoom                           # still zoomed between 0.22 and 0.27
    assert not step(0.28).zoom                       # leave above 0.27
    assert not step(0.25).zoom                       # and not re-entered until < 0.22
    h = cfg()["hand"]
    assert (h["far_face_frac"], h["near_face_frac"]) == (0.22, 0.27)


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
        def hands(self, img, ts, full=False): return [HandObs([(0.5, 0.5, 0.0)] * 21, "Left", 0.9)]
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


def test_crop_takes_in_the_whole_upper_body_with_raised_arms():
    fw = 0.10                                                   # a far user: face a tenth of the frame wide
    g = FaceGeom(0.5, 0.35, fw)
    x, y, w, h = zoom_rect(g, FA, cfg()["hand"]["roi_face_widths"], eye_frac=cfg()["hand"]["roi_eye_frac"])
    face_h = 1.3 * fw * FA                                      # face height, in frame heights
    assert 6 <= w / fw <= 7.5                                   # 6-7 face widths wide
    assert y <= g.eye_y - 0.4 * face_h - 0.1 * face_h           # the head top (eyes are 40% down the face) and room above
    assert y + h >= g.eye_y + 3.0 * fw * FA                     # down to the waist (~3 face widths below the eyes)
    assert x <= g.cx - 2.5 * fw and x + w >= g.cx + 2.5 * fw    # both raised arms (2.5 face widths from the centre)


def test_grow_contains_merge_helpers():
    r = (0.3, 0.2, 0.3, 0.5)
    g = grow(r, [(0.9, 0.3)], 0.1, FA)
    assert contains(g, r) and inside(g, (0.9, 0.3)) and g[0] == r[0] and abs(g[0] + g[2] - 1.0) < 1e-9
    assert grow(r, [(0.45, 0.4)], 0.1, FA) == (0.3, 0.2, 0.3, 0.5) or contains(grow(r, [(0.45, 0.4)], 0.1, FA), r)
    mk = lambda x, y: HandObs([(x, y, 0.0)] * 21, "Left", 0.9)
    base, extra = [mk(0.4, 0.5)], [mk(0.42, 0.51), mk(0.9, 0.4), mk(0.1, 0.4)]
    out = merge_hands(base, extra, 0.06)
    assert [o.lms[0][:2] for o in out] == [(0.4, 0.5), (0.9, 0.4)]            # dedupe by wrist, at most two hands
    assert merge_hands([], [mk(0.2, 0.2)], 0.06)[0].lms[0][0] == 0.2 and merge_hands([mk(0.4, 0.5)], [], 0.06) == base


def test_crop_grows_around_a_hand_outside_it_and_shrinks_back():
    p = planner()
    p.observe_face(FaceGeom(0.4, 0.35, 0.05), 0.0)
    base = p.plan(0.0, True, FA).rect
    p.observe_hands([(0.5, 0.5)], 0.1)                              # inside the crop: nothing changes
    assert p.plan(0.1, True, FA).rect == base
    out = (min(0.97, base[0] + base[2] + 0.2), 0.4)
    assert not inside(base, out)
    p.observe_hands([out], 0.2)
    r = p.plan(0.2, True, FA).rect
    assert inside(r, out) and contains(r, base)
    for i in range(10):                                             # the hand stays out there and is tracked: held, stable
        p.observe_hands([(out[0] + 0.005 * (-1) ** i, out[1])], 0.3 + 0.05 * i)
        assert p.plan(0.3 + 0.05 * i, True, FA).rect == r
    assert p.plan(1.0, True, FA).rect == r                          # last seen 0.2 s ago
    p.observe_hands([], 1.1)
    assert p.plan(2.5, True, FA).rect == base                       # gone for > roi_hand_ttl: back to the body crop


def _pipeline_det(calls):
    class Det:                                    # a hand in the middle of the crop, and one the full frame finds
        def image(self, bgr): return bgr
        def hands(self, img, ts, full=False):
            calls.append("full" if full else "crop")
            if full:                              # the whole frame: the same user's hand as in the crop and a far one
                cx, cy = 0.45, 0.45
                return [HandObs([(cx, cy, 0.0)] * 21, "Left", 0.9), HandObs([(0.92, 0.4, 0.0)] * 21, "Right", 0.9)]
            return [HandObs([(0.5, 0.5, 0.0)] * 21, "Left", 0.9)]
        def face(self, img, ts):
            return None, None
    return Det()


def test_pipeline_runs_a_full_frame_pass_every_fifth_zoomed_frame_and_merges_by_wrist():
    import numpy as np
    from vision import Pipeline
    calls = []
    c = cfg()
    pipe = Pipeline(c, _pipeline_det(calls))
    raw = np.zeros((1080, 1920, 3), np.uint8)
    seen = []
    for i in range(12):
        pipe.planner.observe_face(FaceGeom(0.45, 0.35, 0.05), 0.1 * i)
        hands, _, _, plan = pipe.run(raw, 0.1 * i, i + 1, None)
        assert plan.zoom
        seen.append(len(hands))
    assert calls.count("full") == 2 and calls.count("crop") == 12          # every 5th frame while zoomed
    assert seen[4] == 2 and seen[9] == 2 and seen[0] == seen[1] == 1       # merged: the far hand joins, no duplicate wrist
    # not zoomed: never a full-frame pass
    calls.clear()
    pipe = Pipeline(c, _pipeline_det(calls))
    for i in range(12):
        pipe.planner.observe_face(FaceGeom(0.5, 0.4, 0.30), 0.1 * i)
        assert not pipe.run(raw, 0.1 * i, i + 1, None)[3].zoom
    assert "full" not in calls


def test_the_crop_grows_to_a_hand_the_full_frame_pass_found():
    import numpy as np
    from vision import Pipeline
    pipe = Pipeline(cfg(), _pipeline_det([]))
    raw = np.zeros((1080, 1920, 3), np.uint8)
    rects = []
    for i in range(14):
        pipe.planner.observe_face(FaceGeom(0.45, 0.35, 0.05), 0.1 * i)
        rects.append(pipe.run(raw, 0.1 * i, i + 1, None)[3].rect)
    assert not inside(rects[0], (0.92, 0.4)) and inside(rects[7], (0.92, 0.4))      # after the pass at frame 5
