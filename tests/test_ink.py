import math
import random

import ink
import letters
from synth import cfg, make_hand
from synth_ink import densify
from tracking import HandState

FPS = 30.0


# ---------------------------------------------------------------- geometry
def _eq_spacing(pts):
    d = [math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts))]
    return max(d) / min(d)


def test_resample_returns_n_points_equally_spaced():
    one = [(0, 0), (3, 0), (7, 0)]                      # straight, so chord spacing = spacing along the ink
    two = [[(0, 0), (2, 0)], [(5, 5), (5, 8), (5, 13)]]
    pts = ink.resample([one], 32)
    assert len(pts) == 32 and _eq_spacing(pts) < 1.01
    pts = ink.resample(two, 32)
    assert len(pts) == 32
    # equal spacing ALONG the ink: the jump between the strokes is not ink
    d = [math.dist(pts[i - 1], pts[i]) for i in range(1, 32)]
    inside = [x for x in d if x < 2.0]
    assert max(inside) / min(inside) < 1.01 and len([x for x in d if x > 3]) == 1
    z = ink.resample([[(1, 1), (1, 1)]], 32)
    assert len(z) == 32 and set(z) == {(1, 1)}
    assert len(ink.resample([[(2, 2)]], 8)) == 8


def test_normalize_is_translation_and_scale_invariant():
    base = [(0, 0), (1, 0.2), (2, 1), (3, 0.5)]
    a = ink.normalize(ink.resample([base], 32))
    moved = [(5 + 2.5 * x, -3 + 2.5 * y) for x, y in base]
    b = ink.normalize(ink.resample([moved], 32))
    assert max(math.dist(p, q) for p, q in zip(a, b)) < 1e-9
    assert abs(max(p[0] for p in a) - min(p[0] for p in a)) <= 1.0 + 1e-9


def test_fit_leaves_the_transform_alone_while_the_ink_fits_and_contains_it_after():
    aw, ah, s0 = 296, 144, 48.0
    first = (10.0, 20.0)
    small = [[first, (10.5, 20.5), (11.0, 20.2)]]
    sc, ox, oy = ink.fit(ink.bbox(small), first, aw, ah, s0)
    assert sc == s0 and abs(ox + first[0] * sc - 0.4 * aw) < 1e-9 and abs(oy + first[1] * sc - 0.35 * ah) < 1e-9
    grown = small + [[(11.0, 20.2), (11.4, 20.9)]]                  # still inside: nothing moves
    assert ink.fit(ink.bbox(grown), first, aw, ah, s0) == (sc, ox, oy)
    big = [[first, (16.0, 20.0), (16.0, 26.0)]]                     # would leave the area
    sc2, ox2, oy2 = ink.fit(ink.bbox(big), first, aw, ah, s0)
    x0, y0, x1, y1 = ink.bbox(big)
    assert sc2 < s0
    assert ox2 + x0 * sc2 >= 8 - 1e-6 and ox2 + x1 * sc2 <= aw - 8 + 1e-6
    assert oy2 + y0 * sc2 >= 8 - 1e-6 and oy2 + y1 * sc2 <= ah - 8 + 1e-6
    assert ink.fit(None, first, aw, ah, s0)[0] == s0


# ---------------------------------------------------------------- the Writer on scripted frames
def template_path(ch, size=1.5, step=0.12, variant=0):
    """Palm-unit points of a built-in letter, y down, spaced `step` apart (3.6 palm/s at 30 fps)."""
    strokes = []
    for st in letters.LETTERS[ch][variant]:
        pts = densify([(x * size, -y * size) for x, y in st], 0.02)
        out = [pts[0]]
        for p in pts[1:]:
            if math.dist(p, out[-1]) >= step:
                out.append(p)
        strokes.append(out)
    return strokes


class Drive:
    """A hand in the point pose whose index tip is moved through palm-unit positions, one frame at a time."""

    def __init__(self, aspect=1.0, **write):
        c = cfg()
        c["write"].update(write)
        self.c, self.aspect = c, aspect
        self.w = ink.Writer(c)
        self.hs = HandState(c["hand"])
        self.t = 1.0
        self.pos = (0.0, 0.0)
        self.scale = 1.0
        self.palm0 = None
        self.out = []
        self.commits = []                    # (t, strokes)

    def frame(self, pos=None, pose="point", scale=None, active=True, hand=True, label=None, pinch=0.0):
        self.pos = pos or self.pos
        self.scale = scale or self.scale
        curl = {"point": (0, 1, 1, 1), "open": (0, 0, 0, 0), "fist": (1, 1, 1, 1)}[pose]
        lm = make_hand("right", x=0.5, y=0.5, curl=curl, scale=self.scale, pinch=pinch)
        if self.palm0 is None:
            self.hs.update(lm, self.aspect, self.t)
            self.palm0 = self.hs.palm / self.scale
        palm = self.palm0 * self.scale
        tip = make_hand("right", x=0.0, y=0.0, curl=curl, scale=self.scale, pinch=pinch)[8]
        lm = make_hand("right", x=0.5 - self.pos[0] * palm - tip[0], y=0.5 + self.pos[1] * palm * self.aspect - tip[1],
                       curl=curl, scale=self.scale, pinch=pinch)
        self.hs.update(lm, self.aspect, self.t)
        if label:
            self.hs.label = label
        o = self.w.step(self.hs if hand else None, lm if hand else None, self.aspect, self.t, active)
        self.out.append((self.t, o))
        if o.commit:
            self.commits.append((self.t, o.commit))
        self.t += 1 / FPS
        return o

    def hold(self, seconds, **kw):
        for _ in range(int(round(seconds * FPS))):
            self.frame(**kw)

    def draw(self, strokes, up_between=0.0, **kw):
        """Move through the strokes with the pen down; lift (open hand) for `up_between` seconds between them."""
        if math.dist(strokes[0][0], self.pos) > 0.3 and not kw:      # get to the start with an open hand, then point
            self.hold(0.3, pose="open", pos=strokes[0][0])
            self.hold(0.25, pos=strokes[0][0])
        for i, st in enumerate(strokes):
            if i and up_between:
                self.hold(up_between, pose="open")
            for p in st:
                self.frame(p, **kw)

    def arm(self):
        """Show the canvas and wait out the arm delay with the hand open, then show the point pose at the origin."""
        self.hold(0.7, pose="open")
        self.hold(0.2, pose="point")

    def inked(self):
        return any(o.busy for _, o in self.out)


def test_still_commit_fires_half_a_second_after_the_tip_stops():
    d = Drive()
    d.arm()
    st = template_path("O")
    d.draw(st)
    t_stop = d.t - 1 / FPS
    d.hold(1.0)
    assert len(d.commits) == 1
    dt = d.commits[0][0] - t_stop
    assert 0.5 <= dt <= 0.6 + 1e-6, dt


def test_pause_commit_fires_0_6_s_after_pen_up():
    d = Drive()
    d.arm()
    d.draw(template_path("N"))
    d.frame(pose="open")                       # fingers open: the pen goes up
    t_up = d.t - 1 / FPS
    d.hold(1.0, pose="open")
    assert len(d.commits) == 1
    dt = d.commits[0][0] - t_up
    assert 0.6 - 1 / FPS <= dt <= 0.7 + 1e-6, dt


def test_second_stroke_within_the_pause_joins_the_letter_and_a_late_one_does_not():
    x = template_path("X", variant=0)
    for gap, expect in ((0.3, 1), (0.8, 2)):
        d = Drive()
        d.arm()
        d.draw(x, up_between=gap)
        d.hold(1.0, pose="open")
        assert len(d.commits) == expect, (gap, len(d.commits))
    one = Drive()
    one.arm()
    one.draw(x, up_between=0.3)
    one.hold(1.0, pose="open")
    assert len(one.commits[0][1]) == 2


def test_nothing_is_inked_during_the_arm_delay_or_while_inactive():
    d = Drive()
    st = template_path("O")[0][:8]
    d.pos = st[0]
    d.hold(0.1, pose="point")                  # canvas just appeared: the hand coming out of the click pinch
    d.draw([st])
    assert not d.inked() and not any(o.pen for _, o in d.out)
    q = Drive()
    q.hold(0.7, pose="open", active=False)
    q.hold(0.3, pose="point", active=False)
    q.draw(template_path("O"), active=False)
    q.hold(1.0, active=False)
    assert not q.inked() and not q.commits and not any(o.pen for _, o in q.out)


def test_deactivation_drops_pending_ink_and_emits_nothing():
    d = Drive()
    d.arm()
    d.draw(template_path("O"))
    assert d.w.busy
    d.frame(active=False)
    assert not d.w.busy and not d.out[-1][1].pen
    d.hold(1.0, active=False)
    assert not d.commits


def test_a_short_other_blip_keeps_the_stroke_but_open_ends_it():
    d = Drive()
    d.arm()
    st = template_path("O")[0]
    for p in st[:len(st) // 2]:
        d.frame(p)
    for p in st[len(st) // 2:len(st) // 2 + 3]:          # 0.1 s of "other"
        d.frame(p, label="other")
    assert d.out[-1][1].pen
    for p in st[len(st) // 2 + 3:len(st) // 2 + 8]:      # open: the pen is up
        d.frame(p, pose="open")
    assert not d.out[-1][1].pen
    q = Drive()
    q.arm()
    for p in st[:5]:
        q.frame(p)
    for p in st[5:5 + 12]:                               # 0.4 s of "other": longer than the grace
        q.frame(p, label="other")
    assert not q.out[-1][1].pen


def test_a_parked_pen_ignores_jitter_and_a_real_move_starts_a_new_letter():
    d = Drive()
    d.arm()
    d.draw(template_path("O"))
    d.hold(0.8)                                          # still-commit, pen stays down (parked)
    assert len(d.commits) == 1
    rng = random.Random(3)
    end = d.pos
    for _ in range(20):
        d.frame((end[0] + rng.uniform(-0.025, 0.025), end[1] + rng.uniform(-0.025, 0.025)))
    assert not d.w.busy
    for i in range(1, 8):                                # 0.3+ palm away
        d.frame((end[0] + 0.1 * i, end[1]))
    assert d.w.busy


def test_changing_palm_size_mid_letter_does_not_distort_the_letter():
    import recognizer
    base = template_path("N", size=1.5)[0]
    ref = None
    for grow in (False, True):
        d = Drive()
        d.arm()
        n = len(base)
        for i, p in enumerate(base):
            d.frame(p, scale=(1.0 + i / n if grow else 1.0))       # the hand moves closer: palm size doubles
        d.hold(1.0, scale=2.0 if grow else 1.0)
        assert len(d.commits) == 1
        pts = recognizer.prep(d.commits[0][1])
        if ref is None:
            ref = pts
        else:
            assert recognizer.dist(pts, ref) < 0.05


def test_too_short_ink_is_discarded_without_a_commit():
    d = Drive()
    d.arm()
    d.draw([[(0.0, 0.0), (0.12, 0.0), (0.24, 0.0), (0.36, 0.0)]])
    d.hold(1.0)
    assert not d.commits and not d.w.busy


def test_pen_needs_the_point_pose_and_a_raw_pinch_lifts_it():
    d = Drive()
    d.arm()
    st = template_path("O")[0]
    for p in st[:6]:
        d.frame(p)
    assert d.out[-1][1].pen
    d.frame(st[6], pinch=1.0)
    assert not d.out[-1][1].pen


def test_still_inside_a_letter_resets_when_the_tip_moves_on():
    d = Drive()
    d.arm()
    st = template_path("O")[0]
    for p in st[:10]:
        d.frame(p)
    d.hold(0.3)                                          # a short hesitation is not the end
    for p in st[10:]:
        d.frame(p)
    d.hold(1.0)
    assert len(d.commits) == 1
