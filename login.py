"""LaunchAgent for 'launch at login' (pure Python; paths are parameters)."""
import os
import plistlib

LABEL = "com.gestyq.app"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def plist_dict(here):
    return {"Label": LABEL, "ProgramArguments": ["/bin/bash", os.path.join(here, "run.sh")],
            "WorkingDirectory": here, "RunAtLoad": True, "KeepAlive": False}


def is_enabled(path=PLIST):
    return os.path.exists(path)


def set_enabled(on, here, path=PLIST):
    if on:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            plistlib.dump(plist_dict(here), f)
    elif os.path.exists(path):
        os.remove(path)
