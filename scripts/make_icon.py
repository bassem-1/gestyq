#!/usr/bin/env python3
"""Renders the gestyq app icon: black squircle on the macOS icon grid (824 of 1024, radius 185, as haptyq)
with a red comet: an arc that thickens and brightens toward a solid head, a gesture drawn in the air.
gestyq red #FF1A2E; the tail fades through the brand opacities.

usage: python3 scripts/make_icon.py <out.icns | out.png>"""
import math
import os
import subprocess
import sys
import tempfile

from AppKit import (NSBezierPath, NSBitmapImageRep, NSColor, NSGraphicsContext, NSMakeRect, NSPNGFileType,
                    NSRoundLineCapStyle)

CANVAS, TILE, RADIUS = 1024, 824.0, 185.0
ARC_R = 240.0                      # comet path radius
START, END = 205.0, 25.0           # degrees: tail -> head, clockwise over the top
SEGMENTS = 48
TAIL_W, HEAD_W = 44.0, 124.0       # stroke width along the arc
HEAD_R = 96.0
CENTER = (CANVAS / 2 - 8, CANVAS / 2 - 78)   # optical centre of the whole mark


def red(a=1.0):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 26 / 255, 46 / 255, a)


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
    span = START - END
    for i in range(SEGMENTS):
        f0, f1 = i / SEGMENTS, (i + 1) / SEGMENTS
        p = NSBezierPath.bezierPath()
        p.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            CENTER, ARC_R, START - f0 * span, START - f1 * span - 0.5, True)
        p.setLineWidth_(TAIL_W + (HEAD_W - TAIL_W) * f1)
        p.setLineCapStyle_(NSRoundLineCapStyle)
        red(0.08 + 0.92 * f1 ** 1.6).setStroke()
        p.stroke()
    a = math.radians(END)
    x, y = CENTER[0] + ARC_R * math.cos(a), CENTER[1] + ARC_R * math.sin(a)
    red().setFill()
    NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x - HEAD_R, y - HEAD_R, 2 * HEAD_R, 2 * HEAD_R)).fill()
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
