"""Port of the turtle pipeline: image bytes in, drawing instructions (JSON-ready dict) out.

Everything stays in memory; nothing is written to disk.
"""
import os

os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(40_000_000))  # decompression-bomb guard

import cv2
import numpy as np

from .schemas import Settings

MAX_SIDE = 1000
MAX_REGIONS = 10000
MAX_EDGE_POINTS = 200_000
MAX_SKETCH_POINTS = 250_000      # cap for the pencil-sketch lines


def _lerp(v: float, lo: float, hi: float) -> float:
    """Map a 50-1000 detail slider onto lo..hi."""
    return lo + (hi - lo) * (v - 50) / 950


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
    ct = s.color_detail / 100                              # colour-fill detail: 0 = simple shapes, 1 = every pixel edge
    region_eps = 1.5 + (0.05 - 1.5) * ct
    min_region = 1 + 30 * (1 - ct) ** 2                    # smallest colour patch (pixels) that is kept
    edge_len = _lerp(s.detail, 50, 3)
    canny_low = _lerp(s.sharpness, 160, 30)

    # --- colour regions ---
    smooth = cv2.medianBlur(
        cv2.bilateralFilter(img, 9, 75, 75),
        median
    )

    cv2.setRNGSeed(7)

    crit = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        30,
        0.5
    )

    _, labels, centers = cv2.kmeans(
        smooth.reshape(-1, 3).astype(np.float32),
        s.colors,
        None,
        crit,
        5,
        cv2.KMEANS_PP_CENTERS
    )

    centers = np.uint8(centers)

    # IMPORTANT:
    # Keep the original K-means label map.
    # Do not blur the quantized image because that can create
    # artificial color boundaries and uncovered areas.
    label_map = labels.reshape(h, w)

    k3 = np.ones((3, 3), np.uint8)

    regions = []

    for color_index, col in enumerate(centers):

        # Pixels belonging to this exact K-means color
        mask = (
            label_map == color_index
        ).astype(np.uint8) * 255

        # Very gentle cleanup.
        # CLOSE fills tiny holes without aggressively destroying details.
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            k3,
            iterations=1
        )

        cnts, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_NONE
        )

        b, g, r = (int(v) for v in col)

        for c in cnts:

            area = cv2.contourArea(c)

            # Keep even small regions.
            # At high color counts these small regions are important.
            if area < min_region:
                continue

            poly = cv2.approxPolyDP(
                c,
                region_eps,
                True
            )

            if len(poly) < 3:
                continue

            x, y, bw, bh = cv2.boundingRect(c)

            paper_white = (
                (
                    x <= 1
                    or y <= 1
                    or x + bw >= w - 1
                    or y + bh >= h - 1
                )
                and min(r, g, b) >= 235
            )

            regions.append(
                (
                    area,
                    {
                        "c": [r, g, b],
                        "p": poly.reshape(-1).tolist(),
                        "w": paper_white
                    }
                )
            )

    # Largest regions first.
    regions.sort(
        key=lambda t: t[0],
        reverse=True
    )

    regions = [
        r for _, r in regions[:MAX_REGIONS]
    ]
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

    # --- sketch lines: a separate, more sensitive edge pass, longest (= most important) first ---
    sk_gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    sd = s.sketch_detail / 100                             # 0 = few main lines, 1 = very detailed sketch
    sk_low = max(8.0, canny_low * (1.0 - 0.9 * sd))
    sk_min_len = 14 - 11 * sd
    sk_edges = cv2.Canny(sk_gray, sk_low, sk_low * 2.5)
    scnts, _ = cv2.findContours(sk_edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    sk_lines = []
    for c in scnts:
        length = cv2.arcLength(c, False)
        if length < sk_min_len:
            continue
        pts = cv2.approxPolyDP(c, 0.8, False).reshape(-1, 2)
        if len(pts) >= 2:
            sk_lines.append((length, pts))
    sk_lines.sort(key=lambda t: t[0], reverse=True)
    sketch, used = [], 0
    for _, pts in sk_lines:
        if used + len(pts) > MAX_SKETCH_POINTS:
            continue
        sketch.append(pts)
        used += len(pts)

    return {"w": w, "h": h, "regions": regions,
            "sketch": [{"p": pts.reshape(-1).tolist()} for pts in sketch],
            "edges": [{"c": rgb, "p": pts.reshape(-1).tolist()} for pts, rgb in kept]}
