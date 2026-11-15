# gestyq

your hands and head, in control. a macos menu bar app: webcam hand gestures move the real cursor,
click, drag and scroll; head turns switch apps. v0.3.0 (successor to handcontrol).

## install

```
conda activate vision        # python 3.11
pip install -r requirements.txt
scripts/bundle.sh            # builds and installs /Applications/gestyq.app, then open it
```

the app is a small launcher that embeds python (links `libpython3.11.dylib`, sets `PYTHONHOME`) and runs
`app.py` from this folder inside the bundle's own process, so the dock icon, reopen events and the
camera/accessibility grants all belong to "gestyq". code edits take effect on the next launch without
rebuilding; rebuild only if you move the folder or change the python env (a rebuilt binary has a new
signature, so re-enable gestyq under accessibility once). logs go to `~/Library/Logs/gestyq.log`. `./run.sh` still works for quick runs from a terminal, but then macOS
attributes permissions to the terminal instead of gestyq.

## the window

opening gestyq shows its window (also: `open gestyq` in the popover, the gadget's right-click menu, or
launching the app again while it runs). closing it returns to the menu bar; gestyq keeps running. the
login item starts with `--background`, so no window appears at login.

- left, live view: the mirrored camera, dimmed, with each hand's 21 landmarks (pointer hand full red,
  command hand 55%), role tag, and under it each hand's pose, finger states (T I M R P, filled =
  extended), pinch ratio against the `pinch_on` / `pinch_off` ticks, handedness vote, head yaw/pitch
  against its threshold, and the last 8 recognised gestures with the action they triggered.
- right, inspector: every gesture grouped by hand with its bound action. a row lights up when that gesture
  is detected live. select one to read how to do it and pick what it does; changes save immediately.
  `reset to defaults` restores the shipped bindings.
- `record` (under the log) writes landmark sessions to
  `~/Library/Application Support/gestyq/recordings/<YYYYmmdd-HHMMSS>.jsonl`, one line per camera frame:
  `{"t": monotonic s, "aspect": w/h, "hands": [{"lms": [[x,y,z] x 21], "label": "Right", "conf": 0.97}]}`
  (unmirrored normalised landmarks; `tools/replay.py` reads them).

### off means off

turning gestyq off closes the camera, window open or not: the live view shows `gestyq is off` and the switch in
the top strip turns it back on (camera and actions start together). closing the window never stops gestyq.
under the live view and inspector a settings strip holds `pointer` (relative | absolute) and `hot corners`.

## displays, distance, camera

- the pointer covers every connected display (dead corners of L-shaped layouts snap to the nearest display);
  plug or unplug a display and it adapts within a second.
  the window status shows the display count; tiling acts on the display holding the front window.
- pointer `relative` (default, like a mouse): the cursor moves by the hand's motion, measured in palm sizes so it is the
  same near and far, through an acceleration curve (slow = precise, a brisk 30 cm move crosses a wide screen;
  `pointer_speed` 1-4 scales the gain). the hand can be anywhere in the frame; when it leaves and comes back the
  cursor stays where it was. `absolute`: a box of the camera maps onto the displays (drawn faintly in the live view).
- when you sit far away (face under 22% of the frame, back to normal above 27%) the hand detector runs on a crop of
  your upper body (about 7 face widths wide, head to waist, raised arms included) at up to 1280 px; every 5th frame
  it also looks at the whole frame so a hand outside the crop is found again (and the crop grows around it).
- `hot corners` (window): on, the cursor may reach the corners (a hot corner like display sleep works). off, gestures
  keep the cursor 4 px away from the corners; edges stay reachable.
- if the display is asleep (hot corner, idle) and gestyq is on, a moving hand or any gesture wakes it, like touching
  the trackpad (at most every 2 s; gestures do not click while the display is asleep).
- the camera is chosen by device id in the window (`camera` under the live view), never by position.
  auto = the built-in camera; if a chosen iphone is away, gestyq uses the built-in one and says so.

## bindings

what each gesture does is not fixed. `bindings.py` lists every gesture and action; your choices live
under `bindings` in your settings file. a missing or invalid entry falls back to the default.

## settings

your settings live in `~/Library/Application Support/gestyq/config.json` (the popover and the window write
it; the repo's `config.json` only holds the defaults).

## permissions

- camera: asked on launch.
- accessibility: needed to move and click. the popover shows a banner with `grant access` until it is on.
  turn on `gestyq` under system settings > privacy & security > accessibility (run it from
  /Applications/gestyq.app; it appears in the list after you click `grant access` once).

the app starts off. click the desktop gadget (or the switch in the popover) to turn it on. off releases
any held mouse button and the camera.

## gestures (default bindings)

| hand | gesture | action |
|---|---|---|
| right | open hand or pointing | moves the real cursor (palm centre) |
| right | thumb + index pinch | left click where the cursor settled; two pinches < 0.4 s = double click |
| right | fist, held 0.15 s | drag: mouse down, move, open the hand to drop |
| right | still for 0.9 s | dwell click (popover switch, off by default) |
| left | thumb + index pinch | right click |
| left | index + middle up, move up/down | scroll |
| either | flick the hand sideways, any pose, like waving a fly away (a burst above 10 palm sizes / s, 0.8+ palm sizes within 0.25 s; the return stroke is ignored) | next space (your left) / previous space (your right) |
| right | point (index out, other fingers folded) while the canvas is up | pen: the fingertip draws, the cursor stands still |
| right | open hand, flick sideways while the canvas is up | space (your right) / delete (your left) |
| both | open palms: move together left/right, spread apart, bring together | tile window left/right, maximize, minimize |
| head | turn right and back / left and back | next app (cmd+tab) / previous app |
| head | tilt up and hold 0.6 s | display sleep |

eye corners (gaze dwell on a screen corner) is beta and off by default.

## writing

air-writing types letters you draw in the air. nothing changes until you **click a text field** (with gestyq or the
real mouse): a small black canvas appears next to the field. it never takes focus and clicks pass through it, so the
caret stays where it was. click anywhere else and it goes away. password fields never show it.

- **point** (index out, other fingers folded) and the fingertip draws red ink. the cursor stands still while you draw.
  the first half second after the canvas appears is ignored, so the hand coming out of the click does not scribble.
- the letter is finished when the fingertip is **still for 0.5 s**, or when you open the hand (**pen up**) for
  0.6 s. the letter is typed into the field and shown on the canvas for a moment (`g · q` means it was unsure: the
  runner-up). lift and write a second stroke within 0.6 s and it is the same letter (t, x, k, f).
- **space**: open your hand and flick it to your right. **delete**: flick left (this throws away ink you have just
  drawn, or deletes the last character). these are the bindable gestures `write_flick_right` / `write_flick_left`.
  the left hand still switches spaces.
- **enter**: draw a stroke down, then left (a return arrow).
- pointing, pinch and flicks work as before whenever no text field is focused. a pinch right after writing is not a click.
- the switch `air writing` in the window (or `write.enabled`) turns all of it off. the `toggle_write` action can be bound.

letter shapes (**capitals A-Z**, the way block capitals are written in the air): lift the finger or retrace instead of
lifting, both work, and the common variants are built in (A as an inverted V plus bar, left leg or right leg first; E and F
as one snake path or a stack; K, H, X, T, Y, P, R, B, D, Q with or without a lift). `I` is a bare line, `L` is down then
RIGHT, `J` is down then a curved hook, and enter is down then LEFT (a sharp corner). the shapes are in `letters.py`
(the lowercase set was dropped; see git history). the recogniser is a template matcher (`recognizer.py`); on synthetic
noisy capitals it reads 99.7% / 97% / 87% right at noise 0.6 / 1.0 / 1.4 (90% at 1.0 when a quarter of the strokes are
drawn backwards), but your own handwriting in the air will be worse: expect 80-90% at first. the commonest mix-ups are
U/V, N/W, K/R, D/P, S/F. the canvas shows what was read, in the case that is typed; flick left to undo.

**case**: letters are typed as capitals by default. the `caps` / `lower` buttons next to `air writing` in the window (or
`writing_case`: `"upper"` / `"lower"` in your settings file) choose the case; the shapes drawn are the same.

needs accessibility (to read which field is focused). `python3 tools/ax_probe.py` prints what the focused element
reports; `python3 tools/write_replay.py <recording.jsonl>` runs a recording (window `record` button) through the
engine and prints the letters. keys under `write` in your settings file: `still`, `pause`, `arm_delay`, `idle_hide`
(12 s without ink hides the canvas), `reject` (how sloppy a letter may be), `trigger` (`focus` shows it on any text
focus instead of a click).

## tuning

the window's live view covers most of this. `python debug.py` is the older OpenCV tool: mirrored camera with landmarks, each hand's role and vote, finger states, pinch
ratio, gesture label, head yaw/pitch against the baseline and head events. keys: `q` quit, `s` swap
hands, `r` re-calibrate head. if roles are still reversed, turn on `swap hands`.

keys in your settings file (the popover and window write the rest):

- `hand.min_cutoff`, `hand.beta`, `hand.deadzone`: one euro filter on the cursor (smooth when slow, fast when fast)
- `hand.frame_margin_x/y`: absolute mode: camera area mapped to the screen
- `hand.pinch_on`, `hand.pinch_off`, `hand.pinch_frames`: pinch hysteresis
- `hand.click_lookback`, `hand.fist_hold`, `hand.loss_grace`, `hand.double_click_gap`
- `hand.ext_deg`, `hand.curl_deg`: finger joint angle thresholds
- `hand.scroll_gain`, `hand.scroll_invert`, `hand.tile_*`
- `hand.flick_speed`, `hand.flick_travel`, `hand.flick_time`, `hand.flick_gap`, `hand.flick_return`: flick (palm sizes)
- `hand.rel_gain`, `hand.rel_knee`, `hand.rel_max_gain`: relative pointer gain curve
- `hand.fist_reach`, `hand.fist_median`, `hand.fist_relax`: fist classifier (relaxed for small hands)
- `pointer_mode` relative | absolute, `hot_corners` true | false
- `hand.spawn_frames`: a new hand must be seen this many frames in a row (5) before it acts
- `hand.face_palm_ratio`, `hand.face_min_conf`, `hand.face_hold`: face veto. a hand whose palm centre is inside the
  face box (shrunk to 70%) is dropped when its palm is smaller than 0.4 x the face height or its handedness
  confidence is under 0.6. needs head or eye tracking on (that is what finds the face)
- `hand.min_detection_conf`, `hand.min_presence_conf`: 0.7
- `handedness.*`: label, geometry and position weights, vote time constant, flip margin and time
- `head.yaw_deg`, `head.pitch_deg`: thresholds at sensitivity `normal`; `head.yaw_per_deg`,
  `head.pitch_per_deg` convert the nose-offset proxy to degrees
- `pointer_speed` 0-4, `head_level` 0-4 (0 = off)

diagnostic log lines (`~/Library/Logs/gestyq.log`): `flick-trace` (peak palm/s, travel, why a flick did or did not fire), `fist-trace` (per-finger reach, median, limit and palm size whenever 3+ fingers are curled), `tile-trace`, `roles-trace`.

tests: `python -m pytest tests` (pure logic; the layout test needs AppKit and skips elsewhere).
