"""Port of the turtle pipeline: image bytes in, drawing instructions (JSON-ready dict) out.

Everything stays in memory; nothing is written to disk.
"""
import os

os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(40_000_000))  # decompression-bomb guard

import cv2
import numpy as np

from .schemas import Settings

MAX_SIDE = 560        # working size of the drawing
MAX_REGIONS = 300
MAX_EDGE_POINTS = 40_000


def _lerp(v: float, lo: float, hi: float) -> float:
    """Map a 0-100 slider value onto lo..hi."""
    return lo + (hi - lo) * v / 100


def _decode(data: bytes) -> np.ndarray:
    raw = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ValueError("This file could not be read as an image.")
    if raw.ndim == 2:
        return cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    if raw.shape[2] == 4:
        img = raw[:, :, :3].copy()
        img[raw[:, :, 3] < 128] = 255
        return img
    return raw


def process(data: bytes, s: Settings) -> dict:
    img = _decode(data)
    h0, w0 = img.shape[:2]
    k = min(MAX_SIDE / max(h0, w0), 1)
    w, h = max(1, int(w0 * k)), max(1, int(h0 * k))
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.15, 0, 255)
    img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # --- slider mapping ---
    median = 3 + 2 * int(_lerp(s.texture, 0, 5))          # 3..13 (more = flatter)
    min_area = _lerp(s.detail, 500, 40)
    region_eps = _lerp(s.detail, 2.2, 0.8)
    edge_len = _lerp(s.detail, 60, 8)
    canny_low = _lerp(s.sharpness, 160, 30)

    # --- colour regions ---
    smooth = cv2.medianBlur(cv2.bilateralFilter(img, 9, 75, 75), median)
    cv2.setRNGSeed(7)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, labels, centers = cv2.kmeans(smooth.reshape(-1, 3).astype(np.float32), s.colors,
                                    None, crit, 5, cv2.KMEANS_PP_CENTERS)
    centers = np.uint8(centers)
    quant = cv2.medianBlur(centers[labels.flatten()].reshape(img.shape), 5)

    k3 = np.ones((3, 3), np.uint8)
    regions = []
    for col in centers:
        mask = np.all(quant == col, axis=2).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k3, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k3)
        mask = cv2.dilate(mask, k3)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        b, g, r = (int(v) for v in col)
        for c in cnts:
            area = cv2.contourArea(c)
            if area < min_area:
                continue
            poly = cv2.approxPolyDP(c, region_eps, True)
            if len(poly) < 3:
                continue
            x, y, bw, bh = cv2.boundingRect(c)
            paper_white = (x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1) and min(r, g, b) >= 235
            regions.append((area, {"c": [r, g, b], "p": poly.reshape(-1).tolist(), "w": paper_white}))
    regions.sort(key=lambda t: t[0], reverse=True)       # big first: nothing gets covered
    regions = [r for _, r in regions[:MAX_REGIONS]]

    # --- edges ---
    gray = cv2.bilateralFilter(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 5, 40, 40)
    edges = cv2.Canny(gray, canny_low, canny_low * 2.5)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    ecnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    colour_src = cv2.blur(img, (5, 5))
    lines = []
    for c in ecnts:
        if cv2.arcLength(c, False) < edge_len:
            continue
        pts = cv2.approxPolyDP(c, 0.9, False).reshape(-1, 2)
        if len(pts) < 2:
            continue
        if s.outline_mode == "black":
            rgb = [0, 0, 0]
        else:
            bgr = colour_src[pts[:, 1], pts[:, 0]].mean(axis=0) * s.outline_darken
            rgb = [int(bgr[2]), int(bgr[1]), int(bgr[0])]
        lines.append((pts, rgb))

    lines.sort(key=lambda t: len(t[0]), reverse=True)    # keep the longest lines under the cap
    kept, used = [], 0
    for pts, rgb in lines:
        if used + len(pts) > MAX_EDGE_POINTS:
            continue
        kept.append((pts, rgb))
        used += len(pts)
    if s.edge_order == "top_to_bottom":
        kept.sort(key=lambda t: t[0][:, 1].mean())
    elif s.edge_order == "left_to_right":
        kept.sort(key=lambda t: t[0][:, 0].mean())

    return {"w": w, "h": h, "regions": regions,
            "edges": [{"c": rgb, "p": pts.reshape(-1).tolist()} for pts, rgb in kept]}
