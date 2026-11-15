import textfocus as tf
from textfocus import CanvasGate, Focus, classify, place_canvas


def test_classify_table():
    assert classify("AXTextField", None, True, True) == "text"
    assert classify("AXTextArea", None, True, True) == "text"
    assert classify("AXSearchField", None, False, False) == "text"
    assert classify("AXTextField", "AXSearchField", True, True) == "text"
    assert classify("AXGroup", "AXSearchField", False, False) == "text"
    assert classify("AXComboBox", None, True, False) == "text"
    assert classify("AXTextField", "AXSecureTextField", True, True) == "secure"
    assert classify("AXWebArea", None, True, True) == "text"                   # contenteditable
    assert classify("AXWebArea", None, False, True) is None                    # read-only page
    assert classify("AXButton", None, False, False) is None
    assert classify("AXGroup", None, False, False) is None
    assert classify("AXGroup", None, True, False) is None
    assert classify("AXTextField", None, True, True, own_process=True) is None


SCR = (0, 0, 1440, 900)


def test_place_canvas_below_above_and_inside_for_tall_fields():
    assert place_canvas((100, 100, 400, 30), [SCR]) == (100, 138)               # below, left edges aligned
    x, y = place_canvas((100, 800, 400, 30), [SCR])                              # no room below: above
    assert (x, y) == (100, 800 - 8 - 200)
    assert place_canvas((50, 50, 1000, 700), [SCR]) == (1050 - 320 - 16, 750 - 200 - 16)    # tall: inside bottom right
    assert place_canvas((0, 0, 1440, 900), [SCR]) == (1440 - 320 - 16, 900 - 200 - 16)


def test_place_canvas_clamps_and_picks_the_screen_of_the_field():
    left = (-1920, 0, 1920, 1080)                                                 # a display left of the primary
    x, y = place_canvas((-400, 100, 300, 30), [SCR, left])
    assert left[0] <= x and x + 320 <= left[0] + left[2]                          # field centre is on the left display
    assert place_canvas((-1900, 100, 300, 30), [SCR, left]) == (-1900, 138)
    far = place_canvas((5000, 5000, 100, 30), [SCR])                              # off every display: nearest, clamped
    assert far[0] + 320 <= 1440 and far[1] + 200 <= 900
    for field in ((0, 0, 50, 20), (1400, 880, 100, 20), (700, 450, 10, 10), (-5, -5, 3000, 3000), (-1900, 1000, 100, 30)):
        x, y = place_canvas(field, [SCR, left])
        assert any(r[0] <= x and x + 320 <= r[0] + r[2] and r[1] <= y and y + 200 <= r[1] + r[3] for r in (SCR, left))


def text(token=1, frame=(100, 100, 300, 30)):
    return Focus("text", frame, 42, token)


INSIDE = (200, 110)


def test_click_in_a_focused_text_field_shows_and_focus_alone_does_not():
    g = CanvasGate()
    assert g.step(10.0, text(), True, None) is False                              # focus without a click
    assert g.step(10.2, text(), True, (9.9, INSIDE)) is True                      # click on the field
    assert g.step(11.0, text(), True, (9.9, INSIDE)) is True                      # stays
    assert CanvasGate().step(10.0, text(), True, (9.9, (900, 900))) is False      # click elsewhere


def test_click_window_is_one_second_for_laggy_focus():
    assert CanvasGate().step(10.8, text(), True, (10.0, INSIDE)) is True          # focus arrived 0.8 s after the click
    assert CanvasGate().step(11.5, text(), True, (10.0, INSIDE)) is False         # 1.5 s: not this click


def test_a_failed_read_is_tolerated_for_0_4_s():
    g = CanvasGate()
    g.step(10.0, text(), True, (9.9, INSIDE))
    assert g.step(10.3, None, True, None) is True
    assert g.step(10.6, None, True, None) is False
    g = CanvasGate()
    g.step(10.0, text(), True, (9.9, INSIDE))
    assert g.step(10.3, None, True, None) is True and g.step(10.35, text(), True, None) is True


def test_idle_hide_after_12_s_is_reset_by_ink_and_a_new_click_shows_again():
    g = CanvasGate(idle_hide=12.0)
    g.step(10.0, text(), True, (9.9, INSIDE))
    assert g.step(21.0, text(), True, None) is True
    g.note_ink(21.5)
    assert g.step(33.0, text(), True, None) is True                                # 11.5 s since ink
    assert g.step(34.0, text(), True, None) is False                               # 12.5 s: hidden
    assert g.step(35.0, text(), True, (9.9, INSIDE)) is False                      # the old click is spent
    assert g.step(36.0, text(), True, (35.8, INSIDE)) is True                      # click the field again
    assert CanvasGate(idle_hide=0).step(500.0, text(), True, (499.9, INSIDE)) is True


def test_idle_never_hides_when_zero():
    g = CanvasGate(idle_hide=0)
    g.step(10.0, text(), True, (9.9, INSIDE))
    assert g.step(5000.0, text(), True, None) is True


def test_secure_fields_never_show_and_leaving_the_field_hides():
    g = CanvasGate()
    sec = Focus("secure", (100, 100, 300, 30), 42, 2)
    assert g.step(10.0, sec, True, (9.9, INSIDE)) is False
    g.step(11.0, text(), True, (10.9, INSIDE))
    assert g.visible
    assert g.step(12.0, sec, True, None) is False
    g.step(13.0, text(), True, (12.9, INSIDE))
    assert g.step(13.5, Focus(None, (0, 0, 5, 5), 42, 9), True, None) is False     # a button took focus
    g.step(14.0, text(), True, (13.9, INSIDE))
    assert g.step(14.5, text(token=77), True, None) is False                       # another text element, no click


def test_off_hides_at_once_and_focus_trigger_shows_without_a_click():
    g = CanvasGate()
    g.step(10.0, text(), True, (9.9, INSIDE))
    assert g.step(10.1, text(), False, None) is False
    f = CanvasGate(trigger="focus")
    assert f.step(10.0, text(), True, None) is True
    f.step(11.0, Focus(None, (0, 0, 1, 1), 1, 3), True, None)
    assert f.step(12.0, text(token=5), True, None) is True


def test_canvas_size_is_the_spec_size():
    assert tf.CANVAS_SIZE == (320, 200)
