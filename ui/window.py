"""The main window: live view (left) and inspector (right), settings strip below. Opening it switches the app to a
regular (dock) app; closing it goes back to the menu bar. The window never starts the camera: while gestyq is off
the live view is a calm placeholder."""
import time

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular,
                    NSBackingStoreBuffered, NSBezierPath, NSMakeRect, NSObject, NSWindow,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskFullSizeContentView,
                    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskTitled, NSWindowTitleHidden)
from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer

import preview
from . import theme as T
from .inspector import DETAIL_W, LIST_W, Inspector
from .live import W as LIVE_W, LiveView, put
from .widgets import Flipped, Switch, TextButton, text_width

WIN_W, WIN_H = 960, 640
TOP = 44
FOOT = 40                      # settings strip along the bottom
BODY_H = WIN_H - TOP - 1 - FOOT


class Root(Flipped):
    """Title strip, status line and the hairlines between the columns."""

    def initWithModel_(self, model):
        self = objc.super(Root, self).initWithFrame_(NSMakeRect(0, 0, WIN_W, WIN_H))
        self.model = model
        self.status = preview.mode_label(False)
        self.master = Switch.alloc().initWithOn_callback_(False, model.set_enabled)
        self.master.setFrameOrigin_((WIN_W - T.PAD - Switch.W, 13))
        self.addSubview_(self.master)
        self.live = LiveView.alloc().initWithModel_(model)
        self.live.setFrameOrigin_((0, TOP + 1))
        self.addSubview_(self.live)
        self.inspector = Inspector.alloc().initWithModel_frame_(
            model, NSMakeRect(LIVE_W + 1, TOP + 1, LIST_W + 1 + DETAIL_W, BODY_H))
        self.addSubview_(self.inspector)
        # settings strip: pointer mode, hot corners
        y = WIN_H - FOOT + 8
        self.mode_btns = {}
        x = T.PAD + 70
        for key in ("relative", "absolute"):
            b = TextButton.alloc().initWithTitle_size_color_callback_(
                key, T.SIZE_SMALL, "fg2", lambda k=key: model.set("pointer_mode", k))
            b.setFrameOrigin_((x, y))
            self.addSubview_(b)
            self.mode_btns[key] = b
            x += b.frame().size.width + 4
        self.corners = Switch.alloc().initWithOn_callback_(True, lambda on: model.set("hot_corners", bool(on)))
        self.corners.setFrameOrigin_((WIN_W / 2 + 96, WIN_H - FOOT + 11))
        self.addSubview_(self.corners)
        self.mode_now = None
        return self

    @objc.python_method
    def sync_settings(self, cfg):
        mode = "absolute" if cfg.get("pointer_mode") == "absolute" else "relative"
        if mode != self.mode_now:
            self.mode_now = mode
            for k, b in self.mode_btns.items():
                b.color = "fg" if k == mode else "fg2"
                b.setNeedsDisplay_(True)
            self.setNeedsDisplayInRect_(NSMakeRect(0, WIN_H - FOOT, WIN_W, FOOT))
        self.corners.set_on(bool(cfg.get("hot_corners", True)))

    @objc.python_method
    def set_status(self, text, on):
        if text != self.status:
            self.status = text
            self.setNeedsDisplayInRect_(NSMakeRect(WIN_W / 2, 0, WIN_W / 2, TOP))
        self.master.set_on(on)

    def drawRect_(self, rect):
        T.black().setFill()
        NSBezierPath.fillRect_(self.bounds())
        put("gestyq", 84, 14, T.SIZE_TITLE, T.fg(), medium=True)
        put(self.status, WIN_W - T.PAD - Switch.W - 12, 15, T.SIZE_SMALL, T.fg2(), right=True)
        T.line().setFill()
        NSBezierPath.fillRect_(NSMakeRect(0, TOP, WIN_W, 1))
        NSBezierPath.fillRect_(NSMakeRect(LIVE_W, TOP, 1, WIN_H - TOP - FOOT))
        NSBezierPath.fillRect_(NSMakeRect(LIVE_W + 1 + LIST_W, TOP, 1, WIN_H - TOP - FOOT))
        NSBezierPath.fillRect_(NSMakeRect(0, WIN_H - FOOT, WIN_W, 1))
        put("pointer", T.PAD, WIN_H - FOOT + 14, T.SIZE_SMALL, T.dim())
        rel = self.mode_now != "absolute"
        put("like a mouse, anywhere in the frame" if rel else
            "a camera box maps onto the screen", T.PAD + 70 + 150, WIN_H - FOOT + 14, T.SIZE_SMALL, T.dim())
        put("hot corners", WIN_W / 2 + 4, WIN_H - FOOT + 14, T.SIZE_SMALL, T.fg2())
        put("off: keep 4 px from corners", WIN_W - T.PAD, WIN_H - FOOT + 14, T.SIZE_SMALL, T.dim(), right=True)


class MainWindowController(NSObject):
    def initWithModel_(self, model):
        self = objc.super(MainWindowController, self).init()
        self.model = model
        self.window = None
        self.timer = None
        self.last_n, self.last_seq, self.last_on = -1, 0, None
        return self

    @objc.python_method
    def build(self):
        w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIN_W, WIN_H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskFullSizeContentView, NSBackingStoreBuffered, False)
        w.setTitle_("gestyq")
        w.setTitleVisibility_(NSWindowTitleHidden)
        w.setTitlebarAppearsTransparent_(True)
        w.setReleasedWhenClosed_(False)
        w.setAppearance_(T.dark_appearance())
        w.setBackgroundColor_(T.black())
        w.setDelegate_(self)
        self.root = Root.alloc().initWithModel_(self.model)
        w.setContentView_(self.root)
        w.setContentSize_((WIN_W, WIN_H))
        w.center()
        w.setFrameAutosaveName_("gestyq.main")
        self.window = w
        return w

    @property
    def is_open(self):
        return self.window is not None and self.window.isVisible()

    @objc.python_method
    def show(self):
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyRegular)
        w = self.window or self.build()
        self.model.set_window_open(True)         # publishes the live view while the camera runs; never starts it
        self.last_seq = 0
        self.root.inspector.refresh()
        w.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        if self.timer is None:
            self.timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
                1 / 30.0, self, "poll:", None, True)
            NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, NSRunLoopCommonModes)
        self.poll_(None)

    def windowWillClose_(self, note):
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        self.model.set_window_open(False)
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    def poll_(self, timer):
        m = self.model
        snap = m.state.get()
        on = snap["enabled"]
        self.root.set_status(f"{preview.mode_label(on)} · {m.display_label()}", on)
        self.root.sync_settings(m.cfg)
        self.root.live.set_camera_info(snap["camera_uid"], snap["camera_name"], snap["camera_note"])
        data = snap.get("live") if on else None
        n = data["n"] if data else -1
        if n != self.last_n or data is None or on != self.last_on:
            self.last_n, self.last_on = n, on
            self.root.live.set_data(data, snap["camera"], snap.get("recording"), on)
        if data:
            for seq, t, gid in data["gestures"]:
                if seq > self.last_seq:
                    self.last_seq = seq
                    if time.monotonic() - t < 1.0:
                        self.root.inspector.flash(gid)
        elif self.last_seq:
            self.last_seq = 0
        self.root.inspector.refresh()
