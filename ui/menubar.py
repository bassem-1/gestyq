"""Menu bar item: custom-drawn 18x18 template glyph (comet) + NSPopover."""
import math
import objc
from Foundation import NSTimer
from AppKit import (NSApplication, NSBezierPath, NSColor, NSImage, NSMakeRect, NSMinYEdge,
                    NSObject, NSPopover, NSPopoverBehaviorTransient, NSStatusBar, NSViewController)

from . import theme as T
from .popover import PopoverContent, blacken

# A comet: an arc that thickens and brightens toward a solid head, the app icon's mark at 18 pt.
# Three tones (the brand opacities .32 / .55 / 1) so it stays crisp at menu bar size. Template image,
# so macOS tints it; the off state fades the whole glyph as one layer (no darker overlaps).
ARC_C, ARC_R = (9.0, 7.2), 6.2
HEAD_ANGLE, HEAD_R = 25.0, 2.9
TONES = ((215.0, 160.0, 1.7, 0.32), (160.0, 95.0, 2.3, 0.55), (95.0, HEAD_ANGLE, 3.0, 1.0))   # from, to, width, alpha


def comet(alpha=1.0):
    from Quartz import CGContextBeginTransparencyLayer, CGContextEndTransparencyLayer, CGContextSetAlpha
    from AppKit import NSGraphicsContext
    cg = NSGraphicsContext.currentContext().CGContext()
    CGContextSetAlpha(cg, alpha)
    CGContextBeginTransparencyLayer(cg, None)
    for a0, a1, w, tone in TONES:
        p = NSBezierPath.bezierPath()
        p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(ARC_C, ARC_R, a0, a1, True)
        p.setLineWidth_(w)
        NSColor.blackColor().colorWithAlphaComponent_(tone).setStroke()
        p.stroke()
    a = math.radians(HEAD_ANGLE)
    x, y = ARC_C[0] + ARC_R * math.cos(a), ARC_C[1] + ARC_R * math.sin(a)
    NSColor.blackColor().setFill()
    NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x - HEAD_R, y - HEAD_R, 2 * HEAD_R, 2 * HEAD_R)).fill()
    CGContextEndTransparencyLayer(cg)


def icon(enabled):
    """18x18 template image (macOS tints it); 35% alpha when off."""
    def draw(rect):
        comet(1.0 if enabled else 0.35)
        return True

    img = NSImage.imageWithSize_flipped_drawingHandler_((18, 18), False, draw)
    img.setTemplate_(True)
    return img


class _Target(NSObject):
    def toggle_(self, sender):
        self.owner.toggle()


class _PopoverDelegate(NSObject):
    def popoverDidShow_(self, note):
        # the material layers are created lazily after the first display: repaint a few times
        blacken(self.content)
        for d in (0.02, 0.1, 0.4):
            NSTimer.scheduledTimerWithTimeInterval_repeats_block_(d, False, lambda t: blacken(self.content))


class MenuBar:
    def __init__(self, model):
        self.model = model
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
        self.btn = self.item.button()
        self.target = _Target.alloc().init()
        self.target.owner = self
        self.btn.setTarget_(self.target)
        self.btn.setAction_("toggle:")
        self.shown = None
        self.set_enabled(False)
        self.content = PopoverContent.alloc().initWithModel_(model)
        vc = NSViewController.alloc().init()
        vc.setView_(self.content)
        self.popover = NSPopover.alloc().init()
        self.popover.setContentViewController_(vc)
        self.popover.setBehavior_(NSPopoverBehaviorTransient)
        self.popover.setAppearance_(T.dark_appearance())
        self.popover.setAnimates_(False)
        self.pdel = _PopoverDelegate.alloc().init()
        self.pdel.content = self.content
        self.popover.setDelegate_(self.pdel)

    def set_enabled(self, on):
        if on != self.shown:
            self.shown = on
            self.btn.setImage_(icon(on))

    def toggle(self):
        if self.popover.isShown():
            self.popover.performClose_(None)
            return
        self.model.refresh_trust()
        self.refresh()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.popover.showRelativeToRect_ofView_preferredEdge_(self.btn.bounds(), self.btn, NSMinYEdge)

    def refresh(self):
        self.content.refresh()
        self.popover.setContentSize_(self.content.frame().size)
        if self.popover.isShown():
            blacken(self.content)

    @property
    def is_open(self):
        return self.popover.isShown()
