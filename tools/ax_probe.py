"""Phase-0 probe for air-writing: prints what the Accessibility API reports for the focused element, twice a second.

    python3 tools/ax_probe.py [--once]

Click into a text field in Notes, Safari's address bar, Chrome, Slack, Terminal, Spotlight, a password field and
watch the role / subrole / settable / range / frame and what the canvas would do (text, secure, none). The process
running this (Terminal, iTerm, ...) must have Accessibility access, else every read fails ("not trusted").
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from axreader import FocusReader   # noqa: E402


def main():
    r = FocusReader(own_pid=-1)
    if not r.available():
        print("not trusted: give this terminal accessibility access (system settings > privacy & security)")
    while True:
        try:
            el = r._focused()
        except Exception as e:
            el, err = None, e
        if el is None:
            print(time.strftime("%H:%M:%S"), "no focused element (or the call failed)", flush=True)
        else:
            f = r.read()
            role, sub = r._attr(el, "AXRole"), r._attr(el, "AXSubrole")
            print(time.strftime("%H:%M:%S"), f"role={role} subrole={sub} kind={f.kind if f else None} "
                  f"frame={tuple(round(v) for v in f.frame) if f else None} pid={f.pid if f else None}", flush=True)
        if "--once" in sys.argv:
            return
        time.sleep(0.5)


if __name__ == "__main__":
    main()
