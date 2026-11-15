"""Keyboard chord planning (pure Python): explicit modifier events, arrow flags, osascript fallback."""

MOD_CODES = {"control": 59, "command": 55, "shift": 56, "option": 58}
MOD_FLAGS = {"shift": 1 << 17, "control": 1 << 18, "option": 1 << 19, "command": 1 << 20}
FLAG_NUMPAD, FLAG_FN = 1 << 21, 1 << 23          # kCGEventFlagMaskNumericPad / SecondaryFn
ORDER = ("control", "command", "shift", "option")
ARROWS = (123, 124, 125, 126)


def chord_plan(code, mods=()):
    """[(keycode, is_down, flags, is_modifier)]: modifier downs (cumulative flags), key down/up,
    modifier ups in reverse."""
    ms = [m for m in ORDER if m in set(mods)]
    out, flags = [], 0
    for m in ms:
        flags |= MOD_FLAGS[m]
        out.append((MOD_CODES[m], True, flags, True))
    kf = flags | ((FLAG_FN | FLAG_NUMPAD) if code in ARROWS else 0)
    out.append((code, True, kf, False))
    out.append((code, False, kf, False))
    for m in reversed(ms):
        flags &= ~MOD_FLAGS[m]
        out.append((MOD_CODES[m], False, flags, True))
    return out


def osa_chord_script(code, mods=()):
    ms = [m for m in ORDER if m in set(mods)]
    using = " using {" + ", ".join(m + " down" for m in ms) + "}" if ms else ""
    return f'tell application "System Events" to key code {int(code)}{using}'


def dictation_script():
    """Clicks 'Start Dictation...' / 'Stop Dictation' in the frontmost app's Edit menu; prints ok."""
    return '''tell application "System Events"
  set p to first application process whose frontmost is true
  try
    repeat with mi in (menu items of menu 1 of menu bar item "Edit" of menu bar 1 of p)
      set n to name of mi
      if n is not missing value then
        if n starts with "Start Dictation" or n starts with "Stop Dictation" then
          click mi
          return "ok"
        end if
      end if
    end repeat
  end try
end tell
return "fail"'''


def front_window_script():
    return '''tell application "System Events"
  set p to first application process whose frontmost is true
  try
    set {x, y} to position of front window of p
    set {w, h} to size of front window of p
    return (x as text) & "," & (y as text) & "," & (w as text) & "," & (h as text)
  end try
end tell
return ""'''
