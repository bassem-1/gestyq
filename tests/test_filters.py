import math
import random

from filters import DeadZone, MajorityVote, OneEuro, OneEuro2D, RingBuffer


def run(f, sig, hz=30):
    return [f(v, i / hz) for i, v in enumerate(sig)]


def test_one_euro_passes_constant():
    out = run(OneEuro(), [5.0] * 30)
    assert all(abs(v - 5.0) < 1e-9 for v in out)


def test_one_euro_smooths_slow_noise():
    random.seed(1)
    sig = [100 + random.gauss(0, 2.0) for _ in range(300)]
    out = run(OneEuro(min_cutoff=1.0, beta=0.007), sig)
    def std(v):
        m = sum(v) / len(v)
        return math.sqrt(sum((a - m) ** 2 for a in v) / len(v))
    assert std(out[30:]) < 0.5 * std(sig[30:])


def test_one_euro_tracks_fast_motion_with_small_lag():
    ramp = [i * 30.0 for i in range(60)]        # 900 units/s
    out = run(OneEuro(min_cutoff=1.0, beta=0.007), ramp)
    assert ramp[-1] - out[-1] < 70              # lag stays ~2 frames, far below the slow-mode lag
    slow = run(OneEuro(min_cutoff=1.0, beta=0.0), ramp)
    assert ramp[-1] - slow[-1] > 3 * (ramp[-1] - out[-1])


def test_one_euro_2d_and_reset_on_gap():
    f = OneEuro2D(1.0, 0.007)
    f(0, 0, 0.0)
    assert f(10, 10, 5.0) == (10, 10)           # long gap re-initialises


def test_deadzone_holds_then_trails():
    d = DeadZone(2.0)
    assert d(10, 10) == (10, 10)
    assert d(11, 10) == (10, 10)                # inside zone
    x, y = d(15, 10)
    assert abs(x - 13) < 1e-9 and y == 10       # trails at exactly radius


def test_majority_vote():
    v = MajorityVote(5)
    for l in "aabab":
        out = v.push(l)
    assert out == "a"
    for l in "bb":
        out = v.push(l)
    assert out == "b"
    assert MajorityVote(2).push("x") == "x"


def test_ring_buffer_lookup():
    r = RingBuffer(0.3)
    for i in range(20):
        r.push(i * 0.033, i)
    assert r.at(0.033 * 10 + 0.001) == 10
    assert r.at(-5) == r.items[0][1]
    assert len(r.items) <= 11
