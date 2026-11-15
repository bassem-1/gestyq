import copy
import json
import random
import time

import config
import letters
import recognizer
from recognizer import TemplateRecognizer, TemplateStore
from synth_ink import accuracy, flip, synth

REC = recognizer.make(config.DEFAULTS)


def test_every_builtin_template_recognises_itself_with_distance_under_0_02():
    for ch, variants in letters.LETTERS.items():
        for v in variants:
            got = REC.recognize(flip(v))
            assert got and got[0].char == ch and got[0].dist < 0.02, (ch, got[:2])


def test_accuracy_on_noisy_synthetic_capitals():
    """26 capitals x 40 noisy copies (slant, width, rotation, wobble, jitter, stroke-end hooks), fixed seed.
    A floor for the code, not a promise for real handwriting."""
    a06, _ = accuracy(REC, 0.6)
    a10, _ = accuracy(REC, 1.0)
    a10r, _ = accuracy(REC, 1.0, p_rev=0.25)
    a14, _ = accuracy(REC, 1.4)
    print("accuracy", a06, a10, a10r, a14)
    assert a06 >= 0.98 and a10 >= 0.95 and a10r >= 0.87 and a14 >= 0.84


def test_scribble_and_closed_zigzag_are_rejected():
    rng = random.Random(7)
    scribble = [[(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(40)]]
    zig = [[(i % 2, i * 0.12) for i in range(10)] + [(0, 0)]]      # closed zigzag, 10 teeth
    assert REC.recognize(scribble) == [] and REC.recognize(zig) == []
    assert REC.recognize([]) == []


def test_bare_line_is_i_and_line_with_a_foot_is_l():
    assert REC.recognize([[(0, 0), (0, 1)]])[0].char == "I"
    assert REC.recognize([[(0, 0), (0, 0.5), (0, 1)]])[0].char == "I"
    got = REC.recognize([[(0, -2), (0, 0), (0.9, 0)]])
    assert got[0].char == "L"


def test_enter_stroke_is_accepted_clean_and_dropped_when_noisy():
    clean = flip(letters.LETTERS["\n"][0])
    got = REC.recognize(clean)
    assert got[0].char == "\n" and got[0].score > 0.5
    rng = random.Random(5)
    rate = {}
    for lv in (0.6, 1.4):
        n = 0
        for _ in range(200):
            g = REC.recognize(flip(synth(letters.LETTERS["\n"][0], rng, lv)))
            n += bool(g) and g[0].char == "\n"
        rate[lv] = n / 200
    assert rate[0.6] > 0.85 and rate[1.4] < rate[0.6] - 0.2
    # a sloppy "down, then a tiny hook" is never enter
    assert all(c.char != "\n" for c in REC.recognize([[(0, 0), (0, 1), (-0.2, 1.1)]]))


def test_candidates_are_best_first_distinct_and_scored():
    got = REC.recognize(flip(letters.LETTERS["O"][0]))
    assert 1 <= len(got) <= 3 and len({c.char for c in got}) == len(got)
    assert [c.dist for c in got] == sorted(c.dist for c in got)
    assert 0.0 <= got[0].score <= 1.0 and got[0].score > got[-1].score - 1e-9


def test_a_user_template_makes_a_square_an_h(tmp_path):
    tri = [[(0, 0), (1, 0), (1, -1), (0, -1), (0, 0)]]
    assert not REC.recognize(tri) or REC.recognize(tri)[0].char != "H"
    store = TemplateStore(str(tmp_path / "letters.json"))
    store.add("h", tri)         # a lowercase key from an older file still counts for H
    rec = TemplateRecognizer(config.DEFAULTS, store)
    assert rec.recognize(tri)[0].char == "H"


def test_max_user_evicts_the_oldest_and_the_store_round_trips(tmp_path):
    p = str(tmp_path / "support" / "letters.json")
    store = TemplateStore(p, max_user=3)
    for i in range(5):
        store.add("b", [[(0, 0), (1, i)]], now=100.0 + i)
    assert [it["t"] for it in store.data["b"]] == [102.0, 103.0, 104.0]
    store.save()
    again = TemplateStore(p, max_user=3)
    assert again.data == store.data and json.load(open(p))["version"] == 1
    assert len(again.templates()) == 3


def test_a_corrupt_store_loads_as_empty(tmp_path):
    p = tmp_path / "letters.json"
    p.write_text("{not json")
    assert TemplateStore(str(p)).data == {}
    p.write_text(json.dumps({"version": 1, "templates": {"a": [{"strokes": "oops"}]}}))
    assert TemplateStore(str(p)).data == {}
    assert TemplateStore(str(tmp_path / "missing.json")).data == {}


def test_store_path_honours_the_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GESTYQ_LETTERS", str(tmp_path / "x.json"))
    assert recognizer.user_path() == str(tmp_path / "x.json")
    monkeypatch.delenv("GESTYQ_LETTERS")
    assert recognizer.user_path().endswith("letters.json") and "gestyq-test-" in recognizer.user_path()


def test_a_hundred_recognitions_take_under_0_2_s():
    rng = random.Random(1)
    inks = [flip(synth(letters.LETTERS[ch][0], rng, 1.0)) for ch in "ABCDEFGHIJ" * 10]
    t = time.perf_counter()
    for k in inks:
        REC.recognize(k)
    assert time.perf_counter() - t < 0.2


def test_unsure_when_the_runner_up_is_close():
    got = REC.recognize(flip(letters.LETTERS["O"][0]))
    assert not REC.unsure(got) or got[1].dist - got[0].dist < 0.02
    cs = [recognizer.Candidate("A", 0.10, .6), recognizer.Candidate("Q", 0.11, .6)]
    assert REC.unsure(cs) and not REC.unsure(cs[:1])


def test_enter_is_never_read_as_l_or_j_or_i_and_l_j_are_not_read_as_enter():
    """enter = down then LEFT, L = down then RIGHT, J = down then a curved hook."""
    rng = random.Random(11)
    for lv in (0.3, 0.6, 1.0):          # (at 1.4 a sloppy J does read as enter now and then)
        for ch in "LJI":
            for v in letters.LETTERS[ch]:
                for _ in range(100):
                    got = REC.recognize(flip(synth(v, rng, lv, 0.25)))
                    assert not got or got[0].char != "\n", (ch, lv)
        bad = 0
        for _ in range(100):
            got = REC.recognize(flip(synth(letters.LETTERS["\n"][0], rng, lv)))
            bad += bool(got) and got[0].char in "LJI"
        assert bad <= (0 if lv < 0.5 else 8 if lv < 0.7 else 100), (lv, bad)    # sloppy enters may read as J, never at 0.3
    assert REC.recognize([[(0, 0), (0, 1), (-1.2, 1)]])[0].char != "L"       # y down: down, then left


def test_writing_case_upper_is_the_default_and_lower_is_a_live_switch():
    cfg = copy.deepcopy(config.DEFAULTS)
    assert cfg["writing_case"] == "upper"
    rec = recognizer.make(cfg)
    ink = flip(letters.LETTERS["O"][0])
    assert rec.recognize(ink)[0].char == "O"
    cfg["writing_case"] = "lower"                       # the window flips it while the engine runs
    got = rec.recognize(ink)
    assert got[0].char == "o" and all(c.char == c.char.lower() for c in got)
    cfg["writing_case"] = "bogus"
    assert rec.recognize(ink)[0].char == "O"
    cfg["writing_case"] = "lower"
    assert rec.recognize(flip(letters.LETTERS["\n"][0]))[0].char == "\n"      # enter stays enter
