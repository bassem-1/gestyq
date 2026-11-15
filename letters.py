"""Built-in letter shapes, generated in code (pure Python). Units: x-height = 1, baseline y = 0, y UP, ascender 2, descender -1.
Each letter -> list of variants; a variant = list of strokes; a stroke = list of (x, y) in drawing order."""
import math

def L(*pts):                       # polyline through points
    return [tuple(map(float, p)) for p in pts]

def A(cx, cy, rx, ry, a0, a1, n=None):   # elliptical arc, degrees, a0 -> a1 (either direction)
    n = n or max(4, int(abs(a1 - a0) / 12))
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]

def J(*parts):                     # join parts into one stroke (duplicates at the seams are fine)
    out = []
    for p in parts:
        out += p
    return out

BOWL_CCW = lambda a0=20: A(.5, .5, .5, .5, a0, a0 + 360)      # a / d / g / q bowl, starts top right
LETTERS = {
 "a": [[J(BOWL_CCW(30), L((.93, .75), (1, 1), (1, 0)))]],
 "b": [[J(L((0, 2), (0, 0), (0, .5)), A(.5, .5, .5, .5, 180, -180))]],
 "c": [[A(.5, .5, .5, .5, 50, 310)]],
 "d": [[J(BOWL_CCW(30), L((.93, .75), (1, 2), (1, 0)))]],
 "e": [[J(L((0, .5), (1, .5)), A(.5, .5, .5, .5, 0, 310))]],
 "f": [[J(A(.75, 1.6, .35, .4, 20, 180), L((.4, 1.6), (.4, 0))), L((0, 1), (.9, 1))],
       [J(A(.75, 1.6, .35, .4, 20, 180), L((.4, 1.6), (.4, 0), (.4, 1), (0, 1), (.9, 1)))]],
 "g": [[J(BOWL_CCW(30), L((.93, .75), (1, 1), (1, -.5)), A(.5, -.5, .5, .5, 0, -160))]],
 "h": [[J(L((0, 2), (0, 0), (0, .5)), A(.5, .5, .5, .5, 180, 0), L((1, .5), (1, 0)))]],
 "i": [[L((0, 1), (0, 0))]],
 "j": [[J(L((.6, 1), (.6, -.5)), A(.1, -.5, .5, .5, 0, -170))]],
 "k": [[L((0, 2), (0, 0)), L((.9, 1), (0, .45), (.9, 0))],
       [L((0, 2), (0, 0), (0, .45), (.9, 1), (0, .45), (.9, 0))]],
 "l": [[J(L((0, 2), (0, .3)), A(.3, .3, .3, .3, 180, 270), L((.3, 0), (.9, 0)))],   # tall stem with a long right foot (a bare line is i)
       [J(L((0, 0), (.25, .9)), A(.25, 1.55, .25, .45, -30, 200), L((.02, 1.4), (.1, 0), (.4, 0)))]],   # cursive loop
 "m": [[J(L((0, 1), (0, 0), (0, .6)), A(.35, .6, .35, .4, 180, 0), L((.7, .6), (.7, 0), (.7, .6)),
          A(1.05, .6, .35, .4, 180, 0), L((1.4, .6), (1.4, 0)))]],
 "n": [[J(L((0, 1), (0, 0), (0, .5)), A(.5, .5, .5, .5, 180, 0), L((1, .5), (1, 0)))]],
 "o": [[A(.5, .5, .5, .5, 90, 450)]],
 "p": [[J(L((0, 1), (0, -1), (0, .5)), A(.5, .5, .5, .5, 180, -180))]],
 "q": [[J(BOWL_CCW(30), L((.93, .75), (1, 1), (1, -1)))]],
 "r": [[J(L((0, 1), (0, 0), (0, .5)), A(.5, .5, .5, .5, 180, 40))]],
 "s": [[J(A(.5, .75, .42, .25, 30, 270), A(.5, .25, .42, .25, 90, -150))]],
 "t": [[J(L((.4, 1.7), (.4, .3)), A(.7, .3, .3, .3, 180, 280)), L((0, 1), (.9, 1))],
       [J(L((.4, 1.7), (.4, .3)), A(.7, .3, .3, .3, 180, 280), L((.75, 0), (.4, .3), (.4, 1), (0, 1), (.9, 1)))]],
 "u": [[J(L((0, 1), (0, .5)), A(.5, .5, .5, .5, 180, 360), L((1, .5), (1, 1), (1, 0)))]],
 "v": [[L((0, 1), (.5, 0), (1, 1))]],
 "w": [[L((0, 1), (.3, 0), (.6, .8), (.9, 0), (1.2, 1))]],
 "x": [[L((0, 1), (1, 0)), L((1, 1), (0, 0))],
       [L((0, 1), (1, 0), (1, 1), (0, 0))]],
 "y": [[L((0, 1), (.5, 0)), L((1, 1), (.2, -1))],
       [L((0, 1), (.5, 0), (1, 1), (.2, -1))]],
 "z": [[L((0, 1), (1, 1), (0, 0), (1, 0))]],
}

# one more key: enter is a stroke down, then left (a "return" arrow)
LETTERS["\n"] = [[L((1, 1.2), (1, 0), (-0.2, 0))]]

# letters whose single-stroke variants are also matched when drawn backwards: people in the air do not keep one
# direction (measured: 79% -> 93.5% at noise 1.0 with 25% of strokes reversed). Not l: reversed it reads z as l.
REVERSIBLE = "abcdefghijkmnopqrstuvwxyz"
