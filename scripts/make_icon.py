#!/usr/bin/env python3
"""Renders the gestyq app icon: black squircle on the macOS icon grid (824 of 1024, radius 185, as haptyq)
with four red finger bars (heights 10:13:12:9) and a dot for the thumb tip. haptyq's sibling: same tile,
same bar language, gestyq red #FF1A2E.

usage: python3 scripts/make_icon.py <out.icns | out.png>"""
import os
import subprocess
import sys
import tempfile

from AppKit import (NSBezierPath, NSBitmapImageRep, NSColor, NSGraphicsContext, NSMakeRect, NSPNGFileType)

CANVAS, TILE, RADIUS = 1024, 824.0, 185.0
BAR_W, BAR_GAP, UNIT = 92.0, 40.0, 36.0
HEIGHTS = (10, 13, 12, 9)
DOT, DOT_GAP = 92.0, 58.0           # thumb tip: bar-wide dot, a little away from the index bar


def draw(size):
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, "NSDeviceRGBColorSpace", 0, 0)
    NSGraphicsContext.saveGraphicsState()
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.setCurrentContext_(ctx)
    from Quartz import CGContextScaleCTM
    CGContextScaleCTM(ctx.CGContext(), size / CANVAS, size / CANVAS)
    o = (CANVAS - TILE) / 2
    NSColor.colorWithSRGBRed_green_blue_alpha_(0, 0, 0, 1).setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(o, o, TILE, TILE), RADIUS, RADIUS).fill()
    bars_w = len(HEIGHTS) * BAR_W + (len(HEIGHTS) - 1) * BAR_GAP
    group_w = DOT + DOT_GAP + bars_w
    x = (CANVAS - group_w) / 2
    tall = max(HEIGHTS) * UNIT
    base = (CANVAS - tall) / 2 + DOT * 0.2            # optical centre of bars + the dot hanging below
    NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 26 / 255, 46 / 255, 1).setFill()
    NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, base - DOT * 0.35, DOT, DOT)).fill()
    x += DOT + DOT_GAP
    for h in HEIGHTS:
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(x, base, BAR_W, h * UNIT), BAR_W / 2, BAR_W / 2).fill()
        x += BAR_W + BAR_GAP
    NSGraphicsContext.restoreGraphicsState()
    return rep.representationUsingType_properties_(NSPNGFileType, {})


def main(out):
    if out.endswith(".png"):
        draw(CANVAS).writeToFile_atomically_(out, True)
        return
    with tempfile.TemporaryDirectory() as d:
        iconset = os.path.join(d, "AppIcon.iconset")
        os.makedirs(iconset)
        for pt in (16, 32, 128, 256, 512):
            draw(pt).writeToFile_atomically_(os.path.join(iconset, f"icon_{pt}x{pt}.png"), True)
            draw(pt * 2).writeToFile_atomically_(os.path.join(iconset, f"icon_{pt}x{pt}@2x.png"), True)
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
