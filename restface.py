"""Hands resting on the face or head (chin on hand, hand on cheek / forehead / top of the head) are ignored.

Pure Python. A hand is *resting* when its palm centre is inside the head region (the face box grown sideways and
upward over the head, plus a band under the chin) and it has been roughly still for rest_still_time seconds, or
when many of its landmarks overlap the face box. A resting hand gets no role and emits nothing; it counts again
only after its palm centre has left the region (hysteresis), so raising a hand in front of the face and moving it
works as soon as it moves (it is not still) or clears the region."""
import math
from collections import deque

from tracking import iso, palm_anchor, palm_scale

MATCH = 0.2          # frame widths: a hand within this of a track's last palm centre is the same hand


def head_region(box, h):
    """Face box (x0, y0, x1, y1) -> head region (x0, y0, x1, y1), full-frame normalised."""
    x0, y0, x1, y1 = box
    cx, w, hh = (x0 + x1) / 2, x1 - x0, y1 - y0
    sx = h.get("rest_scale_x", 1.4) / 2 * w
    return (cx - sx, y0 - h.get("rest_up", 0.5) * hh, cx + sx, y1 + h.get("rest_down", 0.3) * hh)


def _in(p, r):
    return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]


class _Track:
    __slots__ = ("hist", "ignored")

    def __init__(self):
        self.hist, self.ignored = deque(), False


class RestFilter:
    def __init__(self, h):
        self.h = h
        self.tracks = []

    def reset(self):
        self.tracks = []

    def _still(self, tr, now, palm):
        """Palm centre extent over the last rest_still_time s, in palm sizes per second, below rest_speed."""
        win = self.h.get("rest_still_time", 0.3)
        pts = [p for p in tr.hist if now - p[0] <= win + 1e-6]
        if not tr.hist or now - tr.hist[0][0] < win - 1e-6:
            return False                                          # not observed long enough
        xs, ys = [p[1] for p in pts], [p[2] for p in pts]
        ext = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        return ext / max(palm, 1e-3) / win < self.h.get("rest_speed", 0.5)

    def split(self, obs, now, aspect, box, box_fresh):
        """obs: HandObs list. box: last known face box or None; box_fresh: it is recent enough to start ignoring
        a hand (an already ignored hand keeps being judged against the older box). -> (kept, resting)."""
        h = self.h
        if not h.get("rest_filter", True):
            return list(obs), []
        region = head_region(box, h) if box is not None else None
        pool, out = list(self.tracks), []
        kept, rest, tracks = [], [], []
        for o in obs:
            ax, ay = palm_anchor(o.lms)
            best, bd = None, MATCH
            for tr in pool:
                px, py = tr.hist[-1][1], tr.hist[-1][2]
                d = math.hypot((ax - px), (ay - py) * (1 / aspect))
                if d < bd:
                    best, bd = tr, d
            if best is None:
                best = _Track()
            else:
                pool.remove(best)
            tr = best
            tr.hist.append((now, ax, ay))
            while tr.hist and now - tr.hist[0][0] > h.get("rest_still_time", 0.3) + 0.35:
                tr.hist.popleft()
            tracks.append(tr)
            if region is None:
                tr.ignored = False
                kept.append(o)
                continue
            inside = _in((ax, ay), region)
            if tr.ignored:
                # hysteresis: stays ignored until the palm centre leaves the region (judged on the held box)
                if inside:
                    rest.append(o)
                    continue
                tr.ignored = False
                tr.hist.clear()
                tr.hist.append((now, ax, ay))
            elif box_fresh:
                fx0, fy0, fx1, fy1 = box
                n_in = sum(1 for p in o.lms if fx0 <= p[0] <= fx1 and fy0 <= p[1] <= fy1)
                palm = palm_scale(iso(o.lms, aspect))
                if (n_in / len(o.lms) >= h.get("rest_overlap", 0.5)
                        or (inside and self._still(tr, now, palm))):
                    tr.ignored = True
                    rest.append(o)
                    continue
            kept.append(o)
        self.tracks = tracks
        return kept, rest
