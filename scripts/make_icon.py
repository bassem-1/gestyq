#!/usr/bin/env python3
"""Renders the gestyq app icon: a dark, detailed globe on the black squircle (824 of 1024, radius 185, as haptyq).

Real coastlines (Resources/land_mask.png: Natural Earth 1:50m land, public domain, baked to a 4096x2048
equirectangular mask), orthographic view over the Atlantic, sun from the upper left with a soft terminator,
graphite land, the night side traced in gestyq red (#FF1A2E), a hairline red 15-degree graticule and a thin red
atmosphere on the lit limb.

usage: python3 scripts/make_icon.py <out.icns | out.png>"""
import math
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MASK = os.path.join(HERE, "..", "Resources", "land_mask.png")
SS = 2                                     # supersampling
N = 1024 * SS
TILE, RAD = 824 * SS, 185 * SS
R = 318 * SS                               # globe radius
LON0, LAT0 = math.radians(-25), math.radians(22)
RED = np.array([46, 26, 255], np.float32) / 255      # BGR of #FF1A2E
SUN = np.array([-0.62, 0.42, 0.66])


def _textures():
    mask = cv2.imread(MASK, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        sys.exit(f"missing {MASK}")
    H, W = mask.shape
    land = mask.astype(np.float32) / 255
    coast = cv2.morphologyEx(mask, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)).astype(np.float32) / 255
    rng = np.random.default_rng(7)
    noise = sum(cv2.resize(rng.random((H >> k, W >> k)).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
                / (2 ** k) for k in range(0, 4))
    noise = (noise - noise.min()) / (noise.max() - noise.min())
    inland = np.clip(cv2.distanceTransform(mask, cv2.DIST_L2, 5) / 30.0, 0, 1).astype(np.float32)
    return land, coast, noise, inland


def render():
    """-> BGRA uint8, 1024x1024, transparent outside the squircle."""
    land, coast, noise, inland = _textures()
    H, W = land.shape
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    x, y = (xx - N / 2) / R, -(yy - N / 2) / R
    rr = x * x + y * y
    inside = rr <= 1
    z = np.sqrt(np.clip(1 - rr, 0, 1))
    cy, sy = math.cos(LAT0), math.sin(LAT0)
    Y, Z = y * cy + z * sy, -y * sy + z * cy
    lat = np.arcsin(np.clip(Y, -1, 1))
    lon = np.arctan2(x, Z) + LON0
    mx = (((lon / (2 * math.pi) + 0.5) % 1.0) * (W - 1)).astype(np.float32)
    my = ((0.5 - lat / math.pi) * (H - 1)).astype(np.float32)
    s = lambda t: cv2.remap(t, mx, my, cv2.INTER_LINEAR)
    L, C, F, IN = s(land), s(coast), s(noise), s(inland)

    sun = SUN / np.linalg.norm(SUN)
    lam = x * sun[0] + y * sun[1] + z * sun[2]
    day = np.clip((lam + 0.08) / 0.30, 0, 1)
    day = day * day * (3 - 2 * day)
    light = np.clip(lam, 0, 1) ** 0.7 * day
    night = 1 - day

    ocean = np.array([0.018, 0.016, 0.016]) * (0.5 + 1.2 * light)[..., None]
    landv = (0.30 + 0.10 * (F - 0.5) + 0.10 * IN) * (0.05 + 1.25 * light)
    col = ocean * (1 - L[..., None]) + (landv[..., None] * np.array([0.96, 0.98, 1.0])) * L[..., None]
    col += (C * 0.22 * light)[..., None]                                   # crisp day coastlines
    hv = sun + np.array([0, 0, 1.0])
    hv /= np.linalg.norm(hv)
    col += (np.clip(x * hv[0] + y * hv[1] + z * hv[2], 0, 1) ** 60 * (1 - L) * 0.10)[..., None]   # sheen
    col += (C * night * 0.85)[..., None] * RED                             # night: coastlines in red

    def lines(a, step, w):
        m = np.abs(((a + step / 2) % step) - step / 2)
        return np.clip(1 - m / w, 0, 1)
    pix_deg = 180 / (math.pi * R) / np.maximum(z, 0.05)
    latd, lond = np.degrees(lat), np.degrees(lon)
    grat = np.maximum(lines(latd, 15, pix_deg * 0.8),
                      lines(lond, 15, pix_deg * 0.8 / np.maximum(np.cos(lat), 0.05)))
    col += (grat * (0.05 + 0.12 * night))[..., None] * RED
    col += (((1 - z) ** 6) * (0.25 + 0.75 * day))[..., None] * RED        # fresnel rim
    col *= inside[..., None]
    dist = np.sqrt(rr)
    glow = np.clip(1 - (dist - 1) / 0.05, 0, 1) ** 2.2 * (dist > 1)
    side = np.clip((x * sun[0] + y * sun[1]) / np.maximum(dist, 1e-6) + 0.2, 0, 1)
    col += (glow * side)[..., None] * RED * 0.85                           # thin atmosphere

    tile = np.zeros((N, N), np.uint8)
    o = (N - TILE) // 2
    cv2.rectangle(tile, (o + RAD, o), (o + TILE - RAD, o + TILE), 255, -1)
    cv2.rectangle(tile, (o, o + RAD), (o + TILE, o + TILE - RAD), 255, -1)
    for c in ((o + RAD, o + RAD), (o + TILE - RAD, o + RAD), (o + RAD, o + TILE - RAD), (o + TILE - RAD, o + TILE - RAD)):
        cv2.circle(tile, c, RAD, 255, -1, cv2.LINE_AA)
    a = tile.astype(np.float32) / 255
    premul = np.dstack([np.clip(col, 0, 1) * a[..., None], a])
    small = cv2.resize(premul, (1024, 1024), interpolation=cv2.INTER_AREA)
    alpha = small[..., 3:4]
    rgb = np.where(alpha > 1e-4, small[..., :3] / np.maximum(alpha, 1e-4), 0)
    return (np.clip(np.dstack([rgb, alpha]), 0, 1) * 255).astype(np.uint8)


def main(out):
    big = render()
    if out.endswith(".png"):
        cv2.imwrite(out, big)
        return
    with tempfile.TemporaryDirectory() as d:
        iconset = os.path.join(d, "AppIcon.iconset")
        os.makedirs(iconset)
        for pt in (16, 32, 128, 256, 512):
            for scale, suffix in ((1, ""), (2, "@2x")):
                px = pt * scale
                img = big if px == 1024 else cv2.resize(big, (px, px), interpolation=cv2.INTER_AREA)
                cv2.imwrite(os.path.join(iconset, f"icon_{pt}x{pt}{suffix}.png"), img)
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
