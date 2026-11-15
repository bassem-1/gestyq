"""Air-writing canvas: a small black panel next to the focused text field. The index fingertip draws red ink on it.

The panel never takes focus (non-activating, cannot become key or main) and ignores the mouse, so real and
synthetic clicks pass straight through it to the field below. Show and hide are instant."""
import time

import objc
from AppKit import (NSBackingStoreBuffered, NSBezierPath, NSBitmapImageRep, NSColor, NSGraphicsContext,
                    NSLineCapStyleRound, NSLineJoinStyleRound, NSMakeRect, NSPanel, NSStatusWindowLevel,
                    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
                    NSWindowCollectionBehaviorIgnoresCycle, NSWindowCollectionBehaviorStationary,
                    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel, NSString)

import ink as inkmod
from . import theme as T
from .live import put
from .widgets import Flipped, attrs, rrect

W, H = 320, 200
AREA = (12, 28, 296, 144)            # ink area x, y, w, h
FLASH_OK, FLASH_REJECT, FLASH_SMALL, RESULT_LIFE = 0.45, 0.3, 1.0, 1.0
HINT = "point = pen · flick → space · ← delete"


def circle(x, y, r):
    return NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x - r, y - r, 2 * r, 2 * r))


class CanvasView(Flipped):
    def initWithScale_(self, scale):
        self = objc.super(CanvasView, self).initWithFrame_(NSMakeRect(0, 0, W, H))
        self.snap, self.scale0, self.now = None, scale, time.monotonic()
        return self

    @objc.python_method
    def set_snap(self, snap, now=None):
        self.snap, self.now = snap, now if now is not None else time.monotonic()
        self.setNeedsDisplay_(True)

    def hitTest_(self, p):
        return None

    # -- drawing
    @objc.python_method
    def _stroke(self, strokes, tf, color, width=3.0):
        scale, ox, oy = tf
        color.setStroke()
        for s in strokes:
            if not s:
                continue
            path = NSBezierPath.bezierPath()
            path.setLineWidth_(width)
            path.setLineCapStyle_(NSLineCapStyleRound)
            path.setLineJoinStyle_(NSLineJoinStyleRound)
            p0 = (AREA[0] + ox + s[0][0] * scale, AREA[1] + oy + s[0][1] * scale)
            path.moveToPoint_(p0)
            if len(s) == 1:
                path.lineToPoint_((p0[0] + 0.01, p0[1]))
            for x, y in s[1:]:
                path.lineToPoint_((AREA[0] + ox + x * scale, AREA[1] + oy + y * scale))
            path.stroke()

    @objc.python_method
    def _tf(self, strokes):
        if not strokes:
            return self.scale0, inkmod.PIN[0] * AREA[2], inkmod.PIN[1] * AREA[3]
        return inkmod.fit(inkmod.bbox(strokes), strokes[0][0], AREA[2], AREA[3], self.scale0)

    def drawRect_(self, rect):
        s, now = self.snap, self.now
        T.black().setFill()
        rrect(0, 0, W, H, T.RADIUS).fill()
        T.line().setStroke()
        b = rrect(0.5, 0.5, W - 1, H - 1, T.RADIUS - 0.5)
        b.setLineWidth_(1)
        b.stroke()
        s = s or {"strokes": (), "tip": None, "pen": False, "hand": False, "armed": False, "result": None, "typed": ""}
        w = put("write", 12, 10, T.SIZE_SMALL, T.fg2())
        if s["hand"]:
            c = circle(12 + w + 12, 17, 3)
            if s["pen"]:
                T.fg().setFill()
                c.fill()
            else:
                T.dim().setStroke()
                c = circle(12 + w + 12, 17, 2.5)
                c.setLineWidth_(1)
                c.stroke()
        typed = s["typed"][-16:].replace(" ", "·")
        put(typed, W - 12, 10, T.SIZE_SMALL, T.fg2(), right=True)
        # result flash
        r = s["result"]
        age = now - r["t"] if r else 99.0
        strokes = s["strokes"]
        shown = False
        if r and r["why"] == "" and age < FLASH_OK:
            self._stroke(r["strokes"], self._tf(r["strokes"]), T.line())
            self._centre(r["char"], 22, T.fg(), r["alt"], T.fg2() if r["alt"] else None)
            shown = True
        elif r and r["why"] == "reject" and age < FLASH_REJECT:
            self._stroke(r["strokes"], self._tf(r["strokes"]), T.dim())
            self._centre("?", 22, T.dim())
            shown = True
        elif r and r["why"] == "small" and age < FLASH_SMALL:
            self._centre("write bigger", T.SIZE_SMALL, T.fg2())
            shown = True
        tf = self._tf(strokes)
        if strokes:
            self._stroke(strokes, tf, T.fg())
        # the tip
        tip = s["tip"]
        if tip and s["hand"] and s["armed"] or (tip and s["hand"] and strokes):
            scale, ox, oy = tf
            if strokes:
                px, py = AREA[0] + ox + tip[0] * scale, AREA[1] + oy + tip[1] * scale
                inside = AREA[0] <= px <= AREA[0] + AREA[2] and AREA[1] <= py <= AREA[1] + AREA[3]
            else:                                   # no ink yet: the pen starts at the pin
                px, py = AREA[0] + ox, AREA[1] + oy
                inside = not shown
            if inside:
                if s["pen"]:
                    T.fg().setFill()
                    circle(px, py, 4).fill()
                else:
                    ring = circle(px, py, 4)
                    ring.setLineWidth_(1)
                    T.fg2().setStroke()
                    ring.stroke()
        put(HINT if s["armed"] else "ready in a moment", 12, 176, T.SIZE_SMALL, T.dim())

    @objc.python_method
    def _centre(self, text, size, color, alt=None, alt_color=None):
        cx, cy = AREA[0] + AREA[2] / 2, AREA[1] + AREA[3] / 2
        a = attrs(size, color, medium=size > 12)
        ns = NSString.stringWithString_(text)
        sz = ns.sizeWithAttributes_(a)
        ns.drawAtPoint_withAttributes_((cx - sz.width / 2, cy - sz.height / 2), a)
        if alt:
            put(alt, cx + sz.width / 2 + 8, cy - 7, T.SIZE_SMALL, alt_color)

    # -- test / preview
    @objc.python_method
    def render(self):
        """Draw the current state into a bitmap (2x), for tests and the look check."""
        rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, W * 2, H * 2, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0)
        rep.setSize_((W, H))
        self.cacheDisplayInRect_toBitmapImageRep_(self.bounds(), rep)
        return rep


class CanvasPanel(NSPanel):
    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


class CanvasController:
    def __init__(self, model):
        self.model = model
        self.panel = None
        self.shown = False
        self.last_n = None
        self.origin = None

    @objc.python_method
    def _make(self):
        p = CanvasPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(False)
        p.setHidesOnDeactivate_(False)
        p.setIgnoresMouseEvents_(True)              # clicks go through to the text field
        p.setLevel_(NSStatusWindowLevel)
        p.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | NSWindowCollectionBehaviorStationary | NSWindowCollectionBehaviorIgnoresCycle)
        p.setAppearance_(T.dark_appearance())
        p.setTitle_("gestyq writing")
        self.view = CanvasView.alloc().initWithScale_(float(self.model.cfg["write"]["ink_scale"]))
        p.setContentView_(self.view)
        self.panel = p
        return p

    @objc.python_method
    def show(self, top_left, primary_h):
        """top_left: global top-left coords of the canvas; primary_h converts to Cocoa."""
        p = self.panel or self._make()
        origin = (top_left[0], primary_h - (top_left[1] + H))
        if self.origin is None or abs(origin[0] - self.origin[0]) > 4 or abs(origin[1] - self.origin[1]) > 4:
            self.origin = origin
            p.setFrameOrigin_(origin)
        if not self.shown:
            self.shown = True
            self.last_n = None
            self.view.set_snap(None)
            p.orderFrontRegardless()                # never makeKey: the text field keeps focus

    @objc.python_method
    def hide(self):
        if self.panel is not None and self.shown:
            self.shown = False
            self.origin = None
            self.panel.orderOut_(None)

    @objc.python_method
    def update(self, snap, now):
        """Every tick: redraw when the snapshot changed, or while a result flash may still expire."""
        if not self.shown:
            return
        r = snap and snap.get("result")
        flashing = bool(r) and now - r["t"] < RESULT_LIFE + 0.1
        n = snap["n"] if snap else None
        if n != self.last_n or flashing:
            self.last_n = n
            self.view.set_snap(snap, now)
