#!/usr/bin/env python3
"""gestyq - menu-bar app entry point. AppKit on the main thread; the vision thread owns the camera,
MediaPipe and the gesture engine and posts Quartz events itself."""
import atexit
import os
import signal
import sys
import time

import objc
from AppKit import (NSImage, NSApplication, NSApplicationActivationPolicyAccessory, NSApplicationDidChangeScreenParametersNotification,
                    NSMenu, NSMenuItem, NSObject, NSScreen)
from Foundation import NSNotificationCenter, NSRunLoop, NSRunLoopCommonModes, NSTimer

import actions as actions_mod
import bindings
import cameras
import config
import login
from state import SharedState
from ui.gadget import GadgetController
from ui.menubar import MenuBar, dock_icon
from ui.window import MainWindowController
from vision import VisionThread

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.environ.get("GESTYQ_APP")          # set by the gestyq.app launcher
BACKGROUND = "--background" in sys.argv    # the login item: stay in the menu bar, no window


def request_camera_access():
    try:
        import AVFoundation as AV
        AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AV.AVMediaTypeVideo, lambda granted: None)
    except Exception as e:
        print("camera permission request failed:", e)


class Model:
    """What the UI talks to. Lives on the main thread; the vision thread only reads cfg values."""

    def __init__(self):
        self.cfg = config.load()
        self.cfg["launch_at_login"] = login.is_enabled()
        if self.cfg["launch_at_login"] and APP:
            login.set_enabled(True, HERE, app=APP)      # repoint an older run.sh login item at the app
        self.state = SharedState()
        self.actions = actions_mod.Actions(self.cfg, self.state)
        self.vision = VisionThread(self.state, self.cfg, self.actions)
        self.saver = config.Debounced(lambda: config.save(self.cfg), 0.3)
        self.trusted = actions_mod.is_trusted()
        self.on_change = lambda: None
        self.open_window = lambda: None         # set by the delegate
        self.quitting = False

    def display_count(self):
        return self.actions.desktop.count()

    def display_label(self):
        n = self.display_count()
        return f"{n} display" + ("" if n == 1 else "s")

    def set(self, key, value):
        self.cfg[key] = value
        self.saver.poke()
        if key == "launch_at_login":
            login.set_enabled(bool(value), HERE, app=APP)
        self.on_change()

    # -- window / bindings
    def set_window_open(self, open_):
        self.vision.set_window_open(open_)      # open: the live view is published while the camera runs (never starts it)

    def set_recording(self, on):
        self.vision.set_recording(on)

    def set_binding(self, gesture, action):
        self.cfg.setdefault("bindings", {})[gesture] = action
        self.saver.poke()
        self.on_change()

    def reset_bindings(self):
        self.cfg["bindings"] = dict(bindings.DEFAULT_BINDINGS)
        self.saver.poke()
        self.on_change()

    def set_enabled(self, on):
        self.vision.set_enabled(on)        # OFF releases the mouse button and the camera device
        self.on_change()

    # -- accessibility
    def grant_access(self):
        actions_mod.request_trust()

    def refresh_trust(self):
        t = actions_mod.is_trusted()
        if t != self.trusted:
            self.trusted = t
            self.on_change()

    # -- camera (chosen by AVCaptureDevice uniqueID, see cameras.py)
    def camera_devices(self):
        return cameras.list_devices()

    def camera_choice(self):
        """-> (saved uid or None for auto, device in use or None, note)."""
        snap = self.state.get()
        devs = cameras.list_devices()
        dev, note = cameras.choose(devs, self.cfg)
        if snap["camera_uid"]:
            dev = next((d for d in devs if d.uid == snap["camera_uid"]), dev)
            note = snap["camera_note"]
        return self.cfg.get("camera_id"), dev, note

    def camera_label(self):
        _, dev, _ = self.camera_choice()
        return dev.name.lower() if dev else "no camera"

    def set_camera(self, device):
        """device: cameras.Device, or None for auto (the built-in camera). The saved choice survives the
        camera being away; only this call changes it."""
        self.cfg["camera_id"] = device.uid if device else None
        self.cfg["camera_name"] = device.name if device else None
        self.saver.poke()
        self.vision.reload_camera()
        self.on_change()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.vision.stop()
        self.vision.join(timeout=3)
        self.actions.release_all()
        self.saver.flush()
        config.save(self.cfg)
        NSApplication.sharedApplication().terminate_(None)


class _Menu(NSObject):
    def quit_(self, sender):
        self.model.quit()


class Delegate(NSObject):
    def applicationDidFinishLaunching_(self, note):
        self.model = Model()
        m = self.model
        request_camera_access()
        m.vision.start()
        self.gadget = GadgetController(m)
        self.menubar = MenuBar(m)
        self.window = MainWindowController.alloc().initWithModel_(m)
        m.open_window = self.show_window
        m.on_change = self.changed
        self.build_menu()
        self.gadget.apply()
        self.last_pulse = 0
        self.last_screen = self.last_trust = 0.0
        self.last_snap = None
        t = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(1 / 30.0, self, "tick:", None, True)
        NSRunLoop.currentRunLoop().addTimer_forMode_(t, NSRunLoopCommonModes)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "screensChanged:", NSApplicationDidChangeScreenParametersNotification, None)
        signal.signal(signal.SIGTERM, lambda *a: m.quit())
        signal.signal(signal.SIGINT, lambda *a: m.quit())
        atexit.register(m.actions.release_all)
        self.publish_screen()
        NSApplication.sharedApplication().setApplicationIconImage_(dock_icon())
        if not BACKGROUND:
            self.show_window()

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, has_visible):
        self.show_window()
        return True

    @objc.python_method
    def show_window(self):
        if self.menubar.is_open:
            self.menubar.popover.performClose_(None)
        self.window.show()

    @objc.python_method
    def build_menu(self):
        """Minimal main menu so cmd-q and cmd-w work while the window is up."""
        self.menu_target = _Menu.alloc().init()
        self.menu_target.model = self.model
        bar = NSMenu.alloc().init()
        for title, items in (("gestyq", [("quit gestyq", "quit:", "q", self.menu_target)]),
                             ("window", [("close", "performClose:", "w", None)])):
            top = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            sub = NSMenu.alloc().initWithTitle_(title)
            for t, action, key, target in items:
                it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(t, action, key)
                if target is not None:
                    it.setTarget_(target)
                sub.addItem_(it)
            top.setSubmenu_(sub)
            bar.addItem_(top)
        NSApplication.sharedApplication().setMainMenu_(bar)

    def applicationWillTerminate_(self, note):
        self.model.vision.set_enabled(False)
        self.model.actions.release_all()

    def screensChanged_(self, note):
        self.gadget.reclamp()
        self.model.actions.refresh_displays()
        self.publish_screen()
        self.changed()

    def changed(self):
        self.gadget.apply()
        if self.menubar.is_open:
            self.menubar.refresh()

    def publish_screen(self):
        """Cocoa geometry of every screen, for tiling on the display that holds the front window."""
        scr = list(NSScreen.screens())
        rect = lambda r: (r.origin.x, r.origin.y, r.size.width, r.size.height)
        main = NSScreen.mainScreen()
        self.model.state.update(screen={
            "primary_h": scr[0].frame().size.height,
            "screens": [{"frame": rect(s.frame()), "visible": rect(s.visibleFrame())} for s in scr],
            "main": next((i for i, s in enumerate(scr) if main is not None and s == main), 0)})

    def tick_(self, timer):
        now = time.monotonic()
        m = self.model
        if now - self.last_screen > 1.0:
            self.last_screen = now
            m.actions.refresh_displays()                # hot-plug / arrangement / resolution, even without a notification
            self.publish_screen()
        if now - self.last_trust > 1.0:                 # poll accessibility every second
            self.last_trust = now
            m.refresh_trust()
        snap = m.state.get()
        on = snap["enabled"]
        pulsed = snap["pulse_n"] != self.last_pulse
        self.last_pulse = snap["pulse_n"]
        self.gadget.update(on, snap["caption"] if on else "paused", pulsed)
        self.menubar.set_enabled(on)
        key = (on, m.trusted, m.display_count())
        if key != self.last_snap:
            self.last_snap = key
            if self.menubar.is_open:
                self.menubar.refresh()


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    # dock / app-switcher icon at runtime, so a new icon never needs a re-signed bundle
    icon = NSImage.alloc().initWithContentsOfFile_(os.path.join(HERE, "Resources", "AppIcon.icns"))
    if icon is not None:
        app.setApplicationIconImage_(icon)
    d = Delegate.alloc().init()
    app.setDelegate_(d)
    app.run()


if __name__ == "__main__":
    main()
