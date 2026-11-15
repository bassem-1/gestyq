"""The desktop gadget after gestyq quits: a LaunchAgent that runs gadget_helper.py (pure Python; paths and the
launchctl runner are parameters so it is testable)."""
import os
import plistlib
import subprocess
import sys

LABEL = "com.gestyq.gadget"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
LOG = os.path.expanduser("~/Library/Logs/gestyq-gadget.log")
DEFAULT_APP = "/Applications/gestyq.app"
BUNDLE_ID = "io.github.bassem-1.gestyq"


def parse_argv(argv):
    """-> (on, background): `--on` = enable on launch (the helper's click), `--background` = no window."""
    return "--on" in argv, "--background" in argv


def should_show(app_running, desktop_gadget, after_quit):
    """The helper's gadget shows only while gestyq is not running, the gadget is on and the setting is on."""
    return bool(not app_running and desktop_gadget and after_quit)


def python_for(app=DEFAULT_APP):
    """The app's own interpreter (Resources/python_home -> bin/python3), else the current one."""
    try:
        with open(os.path.join(app, "Contents", "Resources", "python_home")) as f:
            py = os.path.join(f.read().strip(), "bin", "python3")
        if os.path.exists(py):
            return py
    except OSError:
        pass
    return sys.executable


def plist_dict(here, python, app=DEFAULT_APP):
    # KeepAlive only after a crash: "quit gadget" (exit 0) stays quit until the next launch of gestyq or login
    return {"Label": LABEL, "ProgramArguments": [python, os.path.join(here, "gadget_helper.py"), "--app", app],
            "WorkingDirectory": here, "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
            "ProcessType": "Interactive", "StandardOutPath": LOG, "StandardErrorPath": LOG,
            "EnvironmentVariables": {"PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"}}


def is_installed(path=PLIST):
    return os.path.exists(path)


def write_plist(on, here, python, app=DEFAULT_APP, path=PLIST):
    """File only. Returns True when the file changed."""
    if on:
        d = plist_dict(here, python, app)
        try:
            with open(path, "rb") as f:
                if plistlib.load(f) == d:
                    return False
        except (OSError, ValueError):
            pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            plistlib.dump(d, f)
        return True
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# -- launchctl
def _run(args):
    try:
        return subprocess.run(["/bin/launchctl", *args], capture_output=True, timeout=3).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def domain():
    return f"gui/{os.getuid()}"


def is_loaded(run=_run):
    return run(["print", f"{domain()}/{LABEL}"]) == 0


def unload(run=_run):
    if is_loaded(run):
        run(["bootout", f"{domain()}/{LABEL}"])


def sync(on, here, app=DEFAULT_APP, path=PLIST, run=_run, python=None):
    """The setting changed (or the app started): on = write the plist (the agent loads at login or when gestyq
    quits, never while it runs); off = stop the helper and delete the plist."""
    if on:
        write_plist(True, here, python or python_for(app), app, path)
    else:
        unload(run)
        write_plist(False, here, "", app, path)


def on_quit(on, path=PLIST, run=_run):
    """gestyq is quitting: make sure the helper is loaded and running so the gadget stays on the desktop."""
    if not on or not os.path.exists(path):
        return False
    if not is_loaded(run):
        run(["bootstrap", domain(), path])
    run(["kickstart", f"{domain()}/{LABEL}"])       # no -k: starts it if it is idle, leaves a running one alone
    return True
