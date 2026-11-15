"""Live view: the mirrored camera (dimmed, greyscale) with each hand's landmarks drawn on top, a compact
readout per hand, head yaw/pitch against its threshold and a rolling log of recognised gestures."""
import time

import objc
from AppKit import (NSBezierPath, NSCompositingOperationSourceOver, NSData, NSGraphicsContext, NSImage,
                    NSMakeRect, NSString)

import preview
from . import theme as T
from .widgets import Flipped, TextButton, attrs, rrect, text_width

W = 440
PAD = T.PAD
VIDEO_W, VIDEO_H = W - 2 * PAD, 230
HANDS_Y = PAD + VIDEO_H + 12
HAND_H = 38
HEAD_Y = HANDS_Y + 2 * HAND_H + 4
LOG_RULE_Y = HEAD_Y + 44
LOG_Y = LOG_RULE_Y + 28
LOG_LINE = 16
DIM_IMAGE = 0.35                      # camera pixels are shown subdued so the red overlay reads

BONES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
         (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]
FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def fit_rect(aspect, x, y, w, h):
    """Largest rect of the given aspect centred in (x, y, w, h)."""
    if w / h > aspect:
        iw, ih = h * aspect, h
    else:
        iw, ih = w, w / aspect
    return x + (w - iw) / 2, y + (h - ih) / 2, iw, ih


def to_view(lm, rect):
    """Unmirrored normalised landmark -> point on the mirrored image drawn in rect."""
    x, y, w, h = rect
    return x + (1.0 - lm[0]) * w, y + lm[1] * h


def put(s, x, y, size, color, medium=False, right=False):
    a = attrs(size, color, medium)
    ns = NSString.stringWithString_(s)
    w = ns.sizeWithAttributes_(a).width
    ns.drawAtPoint_withAttributes_((x - w if right else x, y), a)
    return w


def hand_alpha(role):
    return T.A_FG if role == "right" else T.A_FG2        # pointer hand full, command hand 55%


PICK_H = 28


class CameraPicker(Flipped):
    """Covers the video: `auto` and every camera as a list, the one in use filled red (like the inspector's
    actions). Opened from the camera button, so a camera is never switched by a stray click."""

    def initWithCallback_(self, cb):
        self = objc.super(CameraPicker, self).initWithFrame_(NSMakeRect(PAD, PAD, VIDEO_W, VIDEO_H))
        self.cb, self.rows, self.selected = cb, [], None
        self.note = ""
        return self

    @objc.python_method
    def set_rows(self, rows, selected, note):
        """rows: [(key, label)], key None = auto; selected: the key that is saved."""
        self.rows, self.selected, self.note = rows, selected, note
        self.setNeedsDisplay_(True)

    @objc.python_method
    def row_at(self, p):
        i = int((p.y - 34) // PICK_H)
        return self.rows[i] if 0 <= i < len(self.rows) and p.x >= 0 else None

    def mouseDown_(self, e):
        r = self.row_at(self.convertPoint_fromView_(e.locationInWindow(), None))
        if r:
            self.cb(r[0])

    def drawRect_(self, rect):
        box = rrect(0, 0, VIDEO_W, VIDEO_H, T.CONTROL_RADIUS)
        T.black().setFill()
        box.fill()
        put("camera", 12, 12, T.SIZE_SMALL, T.dim())
        for i, (key, label) in enumerate(self.rows):
            y = 34 + i * PICK_H
            if key == self.selected:
                T.fg().setFill()
                rrect(6, y, VIDEO_W - 12, PICK_H - 2, T.CONTROL_RADIUS).fill()
                put(label, 14, y + 6, T.SIZE_TITLE, T.black(), medium=True)
            else:
                put(label, 14, y + 6, T.SIZE_TITLE, T.fg())
        if self.note:
            put(self.note, 12, VIDEO_H - 22, T.SIZE_SMALL, T.fg2())
        T.line().setStroke()
        b = rrect(0.5, 0.5, VIDEO_W - 1, VIDEO_H - 1, T.CONTROL_RADIUS)
        b.setLineWidth_(1)
        b.stroke()


class LiveView(Flipped):
    def initWithModel_(self, model):
        self = objc.super(LiveView, self).initWithFrame_(NSMakeRect(0, 0, W, 555))
        self.model = model
        self.data = None            # latest live-view dict (None while off)
        self.on = False
        self.camera = "off"
        self.image, self.image_n = None, -1
        self.rec = None
        self.rec_btn = TextButton.alloc().initWithTitle_size_color_callback_("record", T.SIZE_SMALL, "fg2", self._toggle_rec)
        self.addSubview_(self.rec_btn)
        self.cam_btn = TextButton.alloc().initWithTitle_size_color_callback_("camera", T.SIZE_SMALL, "fg2", self._toggle_picker)
        self.addSubview_(self.cam_btn)
        self.picker = CameraPicker.alloc().initWithCallback_(self._pick)
        self.picker.setHidden_(True)
        self.addSubview_(self.picker)
        self.cam_note = ""
        self.cam_key, self.cam_name = None, None
        self.place_button()
        return self

    @objc.python_method
    def _toggle_picker(self):
        if self.picker.isHidden():
            self.fill_picker()
        self.picker.setHidden_(not self.picker.isHidden())

    @objc.python_method
    def fill_picker(self):
        saved, dev, note = self.model.camera_choice()
        devs = self.model.camera_devices()
        rows = [(None, "auto · built-in camera")] + [(d.uid, d.name.lower()) for d in devs]
        self.picker.set_rows(rows, saved, note)
        self.devs = {d.uid: d for d in devs}

    @objc.python_method
    def _pick(self, uid):
        self.model.set_camera(self.devs.get(uid))
        self.picker.setHidden_(True)

    @objc.python_method
    def set_camera_info(self, key, name, note):
        """What the vision thread actually opened (the saved choice may be away)."""
        if (key, name, note) != (self.cam_key, self.cam_name, self.cam_note):
            self.cam_key, self.cam_name, self.cam_note = key, name, note
            self.cam_btn.set_title("camera · " + (name or "none").lower())
            self.place_button()
            if not self.picker.isHidden():
                self.fill_picker()
            self.setNeedsDisplay_(True)

    @objc.python_method
    def place_button(self):
        self.rec_btn.fit()
        self.rec_btn.setFrameOrigin_((W - PAD + 6 - self.rec_btn.frame().size.width, LOG_RULE_Y + 8))
        self.cam_btn.fit(max_w=170)
        self.cam_btn.setFrameOrigin_((self.rec_btn.frame().origin.x - self.cam_btn.frame().size.width - 4,
                                      LOG_RULE_Y + 8))

    @objc.python_method
    def _toggle_rec(self):
        self.model.set_recording(not (self.rec and self.rec.get("active")))

    @objc.python_method
    def set_data(self, data, camera, rec, on=True):
        self.on = bool(on)
        self.rec_btn.setHidden_(not self.on)
        if data is not None and data["n"] != self.image_n:
            self.image_n = data["n"]
            nd = NSData.dataWithBytes_length_(data["jpg"], len(data["jpg"]))
            self.image = NSImage.alloc().initWithData_(nd)
        if data is None:
            self.image, self.image_n = None, -1
        self.data, self.camera, self.rec = data, camera, rec
        active = bool(rec and rec.get("active"))
        self.rec_btn.set_title(preview.recording_label(active, rec["elapsed"] if rec else 0))
        self.rec_btn.color = "fg" if active else "fg2"
        self.place_button()
        self.setNeedsDisplay_(True)

    # -- drawing
    def drawRect_(self, rect):
        cfg = self.model.cfg
        self.draw_video(cfg)
        if not self.on:
            return                  # gestyq is off: only the calm placeholder (the camera is off too)
        self.draw_hands(cfg)
        self.draw_head(cfg)
        self.draw_log(cfg)

    @objc.python_method
    def draw_video(self, cfg):
        box = rrect(PAD, PAD, VIDEO_W, VIDEO_H, T.CONTROL_RADIUS)
        T.black().setFill()
        box.fill()
        d = self.data
        NSGraphicsContext.currentContext().saveGraphicsState()
        box.addClip()
        if d is not None and self.image is not None:
            ir = fit_rect(d["aspect"], PAD, PAD, VIDEO_W, VIDEO_H)
            self.image.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
                NSMakeRect(*ir), NSMakeRect(0, 0, 0, 0), NSCompositingOperationSourceOver, DIM_IMAGE, True, None)
            self.draw_regions(d, ir)
            for h in d["debug"]:
                self.draw_hand(h, ir)
        else:
            if self.on:
                msg = {"no camera": "no camera", "starting": "starting camera", "ok": "waiting for frames"}.get(
                    self.camera, "starting camera")
                tw = text_width(msg, T.SIZE_TITLE)
                put(msg, PAD + (VIDEO_W - tw) / 2, PAD + VIDEO_H / 2 - 8, T.SIZE_TITLE, T.dim())
            else:
                msg, sub = "gestyq is off", "the camera is off. use the switch above to turn it on."
                put(msg, PAD + (VIDEO_W - text_width(msg, T.SIZE_TITLE)) / 2, PAD + VIDEO_H / 2 - 16,
                    T.SIZE_TITLE, T.fg2(), medium=True)
                put(sub, PAD + (VIDEO_W - text_width(sub, T.SIZE_SMALL)) / 2, PAD + VIDEO_H / 2 + 8,
                    T.SIZE_SMALL, T.dim())
        NSGraphicsContext.currentContext().restoreGraphicsState()
        if self.cam_note:
            put(self.cam_note, PAD + 10, PAD + VIDEO_H - 22, T.SIZE_SMALL, T.fg2())
        T.line().setStroke()
        b = rrect(PAD + 0.5, PAD + 0.5, VIDEO_W - 1, VIDEO_H - 1, T.CONTROL_RADIUS)
        b.setLineWidth_(1)
        b.stroke()

    @objc.python_method
    def draw_regions(self, d, ir):
        """Subtle red outlines (32%): the crop the detectors see while you are far (dashed), and (absolute
        pointer mode only) the box of camera the pointer maps onto the displays."""
        for key, dashed in (("zoom", True), ("box", False)):
            r = d.get(key)
            if not r:
                continue
            (x0, y0), (x1, y1) = to_view((r[0], r[1]), ir), to_view((r[0] + r[2], r[1] + r[3]), ir)
            x, y, w, h = min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
            p = rrect(x + 0.5, y + 0.5, w - 1, h - 1, 2)
            p.setLineWidth_(1)
            if dashed:
                p.setLineDash_count_phase_([4.0, 3.0], 2, 0.0)
            T.dim().setStroke()
            p.stroke()
            put(key, x + 4, y + 3, T.SIZE_SMALL, T.dim())

    @objc.python_method
    def draw_hand(self, h, ir):
        a = hand_alpha(h["role"])
        pts = [to_view(p, ir) for p in h["lms"]]
        T.red(a).setStroke()
        path = NSBezierPath.bezierPath()
        for i, j in BONES:
            path.moveToPoint_(pts[i])
            path.lineToPoint_(pts[j])
        path.setLineWidth_(1.5)
        path.stroke()
        T.red(a).setFill()
        for x, y in pts:
            NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x - 2.5, y - 2.5, 5, 5)).fill()
        tag = f"{h['role']} · {'pinch' if h['pinch'] else h['pose']}"
        tw = text_width(tag, T.SIZE_SMALL)
        x = min(max(pts[0][0] - tw / 2, PAD + 4), PAD + VIDEO_W - tw - 4)
        y = min(pts[0][1] + 8, PAD + VIDEO_H - 18)
        T.black().colorWithAlphaComponent_(0.7).setFill()
        NSBezierPath.fillRect_(NSMakeRect(x - 3, y - 1, tw + 6, 15))
        put(tag, x, y, T.SIZE_SMALL, T.red(a))

    @objc.python_method
    def draw_hands(self, cfg):
        hc = cfg["hand"]
        hands = sorted(self.data["debug"], key=lambda h: h["role"] != "right") if self.data else []
        if not hands:
            put("no hands" if self.data else "", PAD, HANDS_Y + 2, T.SIZE_SMALL, T.dim())
            return
        for i, h in enumerate(hands[:2]):
            y = HANDS_Y + i * HAND_H
            a = hand_alpha(h["role"])
            kind = "pointer" if h["role"] == "right" else "command"
            put(f"{h['role']} · {kind} · {h['pose']}", PAD, y, T.SIZE_TITLE, T.red(a), medium=True)
            put(f"vote {h['vote']:+.2f}   mp {h['label_mp'].lower()}", W - PAD, y + 2, T.SIZE_SMALL, T.fg2(), right=True)
            for k, f in enumerate(FINGERS):
                x, fy = PAD + k * 20, y + 19
                ext = h["fingers"].get(f) == "ext"
                if ext:
                    T.fg().setFill()
                    rrect(x, fy, 16, 16, 3).fill()
                else:
                    T.line().setStroke()
                    p = rrect(x + 0.5, fy + 0.5, 15, 15, 3)
                    p.setLineWidth_(1)
                    p.stroke()
                col = T.black() if ext else T.fg2()
                put(f[0].upper(), x + 4.5, fy + 1.5, T.SIZE_SMALL, col)
            self.draw_meter(h, hc, 132, y + 19)

    @objc.python_method
    def draw_meter(self, h, hc, x0, y):
        top = 0.7
        bw = W - PAD - 52 - x0
        put("pinch", x0, y + 1, T.SIZE_SMALL, T.fg2())
        bx = x0 + 40
        bw = W - PAD - bx - 40
        T.line().setFill()
        NSBezierPath.fillRect_(NSMakeRect(bx, y + 6, bw, 4))
        fr = preview.meter_fraction(h["ratio"], top)
        (T.fg() if h["pinch"] else T.fg2()).setFill()
        NSBezierPath.fillRect_(NSMakeRect(bx, y + 6, bw * fr, 4))
        for name in ("pinch_on", "pinch_off"):
            tx = bx + bw * preview.meter_fraction(hc[name], top)
            T.fg().setFill()
            NSBezierPath.fillRect_(NSMakeRect(tx - 0.5, y + 2, 1, 12))
        put(f"{min(h['ratio'], 9.9):.2f}", W - PAD, y + 1, T.SIZE_SMALL, T.fg2(), right=True)

    @objc.python_method
    def draw_head(self, cfg):
        lvl = int(cfg.get("head_level", 0))
        if lvl <= 0:
            put("head off", PAD, HEAD_Y + 2, T.SIZE_SMALL, T.dim())
            return
        hd = self.data and self.data.get("head")
        for i, (name, key, tk) in enumerate((("yaw", "yaw", "thr_yaw"), ("pitch", "pitch", "thr_pitch"))):
            y = HEAD_Y + i * 18
            put("head " + name, PAD, y, T.SIZE_SMALL, T.fg2())
            bx, bw = PAD + 84, 200
            T.line().setFill()
            NSBezierPath.fillRect_(NSMakeRect(bx, y + 6, bw, 2))
            if not hd:
                continue
            thr = hd[tk]
            span = thr * 2
            v = max(-span, min(span, hd[key]))
            cx = bx + bw / 2
            hit = abs(hd[key]) >= thr
            (T.fg() if hit else T.fg2()).setFill()
            NSBezierPath.fillRect_(NSMakeRect(min(cx, cx + v / span * bw / 2), y + 4, abs(v) / span * bw / 2, 6))
            T.fg().setFill()
            for s in (-1, 1):
                NSBezierPath.fillRect_(NSMakeRect(cx + s * bw / 4 - 0.5, y + 2, 1, 10))
            put(f"{hd[key]:+.1f} / {thr:.0f}" + ("" if hd["calibrated"] else " · calibrating"), W - PAD, y, T.SIZE_SMALL,
                T.fg2(), right=True)

    @objc.python_method
    def draw_log(self, cfg):
        T.line().setFill()
        NSBezierPath.fillRect_(NSMakeRect(PAD, LOG_RULE_Y, W - 2 * PAD, 1))
        put("recent gestures", PAD, LOG_RULE_Y + 12, T.SIZE_SMALL, T.dim())
        items = list(reversed(self.data["gestures"])) if self.data else []
        now = time.monotonic()
        if not items:
            put("none yet. try a pinch.", PAD, LOG_Y + 4, T.SIZE_SMALL, T.dim())
        for i, (seq, t, gid) in enumerate(items[:preview.LOG_SIZE]):
            y = LOG_Y + i * LOG_LINE
            fresh = now - t < 1.5
            put(preview.log_line(gid, cfg), PAD, y, T.SIZE_SMALL, T.fg() if fresh else T.fg2())
            put(f"{int(now - t)} s", W - PAD, y, T.SIZE_SMALL, T.dim(), right=True)
