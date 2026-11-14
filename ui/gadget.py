"""Desktop gadget: 140x140 borderless non-activating panel. Click toggles on/off, drag moves it."""
import math

import objc
from AppKit import (NSApplication, NSBezierPath, NSEvent, NSMakeRect, NSMenu, NSMenuItem, NSObject, NSPanel,
                    NSScreen, NSString, NSWindowCollectionBehaviorCanJoinAllSpaces,
                    NSWindowCollectionBehaviorFullScreenNone, NSWindowCollectionBehaviorIgnoresCycle,
                    NSWindowCollectionBehaviorStationary, NSWindowStyleMaskBorderless,
                    NSWindowStyleMaskNonactivatingPanel, NSBackingStoreBuffered, NSFloatingWindowLevel, NSColor)
from Quartz import CGWindowLevelForKey, kCGDesktopIconWindowLevelKey

from . import theme as T
from .widgets import Flipped, PulseDot, attrs, rrect, text_width

SIZE = T.GADGET
LEFT_DOWN, LEFT_UP, RIGHT_DOWN, LEFT_DRAG = 1, 2, 3, 6     # NSEventType raw values


class GadgetView(Flipped):
    def initWithFrame_(self, frame):
        self = objc.super(GadgetView, self).initWithFrame_(frame)
        self.on, self.caption = False, "paused"
        self.dot = PulseDot.alloc().initWithSize_(6)
        self.dot.setFrameOrigin_((SIZE / 2 - 3, SIZE / 2 + 14))
        self.addSubview_(self.dot)
        return self

    def set_state(self, on, caption):
        if (on, caption) != (self.on, self.caption):
            self.on, self.caption = on, caption
            self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        T.black().setFill()
        rrect(0, 0, SIZE, SIZE, T.GADGET_RADIUS).fill()
        T.line().setStroke()
        p = rrect(0.5, 0.5, SIZE - 1, SIZE - 1, T.GADGET_RADIUS - 0.5)
        p.setLineWidth_(1)
        p.stroke()
        small = attrs(T.SIZE_SMALL, T.fg2())
        NSString.stringWithString_("gestyq").drawAtPoint_withAttributes_((14, 14), small)
        word = "on" if self.on else "off"
        wa = attrs(T.SIZE_STATE, T.fg() if self.on else T.dim(), medium=True)
        s = NSString.stringWithString_(word)
        sz = s.sizeWithAttributes_(wa)
        s.drawAtPoint_withAttributes_(((SIZE - sz.width) / 2, SIZE / 2 - sz.height / 2 - 6), wa)
        NSString.stringWithString_(self.caption).drawInRect_withAttributes_(
            NSMakeRect(14, SIZE - 14 - 28, SIZE - 28, 28), small)


class GadgetPanel(NSPanel):
    """Click vs drag (< 3pt = click) is decided here, like haptyq, not by isMovableByWindowBackground."""

    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False

    def sendEvent_(self, event):
        t = event.type()
        if t == LEFT_DOWN:
            self.down = NSEvent.mouseLocation()
            self.origin0 = self.frame().origin
            self.moved = False
        elif t == LEFT_DRAG:
            if getattr(self, "down", None) is None:
                return
            m = NSEvent.mouseLocation()
            dx, dy = m.x - self.down.x, m.y - self.down.y
            if self.moved or math.hypot(dx, dy) >= 3:
                self.moved = True
                self.setFrameOrigin_((self.origin0.x + dx, self.origin0.y + dy))
        elif t == LEFT_UP:
            if getattr(self, "down", None) is None:
                return
            self.down = None
            if self.moved:
                self.on_moved(self.frame().origin)
            elif event.clickCount() == 1:
                self.on_click()
        elif t == RIGHT_DOWN:
            menu = self.menu_builder()
            NSMenu.popUpContextMenu_withEvent_forView_(menu, event, self.contentView())
        else:
            objc.super(GadgetPanel, self).sendEvent_(event)


class _Handler(NSObject):
    def fire_(self, sender):
        self.handlers[sender.tag()]()


class GadgetController:
    def __init__(self, model):
        self.model = model
        self.panel = None
        self.handler = _Handler.alloc().init()
        self.handler.handlers = {}

    def _make(self):
        cfg = self.model.cfg
        p = GadgetPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, SIZE, SIZE), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(False)
        p.setHidesOnDeactivate_(False)
        p.setMovableByWindowBackground_(False)
        p.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
                                 | NSWindowCollectionBehaviorIgnoresCycle | NSWindowCollectionBehaviorFullScreenNone)
        p.setAppearance_(T.dark_appearance())
        p.setTitle_("gestyq")
        self.view = GadgetView.alloc().initWithFrame_(NSMakeRect(0, 0, SIZE, SIZE))
        p.setContentView_(self.view)
        p.down, p.moved = None, False
        p.on_click = lambda: self.model.set_enabled(not self.model.state.get()["enabled"])
        p.on_moved = self._moved
        p.menu_builder = self._menu
        o = cfg.get("gadget_origin") or self._default_origin()
        p.setFrameOrigin_(self.clamp(o))
        self.panel = p
        return p

    def apply(self):
        """Show/hide and set the window level from config."""
        cfg = self.model.cfg
        if not cfg["desktop_gadget"]:
            if self.panel:
                self.panel.orderOut_(None)
            return
        p = self.panel or self._make()
        p.setLevel_(NSFloatingWindowLevel if cfg["gadget_floats"]
                    else int(CGWindowLevelForKey(kCGDesktopIconWindowLevelKey)) + 1)
        p.orderFrontRegardless()

    def update(self, on, caption, pulsed):
        if self.panel is None:
            return
        self.view.set_state(on, caption)
        if pulsed:
            self.view.dot.flash()

    # -- geometry
    def _default_origin(self):
        vf = (NSScreen.mainScreen() or NSScreen.screens()[0]).visibleFrame()
        return (vf.origin.x + vf.size.width - SIZE - 24, vf.origin.y + vf.size.height - SIZE - 24)

    def clamp(self, o):
        best, area = None, -1
        for s in NSScreen.screens():
            f = s.visibleFrame()
            w = max(0, min(o[0] + SIZE, f.origin.x + f.size.width) - max(o[0], f.origin.x))
            h = max(0, min(o[1] + SIZE, f.origin.y + f.size.height) - max(o[1], f.origin.y))
            if w * h > area:
                best, area = f, w * h
        if best is None:
            return o
        return (min(max(o[0], best.origin.x), best.origin.x + best.size.width - SIZE),
                min(max(o[1], best.origin.y), best.origin.y + best.size.height - SIZE))

    def reclamp(self):
        if self.panel:
            f = self.panel.frame().origin
            self.panel.setFrameOrigin_(self.clamp((f.x, f.y)))

    def _moved(self, origin):
        c = self.clamp((origin.x, origin.y))
        self.panel.setFrameOrigin_(c)
        self.model.set("gadget_origin", [c[0], c[1]])

    def _menu(self):
        m = NSMenu.alloc().init()
        m.setAppearance_(T.dark_appearance())
        cfg = self.model.cfg
        entries = [("hide gadget", False, lambda: self.model.set("desktop_gadget", False)),
                   ("float above windows", cfg["gadget_floats"],
                    lambda: self.model.set("gadget_floats", not cfg["gadget_floats"])),
                   ("quit", False, self.model.quit)]
        self.handler.handlers = {}
        for i, (title, checked, fn) in enumerate(entries):
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "fire:", "")
            it.setTarget_(self.handler)
            it.setTag_(i)
            it.setState_(1 if checked else 0)
            self.handler.handlers[i] = fn
            m.addItem_(it)
        return m
