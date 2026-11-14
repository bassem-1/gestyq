"""Eye-corner gaze detector (BETA, default off). Ported from v2: blendshape based, dwell on a
corner fires "gaze:<corner>". Pure Python."""
from events import Event
from filters import clamp


class GazeDetector:
    def __init__(self, cfg):
        self.cfg = cfg
        self.g = cfg["gaze"]
        self.cur = None
        self.start = 0.0
        self.last_seen = -1e9
        self.fired = False
        self.vec = (0.0, 0.0)
        self.corner = None
        self.progress = 0.0

    def reset(self):
        self.cur, self.fired, self.corner, self.progress = None, False, None, 0.0

    def classify(self, bs):
        if not bs:
            self.vec = (0.0, 0.0)
            return None
        g = self.g
        v = lambda n: float(bs.get(n, 0.0))
        xr = (v("eyeLookOutRight") + v("eyeLookInLeft")) / 2   # subject looks to their right
        xl = (v("eyeLookOutLeft") + v("eyeLookInRight")) / 2
        x = xr - xl
        if self.cfg.get("flip_gaze_x"):
            x = -x
        up = (v("eyeLookUpLeft") + v("eyeLookUpRight")) / 2
        down = (v("eyeLookDownLeft") + v("eyeLookDownRight")) / 2
        self.vec = (x, up - down)
        h = "right" if x >= g["x_thresh"] else "left" if x <= -g["x_thresh"] else None
        vt = ("top" if up >= g["up_thresh"] and up > down else
              "bottom" if down >= g["down_thresh"] and down > up else None)
        return f"{vt}-{h}" if h and vt else None

    def update(self, bs, now):
        """bs: dict blendshape name -> score, or None if no face. Returns list of events."""
        g = self.g
        ev = []
        corner = self.classify(bs)
        self.corner = corner
        if corner:
            self.last_seen = now
            if corner != self.cur:
                self.cur, self.start, self.fired = corner, now, False
            if not self.fired and now - self.start >= g["dwell"]:
                self.fired = True
                ev.append(Event("gaze", corner))
            self.progress = 1.0 if self.fired else clamp((now - self.start) / g["dwell"])
        else:
            if self.cur and now - self.last_seen > g["grace"]:
                self.cur, self.fired = None, False
            if self.cur and not self.fired:
                self.progress = clamp((now - self.start) / g["dwell"])
            else:
                self.progress = 0.0
        return ev
