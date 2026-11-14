"""Design tokens. Two colours only: black and red #FF1A2E at fixed opacities. Lowercase strings,
monospaced system font (22/13/11, regular + medium), 4pt grid. AppKit is imported lazily so the
tokens stay importable (and testable) off macOS."""

RED = (1.0, 26 / 255, 46 / 255)      # #FF1A2E
A_FG, A_FG2, A_DIM, A_LINE, A_WASH = 1.0, 0.55, 0.32, 0.16, 0.08
PAD, ROW, GAP, RADIUS, CONTROL_RADIUS = 16, 32, 16, 10, 6
SIZE_STATE, SIZE_TITLE, SIZE_SMALL = 22, 13, 11
POPOVER_W = 300
GADGET = 140
GADGET_RADIUS = 22


def _ns(r, g, b, a):
    from AppKit import NSColor
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)


def red(alpha=1.0):
    return _ns(*RED, alpha)


def black():
    return _ns(0.0, 0.0, 0.0, 1.0)


def fg():
    return red(A_FG)


def fg2():
    return red(A_FG2)


def dim():
    return red(A_DIM)


def line():
    return red(A_LINE)


def wash():
    return red(A_WASH)


def font(size, medium=False):
    from AppKit import NSFont, NSFontWeightMedium, NSFontWeightRegular
    return NSFont.monospacedSystemFontOfSize_weight_(size, NSFontWeightMedium if medium else NSFontWeightRegular)


def dark_appearance():
    from AppKit import NSAppearance, NSAppearanceNameDarkAqua
    return NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua)
