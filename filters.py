"""Pure signal-processing primitives: One Euro filter, dead-zone, majority vote, ring buffer."""
import math
from collections import Counter, deque


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def _alpha(cutoff, dt):
    tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
    return 1.0 / (1.0 + tau / dt)


class OneEuro:
    """Casiez et al. 2012. Smooth when slow (min_cutoff), responsive when fast (beta)."""

    def __init__(self, min_cutoff=1.0, beta=0.007, d_cutoff=1.0, max_gap=1.0):
        self.min_cutoff, self.beta, self.d_cutoff, self.max_gap = min_cutoff, beta, d_cutoff, max_gap
        self.reset()

    def reset(self):
        self.x = None
        self.dx = 0.0
        self.t = None

    def __call__(self, x, t):
        if self.x is None or t - self.t > self.max_gap:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = t - self.t
        if dt <= 1e-4:
            return self.x
        dx = (x - self.x) / dt
        self.dx += _alpha(self.d_cutoff, dt) * (dx - self.dx)
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        self.x += _alpha(cutoff, dt) * (x - self.x)
        self.t = t
        return self.x


class OneEuro2D:
    """One Euro on a 2D point; the cutoff is driven by the speed magnitude so both axes lag equally."""

    def __init__(self, min_cutoff=1.0, beta=0.007, d_cutoff=1.0, max_gap=1.0):
        self.min_cutoff, self.beta, self.d_cutoff, self.max_gap = min_cutoff, beta, d_cutoff, max_gap
        self.reset()

    def reset(self):
        self.p = None
        self.d = (0.0, 0.0)
        self.t = None

    def set_params(self, min_cutoff, beta):
        self.min_cutoff, self.beta = min_cutoff, beta

    def __call__(self, x, y, t):
        if self.p is None or t - self.t > self.max_gap:
            self.p, self.d, self.t = (x, y), (0.0, 0.0), t
            return self.p
        dt = t - self.t
        if dt <= 1e-4:
            return self.p
        a_d = _alpha(self.d_cutoff, dt)
        dx = self.d[0] + a_d * ((x - self.p[0]) / dt - self.d[0])
        dy = self.d[1] + a_d * ((y - self.p[1]) / dt - self.d[1])
        self.d = (dx, dy)
        a = _alpha(self.min_cutoff + self.beta * math.hypot(dx, dy), dt)
        self.p = (self.p[0] + a * (x - self.p[0]), self.p[1] + a * (y - self.p[1]))
        self.t = t
        return self.p


class DeadZone:
    """Output only moves once the input leaves a circle of `radius` around it; then it trails
    the input at exactly `radius` (no jump when the zone is left)."""

    def __init__(self, radius):
        self.radius = radius
        self.out = None

    def reset(self):
        self.out = None

    def __call__(self, x, y):
        if self.out is None:
            self.out = (x, y)
            return self.out
        dx, dy = x - self.out[0], y - self.out[1]
        d = math.hypot(dx, dy)
        if d > self.radius:
            k = (d - self.radius) / d
            self.out = (self.out[0] + dx * k, self.out[1] + dy * k)
        return self.out


class MajorityVote:
    """Most common label among the last n; ties go to the most recent of the tied labels."""

    def __init__(self, n=5):
        self.buf = deque(maxlen=n)

    def reset(self):
        self.buf.clear()

    def push(self, label):
        self.buf.append(label)
        counts = Counter(self.buf)
        best = max(counts.values())
        for l in reversed(self.buf):
            if counts[l] == best:
                return l


class RingBuffer:
    """Time-windowed (t, value) history."""

    def __init__(self, window=0.3):
        self.window = window
        self.items = deque()

    def clear(self):
        self.items.clear()

    def push(self, t, v):
        self.items.append((t, v))
        while self.items and t - self.items[0][0] > self.window:
            self.items.popleft()

    def at(self, t):
        """Value of the newest sample taken at or before t (oldest sample if none is that old)."""
        if not self.items:
            return None
        best = self.items[0][1]
        for ts, v in self.items:
            if ts <= t:
                best = v
            else:
                break
        return best
