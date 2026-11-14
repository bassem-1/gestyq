# gestyq

your hands and head, in control. a macos menu bar app: webcam hand gestures move the real cursor,
click, drag and scroll; head turns switch apps. v0.3.0 (successor to handcontrol).

## install

```
conda activate vision        # python 3.11
pip install -r requirements.txt
scripts/bundle.sh            # builds and installs /Applications/gestyq.app, then open it
```

the app is a small launcher that runs `app.py` from this folder, so code edits take effect on the next
launch without rebuilding. rebuild only if you move the folder or change the python env. logs go to
`~/Library/Logs/gestyq.log`. `./run.sh` still works for quick runs from a terminal, but then macOS
attributes permissions to the terminal instead of gestyq.

## permissions

- camera: asked on launch.
- accessibility: needed to move and click. the popover shows a banner with `grant access` until it is on.
  turn on `gestyq` under system settings > privacy & security > accessibility (run it from
  /Applications/gestyq.app; it appears in the list after you click `grant access` once).

the app starts off. click the desktop gadget (or the switch in the popover) to turn it on. off releases
any held mouse button and the camera.

## gestures

| hand | gesture | action |
|---|---|---|
| right | open hand or pointing | moves the real cursor (palm centre) |
| right | thumb + index pinch | left click where the cursor settled; two pinches < 0.4 s = double click |
| right | fist, held 0.15 s | drag: mouse down, move, open the hand to drop |
| right | still for 0.9 s | dwell click (popover switch, off by default) |
| left | thumb + index pinch | right click |
| left | index + middle up, move up/down | scroll |
| left | open palm, fast sideways swipe | next / previous space |
| both | open palms: move together left/right, spread, bring together | tile window left/right, fill, centre |
| head | turn right and back / left and back | next app (cmd+tab) / previous app |
| head | tilt up and hold 0.6 s | display sleep |

eye corners (gaze dwell on a screen corner) is beta and off by default.

## tuning

run `python debug.py`: mirrored camera with landmarks, each hand's role and vote, finger states, pinch
ratio, gesture label, head yaw/pitch against the baseline and head events. keys: `q` quit, `s` swap
hands, `r` re-calibrate head. if roles are still reversed, turn on `swap hands`.

keys in `config.json` (the popover writes the rest):

- `hand.min_cutoff`, `hand.beta`, `hand.deadzone`: one euro filter on the cursor (smooth when slow, fast when fast)
- `hand.frame_margin_x/y`: camera area mapped to the screen
- `hand.pinch_on`, `hand.pinch_off`, `hand.pinch_frames`: pinch hysteresis
- `hand.click_lookback`, `hand.fist_hold`, `hand.loss_grace`, `hand.double_click_gap`
- `hand.ext_deg`, `hand.curl_deg`: finger joint angle thresholds
- `hand.scroll_gain`, `hand.scroll_invert`, `hand.swipe_dist`, `hand.tile_*`
- `handedness.*`: label, geometry and position weights, vote time constant, flip margin and time
- `head.yaw_deg`, `head.pitch_deg`: thresholds at sensitivity `normal`; `head.yaw_per_deg`,
  `head.pitch_per_deg` convert the nose-offset proxy to degrees
- `pointer_speed` 0-4, `head_level` 0-4 (0 = off)

tests: `python -m pytest tests` (pure logic only, runs anywhere).
