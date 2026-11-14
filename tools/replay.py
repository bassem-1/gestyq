"""Replay a recorded landmark session through a fresh GestureEngine, for tuning with real data.

    python3 tools/replay.py <file.jsonl> [--quiet] [--events]

Input (written by the app's record button, one line per camera frame, unmirrored MediaPipe coords):
    {"t": <monotonic s>, "aspect": <w/h>, "hands": [{"lms": [[x, y, z] x 21], "label": "Left"|"Right", "conf": f}]}
Output: a per-frame, per-hand table (t, role, raw pose, voted pose, finger states i/m/r/p/thumb with
e = extended, c = curled; finger reach i/m/r/p; thumb-index pinch ratio; pinch raw/confirmed) and a summary of
the emitted events by kind / gesture id. Settings come from config.load() (the user's file).
Pure Python: no camera, no mediapipe.
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config                      # noqa: E402
from gestures import GestureEngine  # noqa: E402
from tracking import HandObs        # noqa: E402


def load_frames(path):
    frames = []
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                frames.append(json.loads(line))
            except ValueError:
                print(f"{path}:{n}: skipped (bad json)", file=sys.stderr)
    return frames


def _fingers(d):
    f = d["fingers"]
    return "".join(f[k][0] if k in f else "?" for k in ("index", "middle", "ring", "pinky", "thumb"))


def event_name(e):
    return f"gesture:{e.value['id']}" if e.kind == "gesture" else e.kind


def replay(frames, cfg=None, out=None, events=False):
    """Run frames through a fresh engine. Returns {"frames": n, "events": Counter, "log": [(t, Event)]}."""
    cfg = cfg or config.load()
    eng = GestureEngine(cfg)
    counts, log = Counter(), []
    out = out or (lambda s: None)
    for fr in frames:
        t = fr["t"]
        eng.aspect = fr.get("aspect") or eng.aspect
        obs = [HandObs([tuple(p) for p in h["lms"]], h.get("label", ""), h.get("conf", 0.0))
               for h in fr.get("hands", [])]
        ev = eng.update(obs, t)
        row = []
        for d in eng.debug:
            r = d["reach"]
            row.append(f"{d['role'][:1].upper()} raw={d['pose_raw']:<6} vote={d['pose']:<6} f={_fingers(d)} "
                       f"reach={'/'.join(f'{r[k]:.2f}' for k in ('index', 'middle', 'ring', 'pinky'))} "
                       f"pinch={d['ratio']:.2f} {'R' if d['pinch_raw'] else '-'}{'C' if d['pinch'] else '-'}")
        evs = " ".join(f"[{event_name(e)}{'=' + str(e.value) if e.kind == 'scroll' else ''}]"
                       for e in ev if e.kind not in ("move", "drag_move"))
        out(f"{t:9.3f}  " + (" | ".join(row) if row else "no hands") + ("   " + evs if evs else ""))
        for e in ev:
            counts[event_name(e)] += 1
            log.append((t, e))
    return {"frames": len(frames), "events": counts, "log": log,
            "duration": (frames[-1]["t"] - frames[0]["t"]) if frames else 0.0}


def format_summary(res):
    lines = [f"{res['frames']} frames, {res['duration']:.1f} s", "events:"]
    lines += [f"  {k:<24}{v}" for k, v in sorted(res["events"].items())] or ["  (none)"]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("--quiet", action="store_true", help="summary only, no per-frame table")
    args = ap.parse_args(argv)
    res = replay(load_frames(args.file), out=None if args.quiet else print)
    print(format_summary(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
