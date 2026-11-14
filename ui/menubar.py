"""Menu bar item: custom-drawn 18x18 template glyph (finger bars) + NSPopover."""
import objc
from AppKit import (NSImage, NSMakeRect, NSMinYEdge, NSObject, NSPopover, NSPopoverBehaviorTransient,
                    NSStatusBar, NSViewController, NSBezierPath, NSColor, NSApplication)

from . import theme as T
from .popover import PopoverContent

HEIGHTS = (8, 12, 10, 6)
BAR_W, BAR_GAP = 2, 2


def icon(enabled):
    """Template image: four vertical rounded bars (fingers), 35% alpha when off."""
    def draw(rect):
        total = BAR_W * len(HEIGHTS) + BAR_GAP * (len(HEIGHTS) - 1)
        x = (rect.size.width - total) / 2
        NSColor.blackColor().colorWithAlphaComponent_(1.0 if enabled else 0.35).setFill()
        for h in HEIGHTS:
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, (rect.size.height - h) / 2, BAR_W, h), BAR_W / 2, BAR_W / 2).fill()
            x += BAR_W + BAR_GAP
        return True

    img = NSImage.imageWithSize_flipped_drawingHandler_((18, 18), False, draw)
    img.setTemplate_(True)
    return img


class _Target(NSObject):
    def toggle_(self, sender):
        self.owner.toggle()


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

    @property
    def is_open(self):
        return self.popover.isShown()
