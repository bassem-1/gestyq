"""Synthetic handwriting: the built-in letter shapes with slant, width, rotation, wobble, jitter and stroke-end hooks.
Ink comes out in palm units, y UP like letters.LETTERS; use flip() for the y-down ink the recogniser gets."""
import math
import random

import letters


def densify(st, step=0.06):
    out = [st[0]]
    for a, b in zip(st, st[1:]):
        d = math.dist(a, b)
        k = max(1, int(d / step))
        out += [(a[0] + (b[0] - a[0]) * i / k, a[1] + (b[1] - a[1]) * i / k) for i in range(1, k + 1)]
    return out


def synth(strokes, rng, level=1.0, p_rev=0.0, hooks=True):
    sh, sx, rot = rng.uniform(-.3, .3) * level, 1 + rng.uniform(-.25, .3) * level, math.radians(rng.gauss(0, 6) * level)
    c, s = math.cos(rot), math.sin(rot)
    out = []
    for st in strokes:
        st = densify(st)
        if rng.random() < p_rev:
            st = st[::-1]
        if hooks:
            for end in (0, -1):
                l, a = rng.uniform(0, .22) * level, rng.uniform(0, 2 * math.pi)
                p = st[end]
                q = (p[0] + l * math.cos(a), p[1] + l * math.sin(a))
                seg = densify([q, p]) if end == 0 else densify([p, q])
                st = seg + st if end == 0 else st + seg
        f1, f2, p1, p2 = rng.uniform(.3, 1.2), rng.uniform(.3, 1.2), rng.uniform(0, 6.3), rng.uniform(0, 6.3)
        amp = rng.uniform(.03, .09) * level
        pts = []
        for i, (x, y) in enumerate(st):
            u = i * 0.06
            x += amp * math.sin(2 * math.pi * f1 * u + p1) + rng.gauss(0, .02 * level)
            y += amp * math.sin(2 * math.pi * f2 * u + p2) + rng.gauss(0, .02 * level)
            x = x * sx + sh * y
            pts.append((c * x - s * y, s * x + c * y))
        out.append(pts)
    return out


def flip(strokes):
    return [[(x, -y) for x, y in s] for s in strokes]


def accuracy(rec, level, p_rev=0.0, trials=40, seed=1, chars=None):
    """-> (fraction right, [(want, got)] mistakes) over `trials` noisy copies of every letter (A-Z by default)."""
    rng = random.Random(seed)
    ok = n = 0
    bad = []
    for ch in chars or "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        for _ in range(trials):
            variants = letters.LETTERS[ch]
            ink = flip(synth(rng.choice(variants), rng, level, p_rev))
            got = rec.recognize(ink)
            n += 1
            if got and got[0].char.upper() == ch:
                ok += 1
            else:
                bad.append((ch, got[0].char if got else None))
    return ok / n, bad
