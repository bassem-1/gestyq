"""Custom-drawn views: capsule switch, signal bar, text button, pulse dot, text, hover row.
All views are flipped (origin top-left). Colours come from theme only."""
import time

import objc
from AppKit import (NSBezierPath, NSForegroundColorAttributeName, NSFontAttributeName, NSMakeRect,
                    NSParagraphStyleAttributeName, NSMutableParagraphStyle, NSString, NSTrackingActiveAlways,
                    NSTrackingArea, NSTrackingInVisibleRect, NSTrackingMouseEnteredAndExited, NSView)
from Foundation import NSRunLoop, NSRunLoopCommonModes, NSTimer

from . import theme as T


def animate(duration, step, done=None):
    """Runs step(progress 0..1) at ~60 Hz for `duration` seconds on the main run loop."""
    t0 = time.monotonic()

    def tick(timer):
        p = min((time.monotonic() - t0) / duration, 1.0)
        step(p)
        if p >= 1.0:
            timer.invalidate()
            if done:
                done()

    timer = NSTimer.timerWithTimeInterval_repeats_block_(1 / 60.0, True, tick)
    NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
    return timer


def attrs(size, color, medium=False, align=None):
    d = {NSFontAttributeName: T.font(size, medium), NSForegroundColorAttributeName: color}
    if align is not None:
        ps = NSMutableParagraphStyle.alloc().init()
        ps.setAlignment_(align)
        d[NSParagraphStyleAttributeName] = ps
    return d


def text_width(s, size, medium=False):
    return NSString.stringWithString_(s).sizeWithAttributes_(attrs(size, T.fg(), medium)).width


def rrect(x, y, w, h, r):
    return NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x, y, w, h), r, r)


class Flipped(NSView):
    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True


def _track(view):
    for a in list(view.trackingAreas()):
        view.removeTrackingArea_(a)
    opts = NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
    view.addTrackingArea_(NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(view.bounds(), opts, view, None))


class Text(Flipped):
    """Static text. Colour is one of the theme tokens: 'fg' | 'fg2' | 'dim'."""

    def initWithText_size_color_(self, text, size, color):
        self = objc.super(Text, self).initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.text, self.size, self.color, self.medium, self.wrap, self.right = text, size, color, False, False, False
        return self

    def set_text(self, s):
        if s != self.text:
            self.text = s
            self.setNeedsDisplay_(True)

    def set_color(self, c):
        self.color = c
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        col = getattr(T, self.color)()
        a = attrs(self.size, col, self.medium)
        s = NSString.stringWithString_(self.text)
        if self.wrap:
            s.drawInRect_withAttributes_(self.bounds(), a)
        else:
            w = s.sizeWithAttributes_(a).width
            h = s.sizeWithAttributes_(a).height
            x = self.bounds().size.width - w if self.right else 0
            s.drawAtPoint_withAttributes_((x, (self.bounds().size.height - h) / 2), a)

    def hitTest_(self, p):
        return None


def make_text(text, size=T.SIZE_TITLE, color="fg", medium=False, w=None, h=None, wrap=False, right=False):
    v = Text.alloc().initWithText_size_color_(text, size, color)
    v.medium, v.wrap, v.right = medium, wrap, right
    tw = text_width(text, size, medium)
    v.setFrameSize_((w if w is not None else tw + 2, h if h is not None else size + 6))
    return v


class Switch(Flipped):
    """Capsule 34x18. off: 16% border, 32% knob left. on: filled, black knob right. 120 ms ease-out."""
    W, H = 34, 18

    def initWithOn_callback_(self, on, cb):
        self = objc.super(Switch, self).initWithFrame_(NSMakeRect(0, 0, self.W, self.H))
        self.on, self.pos, self.cb = bool(on), 1.0 if on else 0.0, cb
        try:
            self.setAccessibilityRole_("AXCheckBox")
        except Exception:
            pass
        return self

    def set_on(self, on, animated=False):
        on = bool(on)
        if on == self.on and not animated:
            return
        self.on = on
        a, b = self.pos, 1.0 if on else 0.0
        if not animated:
            self.pos = b
            self.setNeedsDisplay_(True)
            return

        def step(p):
            self.pos = a + (b - a) * (1 - (1 - p) ** 2)
            self.setNeedsDisplay_(True)
        animate(0.12, step)

    def mouseDown_(self, event):
        self.set_on(not self.on, True)
        if self.cb:
            self.cb(self.on)

    def drawRect_(self, rect):
        t = self.pos
        T.red(t).setFill()
        rrect(0, 0, self.W, self.H, 9).fill()
        T.red(T.A_LINE + (1 - T.A_LINE) * t).setStroke()
        p = rrect(0.5, 0.5, self.W - 1, self.H - 1, 8.5)
        p.setLineWidth_(1)
        p.stroke()
        x = 3 + t * (self.W - 6 - 12)
        T.red(T.A_DIM * (1 - t)).setFill()
        NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, 3, 12, 12)).fill()
        T.black().colorWithAlphaComponent_(t).setFill()
        NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, 3, 12, 12)).fill()


class SignalBar(Flipped):
    """Five cells: cell 0 = off (dash), cells 1..4 = levels. 10x14, 3pt gap, radius 2, name to the right."""
    CELL = 13
    W = 5 * 13 - 3 + 8 + 48

    def initWithLevel_names_callback_(self, level, names, cb):
        self = objc.super(SignalBar, self).initWithFrame_(NSMakeRect(0, 0, self.W, T.ROW))
        self.level, self.names, self.cb = level, names, cb
        return self

    def set_level(self, level):
        if level != self.level:
            self.level = level
            self.setNeedsDisplay_(True)

    def mouseDown_(self, event):
        x = self.convertPoint_fromView_(event.locationInWindow(), None).x
        i = int(x // self.CELL)
        if 0 <= i <= 4 and x < 5 * self.CELL:
            self.level = i
            self.setNeedsDisplay_(True)
            if self.cb:
                self.cb(i)

    def drawRect_(self, rect):
        cy = T.ROW / 2
        for i in range(5):
            x = i * self.CELL
            if i == 0:
                (T.fg() if self.level == 0 else T.line()).setFill()
                rrect(x, cy - 1, 10, 2, 1).fill()
            elif i <= self.level:
                T.fg().setFill()
                rrect(x, cy - 7, 10, 14, 2).fill()
            else:
                T.line().setStroke()
                rrect(x + 0.5, cy - 6.5, 9, 13, 2).stroke()
        a = attrs(T.SIZE_SMALL, T.fg2())
        s = NSString.stringWithString_(self.names[self.level])
        s.drawAtPoint_withAttributes_((5 * self.CELL - 3 + 8, cy - s.sizeWithAttributes_(a).height / 2), a)


class TextButton(Flipped):
    """Text button with a 8% hover/pressed wash (never changes layout). Height 24, padding 6."""

    def initWithTitle_size_color_callback_(self, title, size, color, cb):
        self = objc.super(TextButton, self).initWithFrame_(NSMakeRect(0, 0, 10, 24))
        self.title, self.size, self.color, self.cb = title, size, color, cb
        self.hover = self.pressed = False
        self.fit()
        return self

    def fit(self, max_w=None):
        w = text_width(self.title, self.size) + 12
        self.setFrameSize_((min(w, max_w) if max_w else w, 24))

    def set_title(self, t):
        self.title = t
        self.setNeedsDisplay_(True)

    def updateTrackingAreas(self):
        objc.super(TextButton, self).updateTrackingAreas()
        _track(self)

    def mouseEntered_(self, e):
        self.hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, e):
        self.hover = False
        self.setNeedsDisplay_(True)

    def mouseDown_(self, e):
        self.pressed = True
        self.setNeedsDisplay_(True)

    def mouseUp_(self, e):
        self.pressed = False
        self.setNeedsDisplay_(True)
        p = self.convertPoint_fromView_(e.locationInWindow(), None)
        if 0 <= p.x <= self.frame().size.width and 0 <= p.y <= 24 and self.cb:
            self.cb()

    def drawRect_(self, rect):
        if self.hover or self.pressed:
            T.wash().setFill()
            rrect(0, 0, self.frame().size.width, 24, T.CONTROL_RADIUS).fill()
        a = attrs(self.size, getattr(T, self.color)())
        t = str(self.title)
        w = self.frame().size.width - 12
        while len(t) > 1 and text_width(t, self.size) > w:
            t = t[:-2] + "\u2026"
        s = NSString.stringWithString_(t)
        s.drawAtPoint_withAttributes_((6, (24 - s.sizeWithAttributes_(a).height) / 2), a)


class PulseDot(Flipped):
    """6pt dot that flashes 1 -> 0.16 opacity over 180 ms."""

    def initWithSize_(self, size):
        self = objc.super(PulseDot, self).initWithFrame_(NSMakeRect(0, 0, size, size))
        self.alpha = T.A_LINE
        self.gen = 0
        return self

    def flash(self):
        self.gen += 1
        g = self.gen
        self.alpha = 1.0
        self.setNeedsDisplay_(True)

        def step(p):
            if g == self.gen:
                self.alpha = 1.0 - (1.0 - T.A_LINE) * p
                self.setNeedsDisplay_(True)
        animate(0.18, step)

    def drawRect_(self, rect):
        T.red(self.alpha).setFill()
        NSBezierPath.bezierPathWithOvalInRect_(self.bounds()).fill()

    def hitTest_(self, p):
        return None


class Row(Flipped):
    """32pt row with a hover wash that extends 8pt past the content. Dims to 55% and goes inert."""

    def initWithWidth_(self, w):
        self = objc.super(Row, self).initWithFrame_(NSMakeRect(0, 0, w, T.ROW))
        self.hover = False
        self.inert = False
        return self

    def set_inert(self, inert):
        self.inert = inert
        self.setAlphaValue_(T.A_FG2 if inert else 1.0)   # 55%: reads as off but stays legible

    def hitTest_(self, p):
        return None if self.inert else objc.super(Row, self).hitTest_(p)

    def updateTrackingAreas(self):
        objc.super(Row, self).updateTrackingAreas()
        _track(self)

    def mouseEntered_(self, e):
        self.hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, e):
        self.hover = False
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        if self.hover and not self.inert:
            T.wash().setFill()
            rrect(8, 0, self.frame().size.width - 16, T.ROW, T.CONTROL_RADIUS).fill()


class Rule(Flipped):
    """1px hairline at 16%."""

    def drawRect_(self, rect):
        T.line().setFill()
        NSBezierPath.fillRect_(NSMakeRect(0, 0, self.frame().size.width, 1))

    def hitTest_(self, p):
        return None
