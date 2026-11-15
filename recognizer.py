"""Letter recognition (pure Python): an ordered point-path template matcher.

Ink (palm units, x right, y DOWN, drawing order) is resampled to 32 points, centred and scaled uniformly (the
aspect is kept, there is no rotation invariance on purpose: n is not u), and compared point by point with
built-in templates (letters.py, generated in code) and the user's own (TemplateStore).

Interface (the plug point; a VisionRecognizer could implement the same two members):

    recognizer.name
    recognizer.recognize(strokes) -> [Candidate]   best first, at most 3, one per char; [] = nothing
"""
import json
import os
import time
from collections import namedtuple

import config
import letters
from ink import normalize, resample

Candidate = namedtuple("Candidate", "char dist score")      # dist: lower is better; score = max(0, 1 - dist / reject)

N = 32
DEFAULTS = {"reject": 0.28, "margin": 0.02, "user_weight": 0.9, "max_user": 5, "charset": "lower"}
ENTER_MAX = 0.14


def prep(strokes, n=N):
    pts = resample(strokes, n)
    return normalize(pts) if pts else []


def dist(a, b):
    return sum(((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5 for p, q in zip(a, b)) / len(a)


def _flip(strokes):
    """Template units (y up) -> ink units (y down)."""
    return [[(x, -y) for x, y in s] for s in strokes]


def builtin_templates():
    """[(char, prepped points)]: every variant, plus the reversed drawing direction of single strokes for
    letters.REVERSIBLE."""
    out = []
    for ch, variants in letters.LETTERS.items():
        for v in variants:
            v = _flip(v)
            out.append((ch, prep(v)))
            if len(v) == 1 and ch in letters.REVERSIBLE:
                out.append((ch, prep([v[0][::-1]])))
    return out


class TemplateStore:
    """The user's own templates: raw strokes in palm units, at most `max_user` per char (oldest dropped).
    File: ~/Library/Application Support/gestyq/letters.json (GESTYQ_LETTERS overrides)."""

    def __init__(self, path=None, max_user=5):
        self.path = path or user_path()
        self.max_user = max_user
        self.data = {}
        self.load()

    def load(self):
        self.data = {}
        try:
            with open(self.path) as f:
                raw = json.load(f)
            for ch, items in raw["templates"].items():
                good = []
                for it in items:
                    strokes = [[(float(x), float(y)) for x, y in s] for s in it["strokes"]]
                    if strokes and all(len(s) >= 1 for s in strokes):
                        good.append({"strokes": strokes, "t": float(it.get("t", 0))})
                if good and isinstance(ch, str) and len(ch) == 1:
                    self.data[ch] = good
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.data = {}
        return self

    def add(self, ch, strokes, now=None):
        items = self.data.setdefault(ch, [])
        items.append({"strokes": [[tuple(p) for p in s] for s in strokes], "t": now if now is not None else time.time()})
        items.sort(key=lambda it: it["t"])
        del items[:-self.max_user]

    def clear(self, ch):
        self.data.pop(ch, None)

    def save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"version": 1, "templates": {
                ch: [{"strokes": [[list(p) for p in s] for s in it["strokes"]], "t": it["t"]} for it in items]
                for ch, items in self.data.items()}}, f)
        os.replace(tmp, self.path)

    def templates(self):
        return [(ch, prep(it["strokes"])) for ch, items in self.data.items() for it in items]


def user_path():
    return os.environ.get("GESTYQ_LETTERS") or os.path.join(os.path.dirname(config.user_path()), "letters.json")


class TemplateRecognizer:
    name = "templates"

    def __init__(self, cfg=None, store=None):
        w = dict(DEFAULTS)
        w.update(((cfg or {}).get("write", cfg) or {}) if cfg else {})
        self.w = w
        self.base = builtin_templates()
        self.store = store

    def recognize(self, strokes):
        pts = prep(strokes)
        if not pts:
            return []
        best = {}
        for ch, t in self.base:
            d = dist(pts, t)
            if d < best.get(ch, 9e9):
                best[ch] = d
        if self.store is not None:
            for ch, t in self.store.templates():
                d = dist(pts, t) * self.w["user_weight"]
                if d < best.get(ch, 9e9):
                    best[ch] = d
        ranked = sorted(best.items(), key=lambda kv: kv[1])
        if not ranked or ranked[0][1] > self.w["reject"]:
            return []
        if ranked[0][0] == "\n":      # enter is strict: a clean stroke and no close runner-up
            ok = ranked[0][1] <= ENTER_MAX and (len(ranked) < 2 or ranked[1][1] - ranked[0][1] >= self.w["margin"])
            if not ok:
                ranked = ranked[1:]
        ranked = [(ch, d) for ch, d in ranked if ch != "\n" or d <= ENTER_MAX][:3]
        if ranked and ranked[0][1] > self.w["reject"]:
            return []
        rej = self.w["reject"]
        return [Candidate(ch, d, max(0.0, 1.0 - d / rej)) for ch, d in ranked]

    def unsure(self, cands):
        return len(cands) > 1 and cands[1].dist - cands[0].dist < self.w["margin"]


def make(cfg, store=None):
    """"templates" (default); "vision" is a later opt-in and falls back to templates until it exists."""
    return TemplateRecognizer(cfg, store)
