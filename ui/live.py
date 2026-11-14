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


class LiveView(Flipped):
    def initWithModel_(self, model):
        self = objc.super(LiveView, self).initWithFrame_(NSMakeRect(0, 0, W, 555))
        self.model = model
        self.data = None            # latest preview dict
        self.camera = "off"
        self.image, self.image_n = None, -1
        self.rec = None
        self.rec_btn = TextButton.alloc().initWithTitle_size_color_callback_("record", T.SIZE_SMALL, "fg2", self._toggle_rec)
        self.addSubview_(self.rec_btn)
        self.place_button()
        return self

    @objc.python_method
    def place_button(self):
        self.rec_btn.fit()
        self.rec_btn.setFrameOrigin_((W - PAD + 6 - self.rec_btn.frame().size.width, LOG_RULE_Y + 8))

    @objc.python_method
    def _toggle_rec(self):
        self.model.set_recording(not (self.rec and self.rec.get("active")))

    @objc.python_method
    def set_data(self, data, camera, rec):
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
            for h in d["debug"]:
                self.draw_hand(h, ir)
        else:
            msg = {"no camera": "no camera", "starting": "starting camera", "ok": "waiting for frames"}.get(
                self.camera, "camera off")
            tw = text_width(msg, T.SIZE_TITLE)
            put(msg, PAD + (VIDEO_W - tw) / 2, PAD + VIDEO_H / 2 - 8, T.SIZE_TITLE, T.dim())
        NSGraphicsContext.currentContext().restoreGraphicsState()
        T.line().setStroke()
        b = rrect(PAD + 0.5, PAD + 0.5, VIDEO_W - 1, VIDEO_H - 1, T.CONTROL_RADIUS)
        b.setLineWidth_(1)
        b.stroke()

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
