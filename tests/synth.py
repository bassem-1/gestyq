"""Synthetic MediaPipe-style hand landmarks (unmirrored frame, x right / y down, aspect 1)."""
import math

import config
from tracking import HandObs

# local frame, RIGHT hand, palm toward camera, fingers up (wrist at origin). Thumb/index side is +x.
MCP = {"index": (0.040, -0.090), "middle": (0.013, -0.095), "ring": (-0.013, -0.090), "pinky": (-0.040, -0.080)}
SEG = (0.040, 0.025, 0.022)
FLEX_FIST = (80.0, 100.0, 60.0)        # degrees at MCP, PIP, DIP when fully curled (toward camera)


def finger(name, curl):
    """curl 0 = straight, 1 = fist. Returns (mcp, pip, dip, tip) as (x, y, z)."""
    x, y = MCP[name]
    pts = [(x, y, 0.0)]
    cum = 0.0
    for seg, flex in zip(SEG, FLEX_FIST):
        cum += math.radians(flex * curl)
        px, py, pz = pts[-1]
        pts.append((px, py - seg * math.cos(cum), pz - seg * math.sin(cum)))
    return pts


def make_hand(side="right", x=0.3, y=0.5, curl=(0, 0, 0, 0), thumb="ext", pinch=0.0, scale=1.0, back=False):
    """21 landmarks. curl: per finger (index..pinky) 0..1. thumb 'ext' | 'curl'.
    pinch 0..1 moves the thumb tip onto the index tip. side 'left' mirrors the hand.
    back=True shows the back of the hand (mirror of the geometry, as if palm faced away)."""
    L = [None] * 21
    L[0] = (0.0, 0.0, 0.0)
    if thumb == "ext":
        L[1], L[2], L[3], L[4] = (0.03, -0.02, 0), (0.065, -0.045, 0), (0.09, -0.07, 0), (0.11, -0.09, 0)
    else:
        L[1], L[2], L[3], L[4] = (0.03, -0.02, 0), (0.06, -0.04, -0.01), (0.05, -0.065, -0.02), (0.02, -0.07, -0.02)
    for fi, name in enumerate(("index", "middle", "ring", "pinky")):
        pts = finger(name, curl[fi])
        base = 5 + 4 * fi
        for k in range(4):
            L[base + k] = pts[k]
    if pinch > 0:
        tip = L[8]
        target4 = (tip[0] + 0.004, tip[1] + 0.004, tip[2])
        target3 = ((L[2][0] + target4[0]) / 2 + 0.01, (L[2][1] + target4[1]) / 2, tip[2] / 2)
        L[3] = tuple(a + (b - a) * pinch for a, b in zip(L[3], target3))
        L[4] = tuple(a + (b - a) * pinch for a, b in zip(L[4], target4))
    flip = (side == "left") != back
    out = []
    for px, py, pz in L:
        if flip:
            px = -px
        out.append((x + px * scale, y + py * scale, pz * scale))
    return out


def obs(lms, label="Left", conf=0.9):
    return HandObs(lms, label, conf)


def true_label(side, conf=0.9):
    """What MediaPipe reports for an UNMIRRORED frame when it is right: user's right -> 'Left'."""
    return "Left" if side == "right" else "Right"


def cfg(**over):
    c = config.load("/nonexistent")
    c.update(over)
    return c
