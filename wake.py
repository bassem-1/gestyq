"""Wake a sleeping display from hand activity (pure Python; the Quartz / IOKit calls live in actions.py).

A trackpad touch wakes the screen; so does a moving hand (or any gesture) while gestyq is on, at most once per
WAKE_GAP s. While the display is asleep gestures do not execute (they would act blind): they only wake."""
import math

POLL = 0.5          # s between display-asleep queries
WAKE_GAP = 2.0      # s between wake requests
MOVE_EPS = 0.003    # frame widths a palm must travel between two frames to count as moving (landmark jitter is ~0.001)
SLEEP_GRACE = 8.0   # s after a display sleep the user asked for during which hand movement does not wake it


def hands_moved(prev, cur, eps=MOVE_EPS):
    """prev / cur: palm anchors [(x, y)] of the last and this frame. True when any hand moved by >= eps from the
    nearest anchor of the previous frame (a hand that just appeared counts as movement)."""
    if not cur:
        return False
    if not prev:
        return True
    return any(min(math.hypot(c[0] - p[0], c[1] - p[1]) for p in prev) >= eps for c in cur)


def should_wake(asleep, enabled, moving, fired, now, last_wake, gap=WAKE_GAP):
    return bool(asleep and enabled and (moving or fired) and now - last_wake >= gap)
