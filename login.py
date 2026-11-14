"""LaunchAgent for 'launch at login' (pure Python; paths are parameters)."""
import os
import plistlib

LABEL = "com.gestyq.app"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")


def plist_dict(here, app=None):
    """Opens gestyq.app when running from the bundle (so permissions stay with "gestyq"), else run.sh."""
    args = ["/usr/bin/open", "-a", app] if app else ["/bin/bash", os.path.join(here, "run.sh")]
    return {"Label": LABEL, "ProgramArguments": args, "WorkingDirectory": here, "RunAtLoad": True,
            "KeepAlive": False}


def is_enabled(path=PLIST):
    return os.path.exists(path)


def set_enabled(on, here, path=PLIST, app=None):
    if on:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            plistlib.dump(plist_dict(here, app), f)
    elif os.path.exists(path):
        os.remove(path)
