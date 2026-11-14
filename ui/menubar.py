"""Menu bar item: custom-drawn 18x18 template glyph (open hand) + NSPopover."""
import objc
from Foundation import NSTimer
from AppKit import (NSAffineTransform, NSApplication, NSBezierPath, NSColor, NSImage, NSMakeRect, NSMinYEdge,
                    NSObject, NSPopover, NSPopoverBehaviorTransient, NSStatusBar, NSViewController)

from . import theme as T
from .popover import PopoverContent, blacken

# An open hand: palm, four fingers, thumb. One path so the off-state alpha doesn't double up where
# shapes overlap. Deliberately unlike haptyq's floating bars.
FINGERS = ((4.6, 14.2), (6.9, 16.4), (9.2, 16.0), (11.5, 13.8))     # (left x, top y)
FINGER_W = 1.9


def hand_path():
    path = NSBezierPath.bezierPath()
    path.appendBezierPath_(NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(4.6, 1.5, 8.8, 8.0), 3.2, 3.2))                                  # palm
    for x, top in FINGERS:
        path.appendBezierPath_(NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(x, 7.0, FINGER_W, top - 7.0), FINGER_W / 2, FINGER_W / 2))
    thumb = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(-1.0, 0.0, 2.0, 6.4), 1.0, 1.0)
    t = NSAffineTransform.transform()
    t.translateXBy_yBy_(5.8, 3.4)
    t.rotateByDegrees_(42)
    thumb.transformUsingAffineTransform_(t)
    path.appendBezierPath_(thumb)
    return path


def icon(enabled):
    """18x18 template image (macOS tints it); 35% alpha when off."""
    def draw(rect):
        NSColor.blackColor().colorWithAlphaComponent_(1.0 if enabled else 0.35).setFill()
        hand_path().fill()
        return True

    img = NSImage.imageWithSize_flipped_drawingHandler_((18, 18), False, draw)
    img.setTemplate_(True)
    return img


def dock_icon():
    """Red open hand on black, 128x128, for the dock while the window is open."""
    def draw(rect):
        T.black().setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(8, 8, 112, 112), 26, 26).fill()
        t = NSAffineTransform.transform()
        t.translateXBy_yBy_(64 - 9 * 4.2, 64 - 9 * 4.2)
        t.scaleBy_(4.2)
        path = hand_path()
        path.transformUsingAffineTransform_(t)
        T.red().setFill()
        path.fill()
        return True

    return NSImage.imageWithSize_flipped_drawingHandler_((128, 128), False, draw)


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
