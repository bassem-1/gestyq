"""Menu bar item: custom-drawn 18x18 template glyph (globe) + NSPopover."""
import objc
from Foundation import NSTimer
from AppKit import (NSApplication, NSBezierPath, NSColor, NSImage, NSMakeRect, NSMinYEdge,
                    NSObject, NSPopover, NSPopoverBehaviorTransient, NSStatusBar, NSViewController)

from . import theme as T
from .popover import PopoverContent, blacken

# The app icon's globe reduced to its silhouette for 18 pt: an outline, one meridian tilted like the icon's
# view and the equator, all the same stroke so it reads at 11 pt. Template image (macOS tints it); off
# drops to the .32 step of the opacity ladder.
GLOBE_C, GLOBE_R, STROKE = (9.0, 9.0), 6.6, 1.5


def globe(alpha=1.0):
    from AppKit import NSAffineTransform, NSGraphicsContext
    from Quartz import CGContextBeginTransparencyLayer, CGContextEndTransparencyLayer, CGContextSetAlpha
    cg = NSGraphicsContext.currentContext().CGContext()
    CGContextSetAlpha(cg, alpha)                 # fade the glyph as one layer: no darker crossings when off
    CGContextBeginTransparencyLayer(cg, None)
    NSColor.blackColor().setStroke()
    cx, cy = GLOBE_C
    outline = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(cx - GLOBE_R, cy - GLOBE_R, 2 * GLOBE_R, 2 * GLOBE_R))
    outline.setLineWidth_(STROKE)
    outline.stroke()
    mer = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(-GLOBE_R * 0.42, -GLOBE_R, 2 * GLOBE_R * 0.42, 2 * GLOBE_R))
    t = NSAffineTransform.transform()
    t.translateXBy_yBy_(cx, cy)
    t.rotateByDegrees_(-18)                      # the icon's tilted axis
    mer.transformUsingAffineTransform_(t)
    mer.setLineWidth_(STROKE)
    mer.stroke()
    eq = NSBezierPath.bezierPath()
    eq.moveToPoint_((cx - GLOBE_R, cy))
    eq.lineToPoint_((cx + GLOBE_R, cy))
    eq.setLineWidth_(STROKE)
    eq.stroke()
    CGContextEndTransparencyLayer(cg)


def icon(enabled):
    """18x18 template image (macOS tints it); .32 alpha when off."""
    def draw(rect):
        globe(1.0 if enabled else T.A_DIM)
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
