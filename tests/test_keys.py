from keys import FLAG_FN, FLAG_NUMPAD, MOD_FLAGS, chord_plan, dictation_script, osa_chord_script


def test_chord_order_and_cumulative_flags():
    p = chord_plan(48, ["command", "shift"])                 # cmd+shift+tab
    assert [(c, d) for c, d, _, _ in p] == [(55, True), (56, True), (48, True), (48, False), (56, False), (55, False)]
    cmd, shift = MOD_FLAGS["command"], MOD_FLAGS["shift"]
    assert [f for _, _, f, _ in p] == [cmd, cmd | shift, cmd | shift, cmd | shift, cmd, 0]
    assert [m for *_, m in p] == [True, True, False, False, True, True]


def test_arrows_carry_fn_and_numpad_flags_only_on_the_key():
    p = chord_plan(123, ["control"])
    ctrl = MOD_FLAGS["control"]
    assert p[0] == (59, True, ctrl, True)
    assert p[1][2] == p[2][2] == ctrl | FLAG_FN | FLAG_NUMPAD
    assert p[3] == (59, False, 0, True)
    assert chord_plan(48, ["command"])[1][2] == MOD_FLAGS["command"]          # tab: no arrow flags
    assert chord_plan(103) == [(103, True, 0, False), (103, False, 0, False)]
    assert [c for c, *_ in chord_plan(126, ["control", "option", "shift", "command"])][:4] == [59, 55, 56, 58]


def test_osascript_fallbacks():
    assert osa_chord_script(124, ["control"]) == 'tell application "System Events" to key code 124 using {control down}'
    assert osa_chord_script(48, ["command", "shift"]).endswith("using {command down, shift down}")
    assert osa_chord_script(103, []) == 'tell application "System Events" to key code 103'
    s = dictation_script()
    assert "Start Dictation" in s and "Stop Dictation" in s and '"Edit"' in s
