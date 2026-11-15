"""Popover content (300 wide, black). Laid out by hand from the haptyq spec."""
import objc
from AppKit import NSMakeRect

from config import HEAD_NAMES, POINTER_NAMES, VERSION
from . import theme as T
from .widgets import (Flipped, PulseDot, Row, Rule, SignalBar, Switch, TextButton, make_text, rrect)

W = T.POPOVER_W
PAD = T.PAD


class Banner(Flipped):
    def drawRect_(self, rect):
        T.line().setStroke()
        p = rrect(0.5, 0.5, self.frame().size.width - 1, self.frame().size.height - 1, T.RADIUS)
        p.setLineWidth_(1)
        p.stroke()


class PopoverContent(Flipped):
    """`model` provides: cfg, state, set(key, value), set_enabled(bool), trusted, grant_access(),
    refresh_trust(), cycle_camera(), camera_label(), display_count(), quit()."""

    def initWithModel_(self, model):
        self = objc.super(PopoverContent, self).initWithFrame_(NSMakeRect(0, 0, W, 400))
        self.model = model
        self.grant_clicked = False
        self._build()
        self.refresh()
        return self

    # -- construction
    def _row(self, title, control, right_edge=W - PAD):
        row = Row.alloc().initWithWidth_(W)
        t = make_text(title, T.SIZE_TITLE, "fg", h=T.ROW)
        t.setFrameOrigin_((PAD, 0))
        row.addSubview_(t)
        control.setFrameOrigin_((right_edge - control.frame().size.width,
                                 (T.ROW - control.frame().size.height) / 2))
        row.addSubview_(control)
        self.addSubview_(row)
        return row

    def _build(self):
        m = self.model
        cfg = m.cfg
        self.title = make_text("gestyq", T.SIZE_TITLE, "fg", medium=True, h=18)
        self.tagline = make_text("your hands and head, in control.", T.SIZE_SMALL, "fg2", w=220, h=16)
        self.master = Switch.alloc().initWithOn_callback_(m.state.get()["enabled"], m.set_enabled)
        for v in (self.title, self.tagline, self.master):
            self.addSubview_(v)

        mk = lambda key, names: SignalBar.alloc().initWithLevel_names_callback_(
            int(cfg[key]), names, lambda lv, k=key: m.set(k, lv))
        sw = lambda key: Switch.alloc().initWithOn_callback_(cfg[key], lambda on, k=key: m.set(k, on))
        self.bar_pointer, self.bar_head = mk("pointer_speed", POINTER_NAMES), mk("head_level", HEAD_NAMES)
        self.sw = {k: sw(k) for k in ("tiling", "dictation", "dwell_click", "eye_corners", "swap_hands", "desktop_gadget",
                                       "gadget_floats", "launch_at_login")}
        self.rows_a = [self._row("pointer speed", self.bar_pointer, W - PAD + 3),
                       self._row("head", self.bar_head, W - PAD + 3),
                       self._row("window tiling", self.sw["tiling"]),
                       self._row("dictation · left fist", self.sw["dictation"]),
                       self._row("dwell click", self.sw["dwell_click"]),
                       self._row("eye corners · beta", self.sw["eye_corners"])]
        self.cam_btn = TextButton.alloc().initWithTitle_size_color_callback_(
            m.camera_label(), T.SIZE_SMALL, "fg2", self._cycle)
        self.disp_text = make_text(str(m.display_count()), T.SIZE_TITLE, "fg2", w=40, h=T.ROW, right=True)
        self.rows_b = [self._row("camera", self.cam_btn, W - PAD + 6),
                       self._row("displays", self.disp_text),
                       self._row("swap hands", self.sw["swap_hands"]),
                       self._row("desktop gadget", self.sw["desktop_gadget"]),
                       self._row("gadget floats above windows", self.sw["gadget_floats"]),
                       self._row("launch at login", self.sw["launch_at_login"])]
        # the long title would collide with its switch; shrink to the text we have room for
        self.rule1, self.rule2 = Rule.alloc().initWithFrame_(NSMakeRect(0, 0, W - 2 * PAD, 1)), \
            Rule.alloc().initWithFrame_(NSMakeRect(0, 0, W - 2 * PAD, 1))
        self.addSubview_(self.rule1)
        self.addSubview_(self.rule2)
        self.quit_btn = TextButton.alloc().initWithTitle_size_color_callback_("quit", T.SIZE_TITLE, "fg", m.quit)
        self.version = make_text("v" + VERSION, T.SIZE_SMALL, "dim", h=16)
        self.addSubview_(self.quit_btn)
        self.addSubview_(self.version)
        # permission banner
        bw = W - 2 * PAD
        self.banner = Banner.alloc().initWithFrame_(NSMakeRect(PAD, 0, bw, 112))
        msg = make_text("gestyq needs accessibility access to move and click.", T.SIZE_TITLE, "fg",
                        w=bw - 24, h=52, wrap=True)
        msg.setFrameOrigin_((12, 12))
        self.banner.addSubview_(msg)
        self.grant_btn = TextButton.alloc().initWithTitle_size_color_callback_("grant access", T.SIZE_TITLE, "fg", self._grant)
        self.grant_btn.setFrameOrigin_((6, 76))
        self.did_btn = TextButton.alloc().initWithTitle_size_color_callback_(
            "i did it", T.SIZE_TITLE, "fg2", lambda: m.refresh_trust())
        self.did_btn.setFrameOrigin_((6 + self.grant_btn.frame().size.width + 8, 76))
        self.banner.addSubview_(self.grant_btn)
        self.banner.addSubview_(self.did_btn)
        self.addSubview_(self.banner)

    def _grant(self):
        self.grant_clicked = True
        self.model.grant_access()
        self.refresh()

    def _cycle(self):
        self.model.cycle_camera()
        self.refresh()

    # -- layout / state
    def refresh(self):
        m, cfg = self.model, self.model.cfg
        on = m.state.get()["enabled"]
        trusted = m.trusted
        self.master.set_on(on)
        self.bar_pointer.set_level(int(cfg["pointer_speed"]))
        self.bar_head.set_level(int(cfg["head_level"]))
        for k, s in self.sw.items():
            s.set_on(cfg[k])
        self.disp_text.set_text(str(m.display_count()))
        self.cam_btn.set_title(m.camera_label())
        self.cam_btn.fit(max_w=170)
        self.cam_btn.setFrameOrigin_((W - PAD + 6 - self.cam_btn.frame().size.width, 4))
        self.did_btn.setHidden_(not self.grant_clicked)

        y = PAD
        self.title.setFrameOrigin_((PAD, y))
        self.tagline.setFrameOrigin_((PAD, y + 20))
        self.master.setFrameOrigin_((W - PAD - Switch.W, y + 1))
        y += 36 + T.GAP
        self.banner.setHidden_(trusted)
        if trusted:
            for r in self.rows_a:
                r.setHidden_(False)
                r.setFrameOrigin_((0, y))
                r.set_inert(not on)
                y += T.ROW
        else:
            for r in self.rows_a:
                r.setHidden_(True)
            self.banner.setFrameOrigin_((PAD, y))
            y += 112
        y += 8
        self.rule1.setFrameOrigin_((PAD, y))
        y += 9
        for r in self.rows_b:
            r.setFrameOrigin_((0, y))
            y += T.ROW
        y += 8
        self.rule2.setFrameOrigin_((PAD, y))
        y += 9
        self.quit_btn.setFrameOrigin_((PAD - 6, y))
        self.version.setFrameOrigin_((W - PAD - self.version.frame().size.width, y + 4))
        y += 24 + PAD
        self.setFrameSize_((W, y))
