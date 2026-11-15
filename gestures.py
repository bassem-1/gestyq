"""Gesture engine: tracked hands -> events. Pure Python (no cv2/mediapipe/AppKit/Quartz).

Events (see bindings.gesture_of): continuous "move", "drag_start"/"drag_move"/"drag_end", "scroll" (px,
hand up = positive); discrete hand gestures are Event("gesture", {"id": gesture_id, "pos": (nx, ny)|None},
pulse=True) (flicks also carry "hand": the role that flicked). What a gesture DOES is cfg["bindings"], read here only to decide whether to emit it
(a gesture bound to "none" emits nothing; fist bound to "drag" drags, to anything else fires once per hold).
Air-writing adds Event("write", {"op": "text", "text": "a"} | {"op": "enter"}, pulse=True): a recognised letter. It
is not a rebindable gesture (bindings.gesture_of returns None for it). While the canvas is up (write_active) the
pointer hand's flicks are the gestures write_flick_right / write_flick_left instead of swipe_*.
"""
import math
from collections import deque

import bindings
from config import GAIN_SCALE, POINTER_SCALE
from desktop import ControlBox, RelativePointer, from_norm, margin_box, to_norm
from events import Event
import ink
import recognizer
from restface import RestFilter
from filters import DeadZone, OneEuro, OneEuro2D, RingBuffer, clamp
from tracking import FOUR, HandState, HandTracker, iso, median, palm_anchor, palm_scale

REF = 1000.0   # filters work in 1/1000-screen units so cutoffs/beta are resolution independent


def tile_rect(mode, visible, primary_h):
    """visible = Cocoa (x, y, w, h) with bottom-left origin; returns top-left-origin (x, y, w, h)
    as used by System Events."""
    vx, vy, vw, vh = visible
    top = primary_h - (vy + vh)
    if mode == "left":
        r = (vx, top, vw / 2, vh)
    elif mode == "right":
        r = (vx + vw / 2, top, vw / 2, vh)
    elif mode == "fill":
        r = (vx, top, vw, vh)
    else:  # center ~60%
        w, h = vw * 0.6, vh * 0.6
        r = (vx + (vw - w) / 2, top + (vh - h) / 2, w, h)
    return tuple(int(round(v)) for v in r)


def caption_for(hands, flash=None):
    """hands: {role: label}. Short status for the gadget."""
    if flash:
        return flash
    names = {"right": {"open": "move", "point": "move", "other": "move", "none": "move",
                       "pinch": "pinch", "fist": "drag"},
             "left": {"open": "open", "point": "point", "other": "open", "none": "open",
                      "pinch": "pinch", "fist": "fist", "scroll": "scroll"}}
    if not hands:
        return "no hands"
    active = [(r, l) for r, l in hands.items() if l in ("pinch", "fist", "scroll")]
    r, l = active[0] if active else (("right", hands["right"]) if "right" in hands else next(iter(hands.items())))
    return f"{r} · {names[r].get(l, l)}"


HELD_MODES = ("pinch_wait", "pinch", "fist_wait", "fist_done")     # the cursor stays put in these


class PointerHand:
    """Right hand: palm-anchored cursor, pinch / double pinch, fist (drag by default), optional dwell.

    Two mappings (cfg["pointer_mode"]): "relative" (default, mouse-like, see desktop.RelativePointer) and "absolute"
    (a camera box maps onto the displays)."""

    def __init__(self, cfg):
        self.cfg, self.h = cfg, cfg["hand"]
        self.filt = OneEuro2D(self.h["min_cutoff"], self.h["beta"])
        self.dead = DeadZone(self.h["deadzone"])
        self.buf = RingBuffer(self.h["buffer_window"])
        self.box = margin_box(self.h, 16 / 9, 16 / 9)      # absolute mode: camera control box (x0, y0, w, h)
        self.rel = RelativePointer(self.h)
        self.relative = cfg.get("pointer_mode", "relative") != "absolute"
        self.rects = [(0.0, 0.0, 1920.0, 1080.0)]          # displays, global px (set by the engine)
        self.ref_w = 1920.0                                # px width of the reference display
        self.aspect = 16 / 9                               # camera frame width / height
        self.hint = None                                   # the real cursor (global px): where a new track starts
        self.click_block_until = -1e9                      # a pinch that began before this is a pen lift, not a click
        self.reset()

    def set_relative(self, rel, ev):
        if rel != self.relative:
            self.lost(ev)
            self.relative = rel

    def reset(self):
        self.rel.end_track()
        self.hold_until = -1e9
        self.filt.reset(); self.dead.reset(); self.buf.clear()
        self.mode = "move"            # move | pinch_wait | pinch | fist_wait | fist_done | drag
        self.cur = None               # last cursor position (normalised)
        self.sent = None
        self.t_onset = 0.0
        self.last_click = -1e9
        self.dwell_pos = None
        self.dwell_t = 0.0
        self.dwell_armed = True

    @property
    def dragging(self):
        return self.mode == "drag"

    def map(self, ax, ay):
        x0, y0, w, h = self.box
        return (clamp((x0 + w - ax) / w),                   # x mirrored
                clamp((ay - y0) / h))

    def _move(self, pos, ev, kind="move"):
        if kind == "move" and self.sent is not None and abs(pos[0] - self.sent[0]) < 1e-6 \
                and abs(pos[1] - self.sent[1]) < 1e-6:
            return
        self.sent = pos
        ev.append(Event(kind, pos))

    def lost(self, ev):
        if self.mode == "drag" and self.cur:
            ev.append(Event("drag_end", self.cur))
        self.reset()

    def _place(self, at):
        """The cursor was put back at `at` (normalised): the relative pointer continues from there."""
        if self.relative:
            self.rel.place(from_norm(at, self.rects))

    def restore(self, t_start, now, ev):
        """A flick began at t_start: put the cursor back where it was just before and keep it there a moment."""
        self.hold_until = now + self.h.get("flick_hold", 0.2)
        at = self.buf.at(t_start - 0.03)
        if at is not None and self.mode == "move":
            ev[:] = [e for e in ev if e.kind != "move"]       # this frame's move would only throw the cursor first
            self.sent = None
            self.cur = at
            self._place(at)
            self._move(at, ev)

    def step(self, hs, now, ev, screen, scale, dwell_on, gain=1.0, quiet=False):
        """quiet: air-writing is in progress, so no fist and no dwell on this hand."""
        h = self.h
        held = now < self.hold_until
        if self.relative:
            self.rel.set_params(h["min_cutoff"] * scale, h["beta"] * scale)
            frozen = (self.mode in HELD_MODES or hs.pinch.raw or (hs.fist_raw and self.mode != "drag") or held)
            px = self.rel.update(1.0 - hs.anchor[0], hs.anchor[1] / self.aspect, hs.palm, now, self.rects,
                                 self.ref_w, frozen, gain, self.hint)
            pos = to_norm(px, self.rects)
        else:
            self.filt.set_params(h["min_cutoff"] * scale, h["beta"] * scale)
            nx, ny = self.map(*hs.anchor)
            fx, fy = self.filt(nx * REF, ny * REF, now)
            dx, dy = self.dead(fx, fy)
            pos = (dx / REF, dy / REF)
        self.buf.push(now, pos)
        pn, label = hs.pinch, hs.label
        act = lambda g: bindings.action_for(self.cfg, g)
        m = self.mode
        if m == "move":
            if pn.raw:                          # a pinch always wins over a fist and never starts a drag
                self.mode, self.t_onset = "pinch_wait", pn.onset
            elif label == "fist" and act("fist") != "none" and not quiet:
                self.mode, self.t_onset = "fist_wait", hs.label_since
            else:
                if not held:
                    self.cur = pos
                    self._move(pos, ev)
                if dwell_on and not quiet:
                    self._dwell(self.cur or pos, now, ev, screen)
                return
            m = self.mode
        if m == "pinch_wait":
            if not pn.raw:
                self.mode = "move"
            elif pn.confirmed:
                at = self.buf.at(self.t_onset - h["click_lookback"]) or self.cur or pos
                self.cur = at
                self._place(at)
                self._move(at, ev)
                dbl = now - self.last_click < h["double_click_gap"] and act("double_pinch") != "none"
                guarded = self.t_onset <= self.click_block_until
                if not guarded:
                    self.last_click = -1e9 if dbl else now
                gid = "double_pinch" if dbl else "pinch"
                if act(gid) != "none" and not guarded:
                    ev.append(Event("gesture", {"id": gid, "pos": (at[0], at[1])}, pulse=True))
                self.mode = "pinch"
        elif m == "pinch":
            if not pn.raw:
                self.mode = "move"
        elif m == "fist_wait":
            if label != "fist" or pn.raw:
                self.mode = "move"
            elif now - self.t_onset >= h["fist_hold"]:
                at = self.buf.at(self.t_onset - h["click_lookback"]) or self.cur or pos
                self.cur = at
                self._place(at)
                self._move(at, ev)
                if act("fist") == "drag":
                    ev.append(Event("drag_start", at, pulse=True))
                    self.mode = "drag"
                else:                           # discrete action: once per hold
                    ev.append(Event("gesture", {"id": "fist", "pos": (at[0], at[1])}, pulse=True))
                    self.mode = "fist_done"
        elif m == "fist_done":
            if label != "fist":
                self.mode = "move"
        elif m == "drag":
            if label != "fist":
                ev.append(Event("drag_end", self.cur))
                self.mode = "move"
            else:
                self.cur = pos
                self._move(pos, ev, "drag_move")

    def _dwell(self, pos, now, ev, screen):
        h = self.h
        px = (pos[0] * screen[0], pos[1] * screen[1])
        if self.dwell_pos is None:
            self.dwell_pos, self.dwell_t = px, now
            return
        d = math.hypot(px[0] - self.dwell_pos[0], px[1] - self.dwell_pos[1])
        if not self.dwell_armed:
            if d > h["dwell_rearm"]:
                self.dwell_armed = True
                self.dwell_pos, self.dwell_t = px, now
            return
        if d > h["dwell_radius"]:
            self.dwell_pos, self.dwell_t = px, now
        elif now - self.dwell_t >= h["dwell_time"]:
            if bindings.action_for(self.cfg, "dwell") != "none":
                ev.append(Event("gesture", {"id": "dwell", "pos": (pos[0], pos[1])}, pulse=True))
            self.dwell_armed = False
            self.last_click = -1e9


class CommandHand:
    """Left hand: pinch (right click) and two-finger vertical scroll. (Flicks are handled for both hands by the
    engine, see FlickDetector.)"""

    def __init__(self, cfg):
        self.cfg, self.h = cfg, cfg["hand"]
        self.fy = OneEuro(1.5, 0.01)
        self.reset()

    def reset(self):
        self.fy.reset()
        self.pinched = False
        self.prev_y = None
        self.acc = 0.0
        self.last_scroll = -1e9

    def step(self, hs, now, ev, cursor):
        h = self.h
        act = lambda g: bindings.action_for(self.cfg, g)
        pn, label = hs.pinch, hs.label
        if pn.confirmed:
            if not self.pinched:
                self.pinched = True
                if act("left_pinch") != "none":
                    ev.append(Event("gesture", {"id": "left_pinch", "pos": cursor}, pulse=True))
        else:
            self.pinched = False
        # scroll (two fingers up; hand up = positive px; the executor flips it for scroll_inverted)
        if label == "scroll" and not pn.raw and act("two_finger") != "none":
            y = self.fy(hs.anchor[1] * REF, now) / REF
            if self.prev_y is not None:
                d = (self.prev_y - y)                    # hand up -> positive (scroll up)
                if abs(d) >= h["scroll_deadzone"]:
                    self.acc += d * h["scroll_gain"] * (-1 if h["scroll_invert"] else 1)
                    px = int(self.acc)
                    if px:
                        self.acc -= px
                        burst = now - self.last_scroll > 0.4
                        self.last_scroll = now
                        ev.append(Event("scroll", px, pulse=burst))
            self.prev_y = y
        else:
            self.prev_y, self.acc = None, 0.0
            self.fy.reset()

    def lost(self):
        self.reset()


class FlickDetector:
    """A quick sideways flick of one hand, in ANY pose (like waving a fly away). Everything is in palm sizes, so a
    near and a far hand behave alike. Per frame it looks at the last flick_time s of the palm anchor:

      speed   the peak |dx| / dt over >= flick_span (palm sizes / s) must reach flick_speed. Cursor moves run
              2-6 palm/s; a flick is a short burst above 10.
      travel  the largest monotone sideways run in that window, in palm sizes, >= flick_travel (0.8), spread over
              at least three samples with no single jump above 75% of it (a tracking glitch is not a flick).
      line    |dy| <= flick_vert x |dx| (mostly sideways).

    update() returns None (nothing happening) or a dict with dir (+1 = toward the user's right), peak, travel,
    dy, start (time the run began) and why ("" = a flick; else why not). The engine applies the global rules
    (gap, return stroke, vetoes) and calls reset() on the detector that fired."""

    def __init__(self, h):
        self.h = h
        self.tr = deque()                 # (t, x, y, palm); x mirrored (user's right = +), x/y in frame widths

    def reset(self):
        self.tr.clear()

    def update(self, now, x, y, palm, blocked):
        h = self.h
        if blocked or (self.tr and now - self.tr[-1][0] > 0.15):
            self.tr.clear()
        if blocked:
            return None
        self.tr.append((now, x, y, palm))
        while self.tr and now - self.tr[0][0] > h["flick_time"]:
            self.tr.popleft()
        tr, n = self.tr, len(self.tr)
        if n < 3:
            return None
        pm = max(median([p[3] for p in tr]), 1e-3)
        span = h.get("flick_span", 0.05)
        peak, pdir, i = 0.0, 0, 0
        for j in range(1, n):
            while i + 1 < j and tr[j][0] - tr[i + 1][0] >= span:
                i += 1
            dt = tr[j][0] - tr[i][0]
            if dt < span:
                continue
            v = (tr[j][1] - tr[i][1]) / dt / pm
            if abs(v) > peak:
                peak, pdir = abs(v), 1 if v > 0 else -1
        if peak < 0.6 * h["flick_speed"]:
            return None
        best, lo, lo_k, a, b = 0.0, 1e9, 0, 0, 0
        for k, p in enumerate(tr):
            v = pdir * p[1]
            if v <= lo:
                lo, lo_k = v, k
            if v - lo > best:
                best, a, b = v - lo, lo_k, k
        travel = best / pm
        dy = abs(tr[b][2] - tr[a][2]) / pm
        step = max((abs(tr[k][1] - tr[k - 1][1]) for k in range(a + 1, b + 1)), default=0.0) / pm
        why = ""
        if peak < h["flick_speed"]:
            why = "slow"
        elif travel < h["flick_travel"]:
            why = "short"
        elif b - a < 2 or step > 0.75 * travel:
            why = "single jump"
        elif dy > h["flick_vert"] * travel:
            why = "too vertical"
        return {"dir": pdir, "peak": peak, "travel": travel, "dy": dy, "start": tr[a][0], "why": why,
                "n": n, "palm": pm, "travel_x": best}


class GestureEngine:
    def __init__(self, cfg, screen=(1920, 1080)):
        self.cfg, self.h = cfg, cfg["hand"]
        self.tracker = HandTracker(cfg["handedness"], cfg["hand"].get("spawn_frames", 5))
        self.face_box, self.face_t = None, -1e9
        self.rejected = []
        self.rest = RestFilter(cfg["hand"])
        self.resting = []                # hands ignored because they rest on the face / head (live view dims them)
        self.states = {"right": HandState(self.h), "left": HandState(self.h)}
        self.last_seen = {"right": -1e9, "left": -1e9}
        self.pointer = PointerHand(cfg)
        self.command = CommandHand(cfg)
        self.flicks = {"right": FlickDetector(self.h), "left": FlickDetector(self.h)}
        self.xh = {"right": deque(), "left": deque()}     # (t, mirrored x) per role, for the two-hand vetoes
        self.fl_t, self.fl_dir, self.flick_veto_until = -1e9, 0, -1e9
        self.trace_t = {}
        self.screen = screen
        self.rects = None                # displays in global px; None = one display of `screen`
        self.aspect = 16 / 9             # camera frame width / height
        self.union_aspect = 16 / 9       # all displays together, width / height
        self.union_span = 1.0            # ... width / width of the primary display
        self.cbox = ControlBox(self.h)
        self.tile_hist = deque()
        self.tile_last = -1e9
        self.flash_text, self.flash_until = None, 0.0
        self.debug = []
        self.labels = {}
        # air-writing (see ink.py, recognizer.py): the vision thread sets write_active each frame
        self.writer = ink.Writer(cfg)
        self.recognizer = recognizer.make(cfg)
        self.write_active = False
        self.write_shown_at = None
        self.ink = None                  # latest canvas snapshot (see _ink_view), None while the canvas is away
        self.ink_n = 0
        self.typed = ""
        self.ink_result = None
        self._w = None
        self._ink_sig = None

    def reset(self):
        self.tracker.reset()
        for s in self.states.values():
            s.reset()
        self.last_seen = {"right": -1e9, "left": -1e9}
        self.pointer.reset()
        self.command.reset()
        self.cbox.reset()
        self.rest.reset()
        self.resting = []
        self.tile_hist.clear()
        for k in ("right", "left"):
            self.flicks[k].reset()
            self.xh[k].clear()
        self.debug, self.labels = [], {}
        self._write_reset()

    def _write_reset(self):
        self.writer.reset()
        self.typed, self.ink_result, self.ink, self._w, self._ink_sig = "", None, None, None, None

    def observe_face(self, geom, now, far=None):
        """geom: roi.FaceGeom in full-frame coords (or None); far: the camera is zoomed (user far away),
        which switches the ABSOLUTE pointer to the body-relative control box."""
        self.cbox.observe_face(geom, now)
        if far is not None:
            self.cbox.set_far(far)

    @property
    def dragging(self):
        return self.pointer.dragging

    @property
    def relative(self):
        return self.cfg.get("pointer_mode", "relative") != "absolute"

    def flash(self, text, now, dur=1.0):
        self.flash_text, self.flash_until = text, now + dur

    def release(self):
        """Returns events that release anything held (call when switching off)."""
        ev = []
        self.pointer.lost(ev)
        self.command.lost()
        self._write_reset()
        return ev

    def caption(self, now):
        return caption_for(self.labels, self.flash_text if now < self.flash_until else None)

    def _face_veto(self, obs, now, face_box):
        """Drop phantom hands on the face: palm centre inside the face box shrunk to ~70%, hand small
        next to the face (a real hand held up is big), or low handedness confidence inside the box.
        Keeps the last box face_hold seconds. Returns (kept, rejected obs)."""
        h = self.h
        if face_box is not None:
            self.face_box, self.face_t = face_box, now
        fresh = self.face_box is not None and now - self.face_t <= h.get("face_hold", 0.5)
        box = self.face_box if now - self.face_t <= h.get("rest_keep", 3.0) else None
        obs, self.resting = self.rest.split(obs, now, self.aspect, box, fresh)
        if not fresh:
            return list(obs), []
        x0, y0, x1, y1 = self.face_box
        cx, cy, sx, sy = (x0 + x1) / 2, (y0 + y1) / 2, 0.35 * (x1 - x0), 0.35 * (y1 - y0)
        face_h = (y1 - y0) / self.aspect                  # in frame widths, like palm_scale
        kept, bad = [], []
        for o in obs:
            ax, ay = palm_anchor(o.lms)
            inside = abs(ax - cx) <= sx and abs(ay - cy) <= sy
            small = palm_scale(iso(o.lms, self.aspect)) < h.get("face_palm_ratio", 0.4) * face_h
            if inside and (small or o.conf < h.get("face_min_conf", 0.6)):
                bad.append(o)
            else:
                kept.append(o)
        return kept, bad

    def _print_limited(self, key, now, text, every=0.8):
        if now - self.trace_t.get(key, -1e9) >= every:
            self.trace_t[key] = now
            print(text, flush=True)

    def _fist_trace(self, role, st, now):
        """Diagnostic for tuning the fist classifier from a real log: a hand with >= 3 curled fingers."""
        curled = [f for f in FOUR if st.states.get(f) == "curl"]
        if len(curled) < 3:
            return
        r, m = st.reach, st.reach_med
        self._print_limited(("fist", role), now,
                            f"fist-trace {role} curled={len(curled)} reach i/m/r/p="
                            f"{'/'.join(f'{r[f]:.2f}' for f in FOUR)} median={'/'.join(f'{m[f]:.2f}' for f in FOUR)} "
                            f"limit={st.fist_limit:.2f} palm={st.palm:.3f} pose_raw={st.pose_raw} label={st.label} "
                            f"pinch={st.ratio:.2f}", every=1.0)

    def update(self, obs, now, face_box=None):
        cfg, h = self.cfg, self.h
        ev = []
        obs, self.rejected = self._face_veto(obs, now, face_box)
        tracked = self.tracker.update(obs, now, swap=bool(cfg.get("swap_hands")))
        by = {t.role: t for t in tracked}
        self.debug = []
        self.labels = {}
        for role, t in by.items():
            st = self.states[role]
            st.update(t.obs.lms, self.aspect, now)
            self.last_seen[role] = now
            self.labels[role] = "pinch" if st.pinch.confirmed else st.label
            self._fist_trace(role, st, now)
            self.debug.append({"role": role, "vote": t.vote, "score": t.score, "label_mp": t.obs.label,
                               "fingers": dict(st.states), "ratio": st.ratio, "pose": st.label,
                               "pose_raw": st.pose_raw, "reach": dict(st.reach), "reach_med": dict(st.reach_med),
                               "pinch": st.pinch.confirmed, "pinch_raw": st.pinch.raw,
                               "anchor": st.anchor, "lms": t.obs.lms})
        roles = tuple(sorted((r, round(1 - self.states[r].anchor[0], 2)) for r in by))
        if tuple(r for r, _ in roles) != getattr(self, "_roles_seen", None):
            self._roles_seen = tuple(r for r, _ in roles)
            print(f"roles-trace {' '.join(f'{r}@x={x}' for r, x in roles) or 'none'}", flush=True)
        speed = int(cfg.get("pointer_speed", 2))
        rel = self.relative
        pt = self.pointer
        pt.set_relative(rel, ev)
        o = self._write_step(by, now, ev)
        # right hand = pointer
        if "right" in by and speed > 0:
            rs = self.states["right"]
            pt.rects = self.rects or [(0.0, 0.0, float(self.screen[0]), float(self.screen[1]))]
            pt.ref_w = self.screen[0] / max(self.union_span, 0.1)
            pt.aspect = self.aspect
            if not rel:
                frozen = pt.mode != "move" or rs.pinch.raw or rs.fist_raw
                pt.box = self.cbox.update(now, frozen, self.union_aspect, self.aspect,
                                          -1 if cfg.get("swap_hands") else 1, self.union_span)
            pt.step(rs, now, ev, self.screen, POINTER_SCALE.get(speed, 1.0), bool(cfg.get("dwell_click")),
                    GAIN_SCALE.get(speed, 1.0), o is not None and (o.pen or o.busy))
        elif now - self.last_seen["right"] > h["loss_grace"] or speed <= 0:
            pt.lost(ev)
        # left hand = commands
        if "left" in by:
            self.command.step(self.states["left"], now, ev, pt.cur)
        elif now - self.last_seen["left"] > h["loss_grace"]:
            self.command.lost()
        for role in ("right", "left"):
            if role not in by and now - self.last_seen[role] > h["loss_grace"]:
                self.flicks[role].reset()
                self.xh[role].clear()
        self._flicks(by, now, ev)
        # both palms open -> tiling
        if (cfg.get("tiling", True) and "right" in by and "left" in by
                and self.states["right"].confident_open(now) and self.states["left"].confident_open(now)
                and not self.states["right"].pinch.raw and not self.states["left"].pinch.raw):
            self._tile(self.states["right"], self.states["left"], now, ev)
        else:
            self.tile_hist.clear()
        for e in ev:
            gid = bindings.gesture_of(e)
            if gid and e.kind in ("gesture", "drag_start"):
                hand = bindings.GESTURES[gid]["hand"]
                role = (e.value.get("hand") if e.kind == "gesture" else None) or \
                    {"pointer": "right", "command": "left"}.get(hand, "both")
                label = bindings.ACTIONS[bindings.action_for(cfg, gid)]["label"]
                self.flash(f"{role} · {label}", now, 0.5 if e.kind == "gesture" else 0.3)
        return ev

    # -- air-writing
    def _write_step(self, by, now, ev):
        """Steps the Writer for the pointer hand, applies its cursor / click effects, recognises a finished letter
        and builds the canvas snapshot. -> the Writer's Out, or None while the canvas is away."""
        w = self.cfg["write"]
        active = bool(self.write_active and w["enabled"])
        if not active:
            self.writer.shown_at = None
            if self._w is not None or self.ink is not None or self.writer.was_active:
                self._write_reset()
            self._w = None
            return None
        if not self.writer.was_active:
            self.typed, self.ink_result = "", None
            self.writer.shown_at = self.write_shown_at
        rs = self.states["right"] if "right" in by else None
        lms = by["right"].obs.lms if rs is not None else None
        if self.write_shown_at is not None:
            self.writer.shown_at = self.write_shown_at
        o = self.writer.step(rs, lms, self.aspect, now, True, free=self.pointer.mode == "move")
        self._w = o
        if o.freeze:
            self.pointer.hold_until = max(self.pointer.hold_until, now + w["cursor_hold"])
        self.pointer.click_block_until = self.writer.last_pen + w["click_guard"]
        if o.commit:
            self._write_commit(o.commit, now, ev)
        elif o.result == "small":
            self.ink_result = {"t": now, "char": None, "alt": None, "why": "small", "strokes": ()}
        self._ink_view(now)
        return o

    def _typed(self, action):
        if action == "type_space":
            self.typed = (self.typed + " ")[-16:]
        elif action == "backspace":
            self.typed = self.typed[:-1]

    def _write_commit(self, strokes, now, ev):
        if not strokes:
            return
        cands = self.recognizer.recognize(strokes)
        keep = tuple(tuple(s) for s in strokes)
        if not cands:
            self.ink_result = {"t": now, "char": None, "alt": None, "why": "reject", "strokes": keep}
            return
        ch = cands[0].char
        alt = cands[1].char if self.recognizer.unsure(cands) and cands[1].char != "\n" else None
        if ch == "\n":
            ev.append(Event("write", {"op": "enter"}, pulse=True))
        else:
            ev.append(Event("write", {"op": "text", "text": ch}, pulse=True))
            self.typed = (self.typed + ch)[-16:]
        self.flash("write · " + ("enter" if ch == "\n" else ch), now, 0.5)
        self.ink_result = {"t": now, "char": ch, "alt": alt, "why": "", "strokes": keep}

    def _ink_view(self, now):
        """The canvas snapshot (state["ink"]): a new tuple dict with n bumped whenever anything the view shows changed."""
        v = self.writer.view()
        r = self.ink_result
        sig = (v["strokes"], v["tip"], v["pen"], v["hand"], self.writer.armed(now), r and r["t"], self.typed)
        if sig != self._ink_sig:
            self._ink_sig = sig
            self.ink_n += 1
            self.ink = {"n": self.ink_n, "strokes": v["strokes"], "tip": v["tip"], "pen": v["pen"], "hand": v["hand"],
                        "armed": sig[4], "result": dict(r) if r else None, "typed": self.typed}

    # -- flicks
    def _flick_blocked(self, role, st, now):
        """Any pose may flick except an active pinch, drag or two-finger scroll."""
        if st.pinch.raw or st.pinch.confirmed or st.pose_raw == "scroll" or st.label == "scroll" \
                or now - st.scroll_seen <= self.h.get("scroll_veto", 0.6):
            return True
        if role == "right" and self._w is not None and (self._w.pen or now - self.writer.last_pen < 0.2):
            return True                  # a pen stroke is not a flick
        return role == "right" and self.pointer.mode in ("pinch_wait", "pinch", "fist_wait", "fist_done", "drag")

    def _moved(self, role, since, now):
        """Signed sideways travel (frame widths, + = user's right) of a hand since `since` (or None)."""
        pts = [p for p in self.xh[role] if p[0] >= since - 0.03]
        return pts[-1][1] - pts[0][1] if len(pts) >= 2 else None

    def _flicks(self, by, now, ev):
        h, cfg = self.h, self.cfg
        for role, t in by.items():
            st = self.states[role]
            x, y = 1.0 - st.anchor[0], st.anchor[1] / self.aspect
            xh = self.xh[role]
            xh.append((now, x))
            while xh and now - xh[0][0] > 0.5:
                xh.popleft()
        for role in ("right", "left"):
            if role not in by:
                continue
            st = self.states[role]
            x, y = 1.0 - st.anchor[0], st.anchor[1] / self.aspect
            c = self.flicks[role].update(now, x, y, st.palm, self._flick_blocked(role, st, now))
            if c is None:
                continue
            writing = role == "right" and self._w is not None
            gid = ("write_flick_" if writing else "swipe_") + ("right" if c["dir"] > 0 else "left")
            why = c["why"]
            if not why:
                other = "left" if role == "right" else "right"
                om = self._moved(other, c["start"], now) if other in by else None
                if c["dir"] == -self.fl_dir and now - self.fl_t < h["flick_return"]:
                    why = "return stroke"
                elif now - self.fl_t < h["flick_gap"]:
                    why = "gap"
                elif now < self.flick_veto_until:
                    why = "just tiled"
                elif (cfg.get("tiling", True) and om is not None and c["dir"] * om >= 0.5 * c["travel_x"]
                      and self.states[other].confident_open(now) and st.confident_open(now)):
                    why = "vetoed: both palms moving (tiling)"
                elif bindings.action_for(cfg, gid) == "none":
                    why = "unbound"
            if not why:
                why = "fired " + gid
                self.fl_t, self.fl_dir = now, c["dir"]
                self.flicks[role].reset()
                if writing and self.writer.busy:
                    # ink is pending: left throws it away, right finishes the letter before the space
                    if c["dir"] < 0:
                        self.writer.discard()
                        self.ink_result = None
                        continue
                    self._write_commit(self.writer.commit_now(now), now, ev)
                ev.append(Event("gesture", {"id": gid, "pos": None, "hand": role}, pulse=True))
                if writing:
                    self._typed(bindings.action_for(cfg, gid))
                if role == "right":
                    self.pointer.restore(c["start"], now, ev)
                print(f"flick-trace {'right' if c['dir'] > 0 else 'left'} hand={role} peak={c['peak']:.1f} palm/s "
                      f"travel={c['travel']:.2f} palm dy={c['dy']:.2f} palm={c['palm']:.3f} frames={c['n']} "
                      f"need>={h['flick_speed']:.0f} palm/s, {h['flick_travel']} palm why={why}", flush=True)
            else:
                self._print_limited(("flick", role, why), now,
                                    f"flick-trace {'right' if c['dir'] > 0 else 'left'} hand={role} "
                                    f"peak={c['peak']:.1f} palm/s travel={c['travel']:.2f} palm dy={c['dy']:.2f} "
                                    f"palm={c['palm']:.3f} frames={c['n']} need>={h['flick_speed']:.0f} palm/s, "
                                    f"{h['flick_travel']} palm why={why}", every=0.5)

    def _tile(self, rs, ls, now, ev):
        c = self.h
        xr, xl = 1 - rs.anchor[0], 1 - ls.anchor[0]
        self.tile_hist.append((now, (xr + xl) / 2, abs(xr - xl), (rs.palm + ls.palm) / 2, xr, xl))
        while self.tile_hist and now - self.tile_hist[0][0] > c["tile_window"]:
            self.tile_hist.popleft()
        if now - self.tile_last < c["tile_cooldown"] or len(self.tile_hist) < 2:
            return
        palm = sorted(p[3] for p in self.tile_hist)[len(self.tile_hist) // 2]       # palm sizes: distance independent
        first, last = self.tile_hist[0], self.tile_hist[-1]
        dcx = last[1] - first[1]
        dgap = last[2] - first[2]
        # both palms must travel: one hand's flick next to a resting open palm changes the gap but is no tiling
        if min(abs(last[4] - first[4]), abs(last[5] - first[5])) < c.get("tile_both", 0.5) * palm:
            return
        mv, gp = c["tile_move"] * palm, c["tile_gap"] * palm
        cands = [("left", -dcx / mv), ("right", dcx / mv), ("fill", dgap / gp), ("center", -dgap / gp)]
        mode, score = max(cands, key=lambda t: t[1])
        if score >= 0.6 and now - getattr(self, "_tile_trace_t", -1e9) > 0.8:
            self._tile_trace_t = now
            print(f"tile-trace {mode} score={score:.2f} dcx={dcx:+.2f} dgap={dgap:+.2f} palm={palm:.3f}", flush=True)
        if score >= 1.0:
            gid = {"left": "palms_left", "right": "palms_right", "fill": "palms_apart",
                   "center": "palms_together"}[mode]
            self.tile_hist.clear()
            if bindings.action_for(self.cfg, gid) != "none":
                ev.append(Event("gesture", {"id": gid, "pos": None}, pulse=True))
                self.tile_last = now
                self.flick_veto_until = now + 0.8
