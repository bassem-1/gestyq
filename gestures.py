"""Gesture engine: tracked hands -> events. Pure Python (no cv2/mediapipe/AppKit/Quartz)."""
import math
from collections import deque

from config import POINTER_SCALE
from events import Event
from filters import DeadZone, OneEuro, OneEuro2D, RingBuffer, clamp
from tracking import HandState, HandTracker

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


class PointerHand:
    """Right hand: palm-anchored cursor, pinch click, fist drag, optional dwell click."""

    def __init__(self, cfg):
        self.cfg, self.h = cfg, cfg["hand"]
        self.filt = OneEuro2D(self.h["min_cutoff"], self.h["beta"])
        self.dead = DeadZone(self.h["deadzone"])
        self.buf = RingBuffer(self.h["buffer_window"])
        self.reset()

    def reset(self):
        self.filt.reset(); self.dead.reset(); self.buf.clear()
        self.mode = "move"            # move | pinch_wait | pinch | fist_wait | drag
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
        h = self.h
        mx, my = h["frame_margin_x"], h["frame_margin_y"]
        return (clamp((1.0 - ax - mx) / (1 - 2 * mx)),      # x mirrored
                clamp((ay - my) / (1 - 2 * my)))

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

    def step(self, hs, now, ev, screen, scale, dwell_on):
        h = self.h
        self.filt.set_params(h["min_cutoff"] * scale, h["beta"] * scale)
        nx, ny = self.map(*hs.anchor)
        fx, fy = self.filt(nx * REF, ny * REF, now)
        dx, dy = self.dead(fx, fy)
        pos = (dx / REF, dy / REF)
        self.buf.push(now, pos)
        pn, label = hs.pinch, hs.label
        m = self.mode
        if m == "move":
            if pn.raw and not hs.fist_raw:
                self.mode, self.t_onset = "pinch_wait", pn.onset
            elif label == "fist":
                self.mode, self.t_onset = "fist_wait", hs.label_since
            else:
                self.cur = pos
                self._move(pos, ev)
                if dwell_on:
                    self._dwell(pos, now, ev, screen)
                return
            m = self.mode
        if m == "pinch_wait":
            if not pn.raw:
                self.mode = "move"
            elif pn.confirmed:
                at = self.buf.at(self.t_onset - h["click_lookback"]) or self.cur or pos
                self.cur = at
                self._move(at, ev)
                count = 2 if now - self.last_click < h["double_click_gap"] else 1
                self.last_click = -1e9 if count == 2 else now
                ev.append(Event("click", (at[0], at[1], count), pulse=True))
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
                self._move(at, ev)
                ev.append(Event("drag_start", at, pulse=True))
                self.mode = "drag"
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
            ev.append(Event("click", (pos[0], pos[1], 1), pulse=True))
            self.dwell_armed = False
            self.last_click = -1e9


class CommandHand:
    """Left hand: pinch = right click, two-finger vertical = scroll, fast open-palm swipe = space."""

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
        self.swipe = deque()
        self.swipe_last = -1e9
        self.scrolling = False

    def step(self, hs, now, ev, cursor, veto_swipe):
        h = self.h
        pn, label = hs.pinch, hs.label
        if pn.confirmed:
            if not self.pinched:
                self.pinched = True
                ev.append(Event("right_click", cursor, pulse=True))
        else:
            self.pinched = False
        # scroll
        if label == "scroll" and not pn.raw:
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
        # swipe
        x = 1.0 - hs.anchor[0]
        y = hs.anchor[1]
        if label == "open" and not pn.raw:
            self.swipe.append((now, x, y))
            while self.swipe and now - self.swipe[0][0] > h["swipe_time"]:
                self.swipe.popleft()
            t0, x0, y0 = self.swipe[0]
            dx, dy = x - x0, y - y0
            if (now - self.swipe_last >= h["swipe_cooldown"] and abs(dx) >= h["swipe_dist"]
                    and abs(dy) < 0.5 * abs(dx) and not veto_swipe(dx, t0, now)):
                self.swipe_last = now
                self.swipe.clear()
                # hand moves to the user's left -> next space (trackpad convention)
                ev.append(Event("space", "right" if dx < 0 else "left", pulse=True))
        else:
            self.swipe.clear()

    def lost(self):
        self.reset()


class GestureEngine:
    def __init__(self, cfg, screen=(1920, 1080)):
        self.cfg, self.h = cfg, cfg["hand"]
        self.tracker = HandTracker(cfg["handedness"])
        self.states = {"right": HandState(self.h), "left": HandState(self.h)}
        self.last_seen = {"right": -1e9, "left": -1e9}
        self.pointer = PointerHand(cfg)
        self.command = CommandHand(cfg)
        self.screen = screen
        self.aspect = 16 / 9
        self.tile_hist = deque()
        self.tile_last = -1e9
        self.xr_hist = deque()
        self.flash_text, self.flash_until = None, 0.0
        self.debug = []
        self.labels = {}

    def reset(self):
        self.tracker.reset()
        for s in self.states.values():
            s.reset()
        self.last_seen = {"right": -1e9, "left": -1e9}
        self.pointer.reset()
        self.command.reset()
        self.tile_hist.clear()
        self.xr_hist.clear()
        self.debug, self.labels = [], {}

    @property
    def dragging(self):
        return self.pointer.dragging

    def flash(self, text, now, dur=1.0):
        self.flash_text, self.flash_until = text, now + dur

    def release(self):
        """Returns events that release anything held (call when switching off)."""
        ev = []
        self.pointer.lost(ev)
        self.command.lost()
        return ev

    def caption(self, now):
        return caption_for(self.labels, self.flash_text if now < self.flash_until else None)

    def _veto_swipe(self, now):
        def veto(dxl, t0, t1):
            if "right" not in self.labels or self.labels["right"] != "open":
                return False
            pts = [p for p in self.xr_hist if p[0] >= t0]
            if len(pts) < 2:
                return False
            dxr = pts[-1][1] - pts[0][1]
            return dxr * dxl > 0 and abs(dxr) >= 0.5 * abs(dxl)
        return veto

    def update(self, obs, now):
        cfg, h = self.cfg, self.h
        ev = []
        tracked = self.tracker.update(obs, now, swap=bool(cfg.get("swap_hands")))
        by = {t.role: t for t in tracked}
        self.debug = []
        self.labels = {}
        for role, t in by.items():
            st = self.states[role]
            st.update(t.obs.lms, self.aspect, now)
            self.last_seen[role] = now
            self.labels[role] = "pinch" if st.pinch.confirmed else st.label
            self.debug.append({"role": role, "vote": t.vote, "score": t.score, "label_mp": t.obs.label,
                               "fingers": dict(st.states), "ratio": st.ratio, "pose": st.label,
                               "pinch": st.pinch.confirmed, "anchor": st.anchor, "lms": t.obs.lms})
        speed = int(cfg.get("pointer_speed", 2))
        # right hand = pointer
        if "right" in by and speed > 0:
            self.pointer.step(self.states["right"], now, ev, self.screen,
                              POINTER_SCALE.get(speed, 1.0), bool(cfg.get("dwell_click")))
            r = self.states["right"]
            if r.label == "open":
                self.xr_hist.append((now, 1.0 - r.anchor[0]))
            while self.xr_hist and now - self.xr_hist[0][0] > 0.6:
                self.xr_hist.popleft()
        elif now - self.last_seen["right"] > h["loss_grace"] or speed <= 0:
            self.pointer.lost(ev)
            self.xr_hist.clear()
        # left hand = commands
        if "left" in by:
            self.command.step(self.states["left"], now, ev, self.pointer.cur, self._veto_swipe(now))
        elif now - self.last_seen["left"] > h["loss_grace"]:
            self.command.lost()
        # both palms open -> tiling
        if (cfg.get("tiling", True) and "right" in by and "left" in by
                and self.labels["right"] == "open" and self.labels["left"] == "open"):
            self._tile(self.states["right"].anchor, self.states["left"].anchor, now, ev)
        else:
            self.tile_hist.clear()
        for e in ev:
            if e.kind == "click":
                self.flash("right · click" if e.value[2] == 1 else "right · double click", now, 0.5)
            elif e.kind == "right_click":
                self.flash("left · right click", now, 0.5)
            elif e.kind == "drag_start":
                self.flash("right · drag", now, 0.3)
            elif e.kind == "space":
                self.flash("left · space " + e.value, now, 0.8)
        return ev

    def _tile(self, right, left, now, ev):
        c = self.h
        xr, xl = 1 - right[0], 1 - left[0]
        self.tile_hist.append((now, (xr + xl) / 2, abs(xr - xl)))
        while self.tile_hist and now - self.tile_hist[0][0] > c["tile_window"]:
            self.tile_hist.popleft()
        if now - self.tile_last < c["tile_cooldown"] or len(self.tile_hist) < 2:
            return
        dcx = self.tile_hist[-1][1] - self.tile_hist[0][1]
        dgap = self.tile_hist[-1][2] - self.tile_hist[0][2]
        cands = [("left", -dcx / c["tile_move"]), ("right", dcx / c["tile_move"]),
                 ("fill", dgap / c["tile_gap"]), ("center", -dgap / c["tile_gap"])]
        mode, score = max(cands, key=lambda t: t[1])
        if score >= 1.0:
            ev.append(Event("tile", mode, pulse=True))
            self.tile_last = now
            self.tile_hist.clear()
            self.flash("tile " + mode, now, 0.8)
