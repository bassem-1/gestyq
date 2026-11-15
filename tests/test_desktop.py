import math

from desktop import (ControlBox, Desktop, body_box, clamp_to_displays, cocoa_to_topleft, control_box,
                     margin_box, parse_rect, pick_visible, span_of, to_point, union)
from gestures import tile_rect
from roi import FaceGeom
from synth import cfg

SIDE = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
STACK = [(0, 0, 1920, 1080), (0, 1080, 1920, 1080)]
L_SHAPE = [(0, 0, 1000, 1000), (1000, 500, 1000, 500)]       # dead area: x>1000, y<500


def aspect_of(box, frame_aspect):
    return box[2] * frame_aspect / box[3]


def test_union_and_clamp_dead_area():
    assert union(SIDE) == (0, 0, 3840, 1080)
    assert union(L_SHAPE) == (0, 0, 2000, 1000)
    assert clamp_to_displays((500, 500), L_SHAPE) == (500, 500)
    assert clamp_to_displays((1500, 700), L_SHAPE) == (1500, 700)
    x, y = clamp_to_displays((1800, 100), L_SHAPE)               # dead area: snaps to nearest display
    assert (x, y) == (1800, 500)
    x, y = clamp_to_displays((1100, 200), L_SHAPE)               # nearer to the left display's edge
    assert (x, y) == (999, 200)
    assert to_point(1.0, 0.0, L_SHAPE) == (1999, 500)             # top-right corner of the union is dead
    assert to_point(0.0, 1.0, SIDE) == (0, 1079)


def test_desktop_thread_safe_set_and_count():
    d = Desktop(SIDE[:1])
    assert d.count() == 1 and not d.set(SIDE[:1]) and d.set(SIDE) and d.count() == 2 and d.span() == 2.0
    assert abs(d.aspect() - 3840 / 1080) < 1e-9
    assert not d.set([])


def test_control_box_adapts_aspect_for_1_2_side_and_2_stacked():
    fa = 16 / 9
    spans = {"one": span_of(SIDE[:1]), "side": span_of(SIDE), "stack": span_of(STACK)}
    assert spans == {"one": 1.0, "side": 2.0, "stack": 1.0}
    boxes = {}
    for name, rects in (("one", SIDE[:1]), ("side", SIDE), ("stack", STACK)):
        u = union(rects)
        b = boxes[name] = control_box(0.5, 0.5, 0.3, u[2] / u[3], fa, span=spans[name])
        assert abs(aspect_of(b, fa) - u[2] / u[3]) < 1e-9              # physical aspect == desktop aspect
        assert b[0] >= 0 and b[0] + b[2] <= 1 + 1e-9 and b[1] >= 0 and b[1] + b[3] <= 1 + 1e-9
        # hand travel per screen px is identical in x and y
        assert abs(b[2] * fa / u[2] - b[3] / u[3]) < 1e-12
    one, side, stack = boxes["one"], boxes["side"], boxes["stack"]
    assert abs(side[2] - 2 * one[2]) < 1e-9 and abs(side[3] - one[3]) < 1e-9     # wider desktop => wider box
    assert abs(stack[3] - 2 * one[3]) < 1e-9 and abs(stack[2] - one[2]) < 1e-9   # stacked => taller box
    # same hand travel per screen-cm as on one display
    assert abs(one[2] * fa / 1920 - side[2] * fa / 3840) < 1e-12
    capped = control_box(0.5, 0.5, 0.8, 32 / 9, fa, span=2.0)                      # capped to the frame
    assert capped[2] <= 1 + 1e-9 and abs(aspect_of(capped, fa) - 32 / 9) < 1e-9


def test_margin_box_matches_old_mapping_and_caps():
    h = cfg()["hand"]
    b = margin_box(h, 16 / 9, 16 / 9)
    assert all(abs(a - e) < 1e-9 for a, e in zip(b, (0.15, 0.15, 0.7, 0.7)))
    wide = margin_box(h, 32 / 9, 16 / 9)                            # capped by the usable width
    assert abs(wide[2] - 0.7) < 1e-9 and wide[3] < 0.7
    tall = margin_box(h, 16 / 18, 16 / 9)                           # capped by the usable height
    assert abs(tall[3] - 0.7) < 1e-9 and tall[2] < 0.7


def test_body_box_scales_with_face_and_sits_on_right_shoulder():
    h = cfg()["hand"]
    near = body_box(FaceGeom(0.5, 0.35, 0.16), h, 16 / 9, 16 / 9)
    far = body_box(FaceGeom(0.5, 0.35, 0.05), h, 16 / 9, 16 / 9)
    assert abs(near[2] - 4.5 * 0.16) < 1e-9 and abs(far[2] - 4.5 * 0.05) < 1e-9
    assert far[2] < near[2] / 3                                      # same arm movement at any distance
    cx = far[0] + far[2] / 2
    assert abs(cx - (0.5 - 1.2 * 0.05)) < 1e-9                       # user's right = image-left
    assert far[1] + far[3] / 2 > 0.35                                # below the eyes
    sw = body_box(FaceGeom(0.5, 0.35, 0.05), h, 16 / 9, 16 / 9, side=-1)
    assert sw[0] + sw[2] / 2 > 0.5


def test_control_box_ema_and_freeze():
    h = cfg()["hand"]
    cb = ControlBox(h)
    b0 = cb.update(0.0, False, 16 / 9, 16 / 9)
    assert not cb.body(0.0) and b0 == margin_box(h, 16 / 9, 16 / 9)
    cb.observe_face(FaceGeom(0.5, 0.35, 0.08), 0.1)
    b1 = cb.update(0.2, False, 16 / 9, 16 / 9)
    tgt = body_box(FaceGeom(0.5, 0.35, 0.08), h, 16 / 9, 16 / 9)
    assert b0[2] > b1[2] > tgt[2]                                    # moving toward target, not snapping
    frozen = cb.update(0.4, True, 16 / 9, 16 / 9)
    assert frozen == b1
    assert cb.update(0.6, False, 16 / 9, 16 / 9)[2] < b1[2]
    assert not cb.body(5.0)                                          # face ttl expired -> fixed box


def test_cocoa_flip_non_primary_displays():
    # primary 1440x900; a display ABOVE it has Cocoa y = 900 (global, relative to the primary)
    above = (0, 900, 1920, 1055)
    assert cocoa_to_topleft(above, 900) == (0, -1055, 1920, 1055)
    assert tile_rect("left", above, 900) == (0, -1055, 960, 1055)
    # a display to the right, vertically offset down by 200 px
    right = (1440, -200, 1920, 1080)
    assert cocoa_to_topleft(right, 900) == (1440, 20, 1920, 1080)
    assert tile_rect("right", right, 900) == (1440 + 960, 20, 960, 1080)
    assert tile_rect("fill", (0, 25, 1440, 875), 900) == (0, 0, 1440, 875)       # primary unchanged


def test_pick_visible_uses_window_display_and_falls_back_to_main():
    prim = {"frame": (0, 0, 1440, 900), "visible": (0, 25, 1440, 850)}
    ext = {"frame": (1440, -200, 1920, 1080), "visible": (1440, -200, 1920, 1055)}
    scr = [prim, ext]
    assert pick_visible((1600, 100, 800, 600), scr, 900) == ext["visible"]       # centre on the external
    assert pick_visible((100, 100, 800, 600), scr, 900) == prim["visible"]
    assert pick_visible((1300, 100, 400, 400), scr, 900) == ext["visible"]       # centre 1500 > 1440
    assert pick_visible(None, scr, 900, main=1) == ext["visible"]
    assert pick_visible((9000, 9000, 10, 10), scr, 900) == prim["visible"]
    assert parse_rect("10, 20, 300, 400") == (10, 20, 300, 400) and parse_rect("") is None
