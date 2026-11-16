# gestyq · development notes

everything the readme leaves out: how the app is built, every tuning key, and the diagnostic tools.

## build and run

```
conda activate vision        # python 3.11 (or anaconda's python3)
pip install -r requirements.txt
scripts/bundle.sh            # builds and installs /Applications/gestyq.app
open /Applications/gestyq.app
```

the app is a small launcher (`launcher/main.c`) that embeds python (links `libpython3.11.dylib`, sets `PYTHONHOME`)
and runs `app.py` from this folder inside the bundle's own process, so the dock icon, reopen events and the
camera / accessibility grants all belong to "gestyq".

- code edits take effect on the next launch, no rebuild needed.
- rebuild only if you move the folder, change the python env, or change the icon / launcher.
- a rebuilt binary has a new ad-hoc signature, so macOS silently drops the accessibility grant (the switch still
  looks on, but clicks stop working). after a rebuild: `tccutil reset Accessibility io.github.bassem-1.gestyq`,
  relaunch, grant again.
- `./run.sh` still works for quick runs from a terminal, but then macOS attributes permissions to the terminal.
- logs: `~/Library/Logs/gestyq.log` (app), `~/Library/Logs/gestyq-gadget.log` (gadget helper).
- the icon is rendered by `scripts/make_icon.py` from `Resources/land_mask.png` (natural earth 1:50m land,
  public domain); `scripts/bundle.sh` embeds it.

tests: `python -m pytest tests` (pure logic; the layout test needs AppKit and skips elsewhere).

## how it fits together

- `vision.py`: camera (avfoundation, chosen by device id), mediapipe hand + face landmarkers, zoom crop when you
  sit far away, the vision thread. off = camera closed.
- `tracking.py`, `gestures.py`: hand roles, finger states, pinch, fist, flick, scroll, tiling, the pointer
  (relative or absolute), resting-hand filter (`restface.py`).
- `head.py`, `gaze.py`: head turns and tilt, eye corners (beta).
- `bindings.py`: every gesture and every action; `actions.py` executes them (quartz events, key chords).
- `desktop.py`: all displays as one desktop, hot-plug, corner guard. `wake.py`: wake the display on hand motion.
- writing: `textfocus.py` + `axreader.py` (which text field is focused), `ink.py`, `letters.py`,
  `recognizer.py`, `ui/canvas.py`.
- ui: `ui/menubar.py`, `ui/popover.py`, `ui/window.py`, `ui/live.py`, `ui/inspector.py`, `ui/gadget.py`;
  `gadget_helper.py` + `afterquit.py` keep the gadget alive after quit.

## the window

- live view: the mirrored camera, dimmed, with each hand's 21 landmarks (pointer hand full red, command hand 55%),
  role tag, each hand's pose, finger states (T I M R P, filled = extended), pinch ratio against the
  `pinch_on` / `pinch_off` ticks, handedness vote, head yaw/pitch against its threshold, and the last 8
  gestures with the action they triggered.
- inspector: every gesture grouped by hand with its bound action; a row lights up when that gesture is detected.
  pick what it does; changes save immediately. `reset to defaults` restores the shipped bindings.
- `record` writes landmark sessions to `~/Library/Application Support/gestyq/recordings/<YYYYmmdd-HHMMSS>.jsonl`,
  one line per frame: `{"t": s, "aspect": w/h, "hands": [{"lms": [[x,y,z] x 21], "label": "Right", "conf": 0.97}]}`
  (unmirrored normalised landmarks). `tools/replay.py` and `tools/write_replay.py` read them.
- settings strip: `pointer` (relative | absolute), `hot corners`, `air writing` + `caps` / `lower`,
  `gadget after quit`.

## gadget after quit

`gadget_helper.py` (appkit only: no camera, no hand tracking, no accessibility, ~0% cpu) runs as a LaunchAgent
(`~/Library/LaunchAgents/com.gestyq.gadget.plist`) and shows the gadget as "off / click to start" whenever gestyq is
not running. click = `gestyq.app --on --background`. it watches `NSWorkspace.runningApplications` with KVO
(didLaunch/didTerminate never fire for accessory apps). gestyq writes the plist at launch and starts the agent as
it quits. config key `gadget_after_quit` (default on).

## settings file

`~/Library/Application Support/gestyq/config.json`. the repo's `config.json` only holds the defaults
(`python3 config.py` regenerates it). saved copies of retired defaults are dropped on load (`LEGACY_DEFAULTS`,
`CONFIG_VERSION`), so tuning changes reach existing installs.

tuning keys (the popover and window write the rest):

- `hand.min_cutoff`, `hand.beta`, `hand.deadzone`: one euro filter on the cursor
- `hand.frame_margin_x/y`: absolute mode: camera area mapped to the screen
- `hand.pinch_on`, `hand.pinch_off`, `hand.pinch_frames`: pinch hysteresis
- `hand.click_lookback`, `hand.fist_hold`, `hand.loss_grace`, `hand.double_click_gap`
- `hand.ext_deg`, `hand.curl_deg`: finger joint angle thresholds
- `hand.scroll_gain`, `hand.scroll_invert`, `hand.tile_*`
- `hand.flick_speed`, `hand.flick_travel`, `hand.flick_time`, `hand.flick_gap`, `hand.flick_return`: flick (palm sizes)
- `hand.rel_gain`, `hand.rel_knee`, `hand.rel_max_gain`: relative pointer gain curve
- `hand.fist_reach`, `hand.fist_median`, `hand.fist_relax`: fist classifier (relaxed for small hands)
- `hand.spawn_frames`: a new hand must be seen this many frames in a row before it acts
- `hand.rest_*`: resting-hand filter (head region size, stillness, overlap)
- `hand.face_palm_ratio`, `hand.face_min_conf`, `hand.face_hold`: face veto for phantom hands
- `hand.min_detection_conf`, `hand.min_presence_conf`
- `handedness.*`: label, geometry and position weights, vote time constant, flip margin and time
- `head.yaw_deg`, `head.pitch_deg`, `head.yaw_per_deg`, `head.pitch_per_deg`
- `pointer_mode`, `pointer_speed` 0-4, `head_level` 0-4, `hot_corners`
- `write.*`: `still`, `pause`, `arm_delay`, `idle_hide`, `reject`, `trigger` (`focus` = show on any text focus);
  `writing_case` `upper` | `lower`
- `bindings`: gesture id -> action id (see `bindings.py`)

## diagnostics

log lines in `~/Library/Logs/gestyq.log`: `perf-trace` (fps and per-stage ms every 5 s), `flick-trace` (peak
palm/s, travel, why a flick did or did not fire), `fist-trace` (per-finger reach when 3+ fingers are curled),
`tile-trace`, `roles-trace`.

`python debug.py` is the older opencv tool: mirrored camera with landmarks, roles, finger states, pinch ratio and
head readouts. keys: `q` quit, `s` swap hands, `r` re-calibrate head. `python3 tools/ax_probe.py` prints what the
focused text element reports to accessibility.

writing recogniser: ordered 32-point template matcher (`recognizer.py`) over capitals A-Z with common stroke-order
variants (`letters.py`). on synthetic noisy capitals it reads 99.7% / 97% / 87% at noise 0.6 / 1.0 / 1.4.
