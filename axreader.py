"""Reads the focused UI element through the Accessibility API (macOS, main thread) -> textfocus.Focus.
Fails soft: not trusted, a hung app or an element without the attributes gives None."""
import os
import time

from textfocus import Focus, classify


class FocusReader:
    """Reads the focused UI element through the Accessibility API (main thread). Fails soft: untrusted, a hung app
    or an element without the attributes -> read() returns None."""

    SLOW = 0.05

    def __init__(self, own_pid=None):
        self.own_pid = own_pid if own_pid is not None else os.getpid()
        self.sys = None
        self.prev, self.counter = None, 0
        self.slow_until, self.slow_n = 0.0, 0

    def available(self):
        try:
            from ApplicationServices import AXIsProcessTrusted
            return bool(AXIsProcessTrusted())
        except Exception:
            return False

    def _attr(self, el, name):
        from ApplicationServices import AXUIElementCopyAttributeValue
        err, val = AXUIElementCopyAttributeValue(el, name, None)
        return val if err == 0 else None

    def _focused(self):
        from ApplicationServices import (AXUIElementCopyAttributeValue, AXUIElementCreateApplication,
                                         AXUIElementCreateSystemWide, AXUIElementSetMessagingTimeout,
                                         kAXFocusedUIElementAttribute)
        if self.sys is None:
            self.sys = AXUIElementCreateSystemWide()
            AXUIElementSetMessagingTimeout(self.sys, 0.08)
        err, el = AXUIElementCopyAttributeValue(self.sys, kAXFocusedUIElementAttribute, None)
        if err == 0 and el is not None:
            return el
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        a = AXUIElementCreateApplication(app.processIdentifier())
        AXUIElementSetMessagingTimeout(a, 0.08)
        err, el = AXUIElementCopyAttributeValue(a, kAXFocusedUIElementAttribute, None)
        return el if err == 0 else None

    def read(self, now=None):
        """-> Focus | None. Backs off to one read a second for 10 s after two slow reads in a row."""
        now = time.monotonic() if now is None else now
        if now < self.slow_until:
            return None
        t0 = time.monotonic()
        try:
            f = self._read()
        except Exception:
            f = None
        if time.monotonic() - t0 > self.SLOW:
            self.slow_n += 1
            if self.slow_n >= 2:
                self.slow_until, self.slow_n = now + 10.0, 0
        else:
            self.slow_n = 0
        return f

    def _read(self):
        from ApplicationServices import (AXUIElementGetPid, AXUIElementIsAttributeSettable, AXValueGetValue,
                                         kAXValueCGPointType, kAXValueCGSizeType)
        from CoreFoundation import CFEqual
        el = self._focused()
        if el is None:
            return None
        err, pid = AXUIElementGetPid(el, None)
        if err != 0:
            return None
        role, sub = self._attr(el, "AXRole"), self._attr(el, "AXSubrole")
        err, settable = AXUIElementIsAttributeSettable(el, "AXValue", None)
        settable = bool(settable) if err == 0 else False
        has_range = self._attr(el, "AXSelectedTextRange") is not None
        kind = classify(role, sub, settable, has_range, pid == self.own_pid)
        pos, size = self._attr(el, "AXPosition"), self._attr(el, "AXSize")
        if pos is None or size is None:
            return None
        ok1, p = AXValueGetValue(pos, kAXValueCGPointType, None)
        ok2, s = AXValueGetValue(size, kAXValueCGSizeType, None)
        if not (ok1 and ok2):
            return None
        if self.prev is None or not CFEqual(self.prev, el):
            self.counter += 1
        self.prev = el
        return Focus(kind, (p.x, p.y, s.width, s.height), pid, (pid, role, self.counter))
