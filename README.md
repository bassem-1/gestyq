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

### preview mode

while the window is open the camera and detection run even if gestyq is off, so the live view always
works, but no action executes: the window says `preview · actions off`. turn gestyq on (switch in the
window, popover or gadget) and the same view runs with actions live. closing the window while off stops
the camera; switching modes never leaves a mouse button held.

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
| left | open palm, sideways swipe (0.18 of the frame in 0.45 s) | next / previous space |
| both | open palms: move together left/right, spread, bring together | tile window left/right, fill, centre |
| head | turn right and back / left and back | next app (cmd+tab) / previous app |
| head | tilt up and hold 0.6 s | display sleep |

eye corners (gaze dwell on a screen corner) is beta and off by default.

## tuning

the window's live view covers most of this. `python debug.py` is the older OpenCV tool: mirrored camera with landmarks, each hand's role and vote, finger states, pinch
ratio, gesture label, head yaw/pitch against the baseline and head events. keys: `q` quit, `s` swap
hands, `r` re-calibrate head. if roles are still reversed, turn on `swap hands`.

keys in your settings file (the popover and window write the rest):

- `hand.min_cutoff`, `hand.beta`, `hand.deadzone`: one euro filter on the cursor (smooth when slow, fast when fast)
- `hand.frame_margin_x/y`: camera area mapped to the screen
- `hand.pinch_on`, `hand.pinch_off`, `hand.pinch_frames`: pinch hysteresis
- `hand.click_lookback`, `hand.fist_hold`, `hand.loss_grace`, `hand.double_click_gap`
- `hand.ext_deg`, `hand.curl_deg`: finger joint angle thresholds
- `hand.scroll_gain`, `hand.scroll_invert`, `hand.tile_*`
- `hand.swipe_dist`, `hand.swipe_time`: open-palm swipe, 0.18 of the frame width within 0.45 s
- `hand.spawn_frames`: a new hand must be seen this many frames in a row (5) before it acts
- `hand.face_palm_ratio`, `hand.face_min_conf`, `hand.face_hold`: face veto. a hand whose palm centre is inside the
  face box (shrunk to 70%) is dropped when its palm is smaller than 0.4 x the face height or its handedness
  confidence is under 0.6. needs head or eye tracking on (that is what finds the face)
- `hand.min_detection_conf`, `hand.min_presence_conf`: 0.7
- `handedness.*`: label, geometry and position weights, vote time constant, flip margin and time
- `head.yaw_deg`, `head.pitch_deg`: thresholds at sensitivity `normal`; `head.yaw_per_deg`,
  `head.pitch_per_deg` convert the nose-offset proxy to degrees
- `pointer_speed` 0-4, `head_level` 0-4 (0 = off)

tests: `python -m pytest tests` (pure logic; the layout test needs AppKit and skips elsewhere).
