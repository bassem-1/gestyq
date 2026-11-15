"""Built-in letter shapes, generated in code (pure Python): CAPITALS A-Z, the way block capitals are written in the air.
Units: cap height = 1, baseline y = 0, y UP. (The lowercase set was removed with the switch to capitals; see git history.)
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


def S(*strokes):                   # a variant from several strokes
    return [list(s) for s in strokes]

def BOWL(cx, cy, rx, ry):          # clockwise right-hand bowl from the top (cx, cy + ry) to the bottom
    return A(cx, cy, rx, ry, 90, -90)

STEM = L((0, 1), (0, 0))
P_BOWL = lambda: A(0, .72, .55, .28, 90, -90)          # upper bowl of P / R / B, ends back on the stem at y = .44
LETTERS = {
 "A": [S(L((0, 0), (.5, 1), (1, 0)), L((.82, .35), (.18, .35))),          # left leg up, right leg down, bar
       S(L((1, 0), (.5, 1), (0, 0)), L((.18, .35), (.82, .35))),          # right leg first
       [L((0, 0), (.5, 1), (1, 0), (.82, .35), (.18, .35))],               # one path
       [L((1, 0), (.5, 1), (0, 0), (.18, .35), (.82, .35))],
       [L((0, 0), (.5, 1), (1, 0))]],                                       # no bar
 "B": [[J(L((0, 1), (0, 0), (0, 1)), P_BOWL(), A(0, .25, .62, .25, 90, -90))],
       S(L((0, 1), (0, 0)), J(P_BOWL(), A(0, .25, .62, .25, 90, -90)))],
 "C": [[A(.5, .5, .5, .5, 45, 315)]],
 "D": [[J(L((0, 1), (0, 0), (0, 1)), BOWL(0, .5, .8, .5))],
       S(L((0, 1), (0, 0)), BOWL(0, .5, .8, .5)),
       [J(L((0, 0), (0, 1)), BOWL(0, .5, .8, .5))]],
 "E": [[L((1, 1), (0, 1), (0, .5), (.8, .5), (0, .5), (0, 0), (1, 0))],
       S(L((1, 1), (0, 1), (0, 0), (1, 0)), L((0, .5), (.8, .5)))],
 "F": [[L((1, 1), (0, 1), (0, .5), (.8, .5), (0, .5), (0, 0))],
       S(L((1, 1), (0, 1), (0, 0)), L((0, .5), (.8, .5)))],
 "G": [[J(A(.5, .5, .5, .5, 40, 360), L((1, .5), (.55, .5)))],
       [J(A(.5, .5, .5, .5, 40, 330), L((.93, .25), (.93, .45), (.55, .45)))]],
 "H": [S(L((0, 1), (0, 0)), L((1, 1), (1, 0)), L((0, .5), (1, .5))),
       [L((0, 1), (0, 0), (0, .5), (1, .5), (1, 1), (1, 0))],
       S(L((0, 0), (0, 1)), L((1, 0), (1, 1)), L((0, .5), (1, .5)))],
 "I": [[L((0, 1), (0, 0))],
       [L((-.3, 1), (.3, 1), (0, 1), (0, 0), (-.3, 0), (.3, 0))]],
 "J": [[J(L((.3, 1), (.3, .35)), A(0, .35, .3, .35, 0, -215))],
       [J(L((-.2, 1), (.3, 1), (.3, .35)), A(0, .35, .3, .35, 0, -215))]],
 "K": [S(L((0, 1), (0, 0)), L((1.1, 1), (0, .42), (1.1, 0))),
       [L((0, 1), (0, 0), (0, .42), (1.1, 1), (0, .42), (1.1, 0))],
       [L((0, 1), (0, 0), (0, .42), (1.1, 0), (0, .42), (1.1, 1))],
       S(L((0, 1), (0, 0)), L((1.1, 0), (0, .42), (1.1, 1)))],
 "L": [[L((0, 1), (0, 0), (.7, 0))]],
 "M": [[L((0, 0), (0, 1), (.5, .3), (1, 1), (1, 0))],
       [L((0, 1), (0, 0), (0, 1), (.5, .3), (1, 1), (1, 0))],
       [L((0, 0), (0, 1), (.5, 0), (1, 1), (1, 0))]],
 "N": [[L((0, 0), (0, 1), (1, 0), (1, 1))],
       [L((0, 1), (0, 0), (0, 1), (1, 0), (1, 1))]],
 "O": [[A(.5, .5, .5, .5, 90, 450)],
       [A(.5, .5, .5, .5, 90, -270)],
       [A(.5, .5, .5, .5, 90, 480)],
       [A(.5, .5, .5, .5, 180, 540)]],
 "P": [[J(L((0, 1), (0, 0), (0, 1)), P_BOWL())],
       S(L((0, 1), (0, 0)), P_BOWL())],
 "Q": [[J(A(.5, .5, .5, .5, 90, 450), L((.6, .35), (1.05, -.05)))],
       [J(A(.5, .5, .5, .5, 90, -270), L((.6, .35), (1.05, -.05)))]],
 "R": [[J(L((0, 1), (0, 0), (0, 1)), P_BOWL(), L((0, .44), (.8, 0)))],
       S(L((0, 1), (0, 0)), J(P_BOWL(), L((0, .44), (.8, 0))))],
 "S": [[J(A(.5, .75, .5, .25, 25, 270), A(.5, .25, .5, .25, 90, -155))]],
 "T": [S(L((0, 1), (1, 1)), L((.5, 1), (.5, 0))),
       [L((0, 1), (1, 1), (.5, 1), (.5, 0))],
       S(L((.5, 1), (.5, 0)), L((0, 1), (1, 1))),
       S(L((1, 1), (0, 1)), L((.5, 1), (.5, 0)))],
 "U": [[J(L((0, 1), (0, .5)), A(.5, .5, .5, .5, 180, 360), L((1, .5), (1, 1)))],
       [J(L((0, 1), (0, .7)), A(.5, .7, .5, .7, 180, 360), L((1, .7), (1, 1)))]],
 "V": [[L((0, 1), (.4, 0), (.8, 1))]],
 "W": [[L((0, 1), (.45, 0), (.9, .75), (1.35, 0), (1.8, 1))],
       [L((0, 1), (.45, 0), (.9, 1), (1.35, 0), (1.8, 1))]],
 "X": [S(L((0, 1), (1, 0)), L((1, 1), (0, 0))),
       S(L((0, 1), (1, 0)), L((0, 0), (1, 1))),
       S(L((1, 1), (0, 0)), L((0, 1), (1, 0))),
       [L((0, 1), (1, 0), (1, 1), (0, 0))]],
 "Y": [S(L((0, 1), (.5, .5), (1, 1)), L((.5, .5), (.5, 0))),
       [L((0, 1), (.5, .5), (1, 1), (.5, .5), (.5, 0))],
       S(L((0, 1), (.5, .5), (.5, 0)), L((1, 1), (.5, .5)))],
 "Z": [[L((0, 1), (1, 1), (0, 0), (1, 0))]],
}

# one more key: enter is a stroke down, then left (a "return" arrow)
LETTERS["\n"] = [[L((1, 1.2), (1, 0), (-0.2, 0))]]

# letters whose single-stroke variants are also matched when drawn backwards: people in the air do not keep one
# direction (measured: 79% -> 93.5% at noise 1.0 with 25% of strokes reversed). Not L: reversed it is a different shape.
REVERSIBLE = "ABCDEFGHIJKMNOPQRSTUVWXYZ"
