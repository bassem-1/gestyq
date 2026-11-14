"""Inspector: gestures grouped by hand (left column) and, for the selected one, what it does (right column).
Choosing an action rebinds the gesture; the change is saved through the model."""
import objc
from AppKit import NSBezierPath, NSMakeRect, NSScrollView, NSScrollerStyleOverlay

import bindings
from . import theme as T
from .live import put
from .widgets import Flipped, PulseDot, TextButton, animate, make_text, rrect

LIST_W, DETAIL_W = 270, 249
HEADER_H, GESTURE_H, CHOICE_H = 32, 40, 28


def layout(groups, header_h=HEADER_H, row_h=GESTURE_H):
    """-> ([(kind, key, y, h)], total_height). kind is 'header' (key = group) or 'gesture' (key = id)."""
    out, y = [], 8
    for g, ids in groups:
        out.append(("header", g, y, header_h))
        y += header_h
        for gid in ids:
            out.append(("gesture", gid, y, row_h))
            y += row_h
    return out, y + 8


def make_scroll(frame, doc):
    s = NSScrollView.alloc().initWithFrame_(frame)
    s.setDrawsBackground_(True)
    s.setBackgroundColor_(T.black())
    s.contentView().setDrawsBackground_(False)
    s.setHasVerticalScroller_(False)         # no grey system scrollers; wheel / trackpad scrolls
    s.setHasHorizontalScroller_(False)
    s.setScrollerStyle_(NSScrollerStyleOverlay)
    s.setBorderType_(0)
    s.setDocumentView_(doc)
    return s


class Header(Flipped):
    def initWithText_(self, text):
        self = objc.super(Header, self).initWithFrame_(NSMakeRect(0, 0, LIST_W, HEADER_H))
        self.text = text
        return self

    def drawRect_(self, rect):
        put(self.text, T.PAD, 12, T.SIZE_SMALL, T.dim())

    def hitTest_(self, p):
        return None


class GestureRow(Flipped):
    def initWithId_callback_(self, gid, cb):
        self = objc.super(GestureRow, self).initWithFrame_(NSMakeRect(0, 0, LIST_W, GESTURE_H))
        self.gid, self.cb, self.selected, self.hover = gid, cb, False, False
        self.action_text = ""
        self.wash_a = 0.0
        self.gen = 0
        self.dot = PulseDot.alloc().initWithSize_(6)
        self.dot.setFrameOrigin_((LIST_W - T.PAD - 6, GESTURE_H / 2 - 3))
        self.addSubview_(self.dot)
        return self

    @objc.python_method
    def set_action(self, text, selected):
        if (text, selected) != (self.action_text, self.selected):
            self.action_text, self.selected = text, selected
            self.setNeedsDisplay_(True)

    @objc.python_method
    def flash(self):
        """The gesture was just detected live: wash + dot."""
        self.dot.flash()
        self.gen += 1
        g = self.gen
        self.wash_a = T.A_LINE
        self.setNeedsDisplay_(True)

        def step(p):
            if g == self.gen:
                self.wash_a = T.A_LINE * (1 - p)
                self.setNeedsDisplay_(True)
        animate(0.6, step)

    def updateTrackingAreas(self):
        objc.super(GestureRow, self).updateTrackingAreas()
        from .widgets import _track
        _track(self)

    def mouseEntered_(self, e):
        self.hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, e):
        self.hover = False
        self.setNeedsDisplay_(True)

    def mouseDown_(self, e):
        self.cb(self.gid)

    def drawRect_(self, rect):
        a = max(self.wash_a, T.A_WASH if self.hover else 0.0, T.A_LINE if self.selected else 0.0)
        if a > 0:
            T.red(a).setFill()
            rrect(8, 2, LIST_W - 16, GESTURE_H - 4, T.CONTROL_RADIUS).fill()
        g = bindings.GESTURES[self.gid]
        put(g["label"], T.PAD, 5, T.SIZE_TITLE, T.fg(), medium=self.selected)
        put(self.action_text, T.PAD, 22, T.SIZE_SMALL, T.fg2())


class ChoiceRow(Flipped):
    def initWithAction_selected_callback_(self, aid, selected, cb):
        self = objc.super(ChoiceRow, self).initWithFrame_(NSMakeRect(0, 0, DETAIL_W, CHOICE_H))
        self.aid, self.selected, self.cb, self.hover = aid, selected, cb, False
        return self

    def updateTrackingAreas(self):
        objc.super(ChoiceRow, self).updateTrackingAreas()
        from .widgets import _track
        _track(self)

    def mouseEntered_(self, e):
        self.hover = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, e):
        self.hover = False
        self.setNeedsDisplay_(True)

    def mouseDown_(self, e):
        self.cb(self.aid)

    def drawRect_(self, rect):
        label = bindings.ACTIONS[self.aid]["label"]
        if self.selected:
            T.fg().setFill()
            rrect(8, 2, DETAIL_W - 16, CHOICE_H - 4, T.CONTROL_RADIUS).fill()
            put(label, T.PAD, 6, T.SIZE_TITLE, T.black(), medium=True)
        else:
            if self.hover:
                T.wash().setFill()
                rrect(8, 2, DETAIL_W - 16, CHOICE_H - 4, T.CONTROL_RADIUS).fill()
            put(label, T.PAD, 6, T.SIZE_TITLE, T.fg2())


class DetailDoc(Flipped):
    pass


class Inspector(Flipped):
    """Two scroll columns plus a footer. `model` needs cfg, set_binding(gid, aid), reset_bindings()."""

    def initWithModel_frame_(self, model, frame):
        self = objc.super(Inspector, self).initWithFrame_(frame)
        self.model = model
        self.selected = bindings.groups()[0][1][0]
        H = frame.size.height
        foot = 36
        self.rows = {}
        items, total = layout(bindings.groups())
        self.list_doc = Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, LIST_W, total))
        for kind, key, y, h in items:
            if kind == "header":
                v = Header.alloc().initWithText_(key)
            else:
                v = GestureRow.alloc().initWithId_callback_(key, self.select)
                self.rows[key] = v
            v.setFrameOrigin_((0, y))
            self.list_doc.addSubview_(v)
        self.list_scroll = make_scroll(NSMakeRect(0, 0, LIST_W, H - foot), self.list_doc)
        self.addSubview_(self.list_scroll)
        self.reset_btn = TextButton.alloc().initWithTitle_size_color_callback_(
            "reset to defaults", T.SIZE_SMALL, "fg2", self.reset)
        self.reset_btn.setFrameOrigin_((T.PAD - 6, H - foot + 6))
        self.addSubview_(self.reset_btn)
        self.detail_scroll = make_scroll(NSMakeRect(LIST_W + 1, 0, DETAIL_W, H), DetailDoc.alloc().initWithFrame_(
            NSMakeRect(0, 0, DETAIL_W, 10)))
        self.addSubview_(self.detail_scroll)
        self.refresh()
        return self

    def drawRect_(self, rect):
        T.line().setFill()
        NSBezierPath.fillRect_(NSMakeRect(0, self.frame().size.height - 36, LIST_W, 1))

    @objc.python_method
    def select(self, gid):
        self.selected = gid
        self.refresh()
        self.detail_scroll.documentView().scrollPoint_((0, 0))

    @objc.python_method
    def reset(self):
        self.model.reset_bindings()
        self.refresh()

    @objc.python_method
    def choose(self, aid):
        self.model.set_binding(self.selected, aid)
        self.refresh()

    @objc.python_method
    def flash(self, gid):
        r = self.rows.get(gid)
        if r is not None:
            r.flash()

    @objc.python_method
    def refresh(self):
        cfg = self.model.cfg
        for gid, r in self.rows.items():
            r.set_action(bindings.ACTIONS[bindings.action_for(cfg, gid)]["label"], gid == self.selected)
        key = (self.selected, bindings.action_for(cfg, self.selected))
        if key != getattr(self, "_detail_key", None):
            self._detail_key = key
            self.build_detail(*key)

    @objc.python_method
    def build_detail(self, gid, current):
        g = bindings.GESTURES[gid]
        W = DETAIL_W
        pad = T.PAD
        doc = DetailDoc.alloc().initWithFrame_(NSMakeRect(0, 0, W, 10))
        y = 16
        for text, size, col, med, h in ((g["label"], T.SIZE_TITLE, "fg", True, 18), (g["group"], T.SIZE_SMALL, "dim", False, 16)):
            t = make_text(text, size, col, medium=med, w=W - 2 * pad, h=h)
            t.setFrameOrigin_((pad, y))
            doc.addSubview_(t)
            y += h + 2
        how = make_text(g["how"], T.SIZE_SMALL, "fg2", w=W - 2 * pad, h=48, wrap=True)
        how.setFrameOrigin_((pad, y + 6))
        doc.addSubview_(how)
        y += 62
        hdr = make_text("does", T.SIZE_SMALL, "dim", w=W - 2 * pad, h=16)
        hdr.setFrameOrigin_((pad, y))
        doc.addSubview_(hdr)
        y += 22
        for aid in bindings.choices(self.selected):
            c = ChoiceRow.alloc().initWithAction_selected_callback_(aid, aid == current, self.choose)
            c.setFrameOrigin_((0, y))
            doc.addSubview_(c)
            y += CHOICE_H
        y += 16
        doc.setFrameSize_((W, max(y, self.detail_scroll.frame().size.height)))
        self.detail_scroll.setDocumentView_(doc)
