#!/usr/bin/env python3
"""gestyq gadget helper: keeps the desktop gadget on screen while gestyq.app is NOT running (a LaunchAgent starts
this, see afterquit.py). AppKit only: no camera, no MediaPipe, no events, no Accessibility. It is idle between
the running-apps list changing (no timers). Click = launch gestyq switched on."""
import argparse
import os
import subprocess
import sys

from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSApplicationDidChangeScreenParametersNotification,
                    NSObject, NSRunningApplication, NSWorkspace)
from Foundation import NSKeyValueObservingOptionNew

import afterquit
import config
from ui.gadget import GadgetController

HERE = os.path.dirname(os.path.abspath(__file__))


def log(*a):
    print(*a, flush=True)


def app_running():
    return len(NSRunningApplication.runningApplicationsWithBundleIdentifier_(afterquit.BUNDLE_ID)) > 0


class HelperModel:
    """Just enough of the app's Model for GadgetController. Only gadget_origin (a drag) and gadget_after_quit
    (hide gadget) are ever written, each onto a fresh copy of the file."""

    def __init__(self):
        self.cfg = config.load()

    def reload(self):
        self.cfg = config.load()

    def set(self, key, value):
        self.cfg[key] = value
        fresh = config.load()
        fresh[key] = value
        config.save(fresh)


class Gadget(GadgetController):
    def __init__(self, model, app, hide, quit_):
        super().__init__(model)
        self.app, self.hide, self.quit_ = app, hide, quit_

    def click(self):
        self.start()

    def start(self):
        # motion: tap 80 · pulse answers the click in the same frame; the caption says what happens next
        self.update(False, "starting", True)
        log("start gestyq")
        subprocess.Popen(["/usr/bin/open", "-a", self.app, "--args", "--on", "--background"])

    def entries(self):
        return [("start gestyq", False, self.start), ("hide gadget", False, self.hide), ("quit gadget", False, self.quit_)]


class Delegate(NSObject):
    def applicationDidFinishLaunching_(self, note):
        self.model = HelperModel()
        if not self.model.cfg["gadget_after_quit"]:
            log("gadget_after_quit is off: exiting")
            os._exit(0)
        self.gadget = Gadget(self.model, self.app_path, self.hide_gadget, self.quit_gadget)
        # KVO, not the didLaunch / didTerminate notifications: those are never posted for accessory (menu bar) apps
        NSWorkspace.sharedWorkspace().addObserver_forKeyPath_options_context_(
            self, "runningApplications", NSKeyValueObservingOptionNew, None)
        from Foundation import NSNotificationCenter
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "screensChanged:", NSApplicationDidChangeScreenParametersNotification, None)
        self.shown, self.running = None, app_running()
        self.evaluate()

    def observeValueForKeyPath_ofObject_change_context_(self, key, obj, change, ctx):
        running = app_running()
        if running != self.running:
            self.running = running
            self.evaluate()

    def screensChanged_(self, note):
        self.gadget.reclamp()

    def evaluate(self):
        self.model.reload()
        cfg = self.model.cfg
        show = afterquit.should_show(app_running(), cfg["desktop_gadget"], cfg["gadget_after_quit"])
        if show:
            self.gadget.apply()
            self.gadget.update(False, "click to start", False)
        elif self.gadget.panel is not None:
            self.gadget.panel.orderOut_(None)
        if show != self.shown:
            self.shown = show
            log("gadget shown" if show else "gadget hidden (gestyq is running)" if app_running() else "gadget hidden")

    def hide_gadget(self):
        log("hide gadget: after-quit gadget off")
        self.model.set("gadget_after_quit", False)
        afterquit.sync(False, HERE, self.app_path)          # stops this helper and removes the LaunchAgent
        os._exit(0)

    def quit_gadget(self):
        log("quit gadget")
        NSApplication.sharedApplication().terminate_(None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=afterquit.DEFAULT_APP)
    args = ap.parse_args()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    d = Delegate.alloc().init()
    d.app_path = args.app
    app.setDelegate_(d)
    app.run()


if __name__ == "__main__":
    main()
