# gestyq

your hands and head, in control. a macos menu bar app: webcam hand gestures move the real cursor,
click, drag and scroll; head turns switch apps. v0.4.0 (successor to handcontrol).

## install

```
conda activate vision        # python 3.11
pip install -r requirements.txt
./run.sh                     # models download on first start
```

## permissions

- camera: asked on launch.
- accessibility: needed to move and click. the popover shows a banner with `grant access` until it is on.
  add your terminal (or python) under system settings > privacy & security > accessibility.

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
| left | open palm, fast sideways swipe (1.6 palm widths in 0.45 s, any distance) | next / previous space |
| left | fist, held 0.6 s | toggle macos dictation (once per hold; open the hand to re-arm) |
| both | open palms: move together left/right, spread, bring together | tile window left/right, fill, centre (on the display holding the front window) |
| head | turn right and back / left and back | next app (cmd+tab) / previous app |
| head | tilt up and hold 0.6 s | display sleep |

eye corners (gaze dwell on a screen corner) is beta and off by default.

## tuning

run `python debug.py`: mirrored camera with landmarks, each hand's role and vote, finger states, pinch
ratio, gesture label, head yaw/pitch against the baseline and head events. keys: `q` quit, `s` swap
hands, `r` re-calibrate head. if roles are still reversed, turn on `swap hands`.

keys in `config.json` (the popover writes the rest):

- `hand.min_cutoff`, `hand.beta`, `hand.deadzone`: one euro filter on the cursor (smooth when slow, fast when fast)
- `hand.frame_margin_x/y`: fixed camera area mapped to the desktop (used when no face is seen); its aspect follows all displays together
- `hand.pinch_on`, `hand.pinch_off`, `hand.pinch_frames`: pinch hysteresis
- `hand.click_lookback`, `hand.fist_hold`, `hand.loss_grace`, `hand.double_click_gap`
- `hand.ext_deg`, `hand.curl_deg`: finger joint angle thresholds
- `hand.scroll_gain`, `hand.scroll_invert`, `hand.swipe_*` and `hand.tile_move/gap` (palm widths), `hand.dictation_hold`
- `hand.far_face_frac/near_face_frac`, `hand.roi_face_widths`: adaptive zoom on/off thresholds and crop size (face widths)
- `hand.box_face_widths`, `hand.box_offset_x/y`: body-relative control box
- `dictation` (popover switch) and `actions.dictation`: fallback action if the Edit menu item is not found
- `handedness.*`: label, geometry and position weights, vote time constant, flip margin and time
- `head.yaw_deg`, `head.pitch_deg`: thresholds at sensitivity `normal`; `head.yaw_per_deg`,
  `head.pitch_per_deg` convert the nose-offset proxy to degrees
- `pointer_speed` 0-4, `head_level` 0-4 (0 = off)

## multiple displays

the cursor covers the union of all displays; points that fall in a dead area (l-shaped layouts) snap to
the nearest display. the control box in the camera frame follows the desktop's aspect. the popover shows
the display count; hot-plugging is picked up live.

## distance

the face width is the scale reference. a far face (< 16% of the frame width) switches on an automatic zoom
crop of the full-resolution frame for the hand detector, and the pointer box follows your shoulder, so the
same arm movement covers the screen at 50 cm or 2.5 m. the camera is asked for 1920x1080 (falls back to
1280x720). `debug.py` draws the zoom rectangle, the control box and the face width fraction.

## troubleshooting

- spaces do not switch: system settings > keyboard > keyboard shortcuts > mission control, enable
  "move left a space" / "move right a space" (ctrl + arrows). also check accessibility access; without it
  gestyq falls back to osascript, which needs automation access for system events.
- dictation does nothing: system settings > keyboard > dictation must be on. gestyq clicks "start dictation"
  in the front app's edit menu; if an app has none, set `actions.dictation` in `config.json`
  (for example `"key:96"`).
- hands missed far away: light the hands from the front, avoid strong back light, and use a 1080p camera
  (an external webcam helps). check `debug.py`: the yellow rectangle is the zoom crop.

tests: `python -m pytest tests` (pure logic only, runs anywhere).
