import turtle
import cv2
import numpy as np
import math
import os
import time
import random
from tkinter import Tk, filedialog

# ============================================================
# SETTINGS
# ============================================================

# If IMAGE_PATH is None, a file dialog will pop up
IMAGE_PATH = None          # set to a path string to skip dialog

SCREEN_W = 700
SCREEN_H = 700
MAX_IMAGE_W = 420
MAX_IMAGE_H = 420

# ---- Fills ----
BLUR_KERNEL      = 7
NUM_COLORS       = 10
MIN_REGION_AREA  = 100
SATURATION_BOOST = 1.15

# ---- Shape fidelity ----
APPROX_EPSILON       = 0.5
CORNER_ANGLE_DEG     = 40
CURVE_SUBDIVISIONS   = 15

# ---- Edges ----
CANNY_LOW, CANNY_HIGH = 80, 200
EDGE_MIN_LEN          = 15
EDGE_APPROX_EPS       = 0.5
EDGE_CORNER_ANGLE_DEG = 40

# ---- Rendering ----
OUTLINE_WIDTH = 1.2
TURTLE_SPEED  = 0

# ---- Outline colour ----
OUTLINE_COLOR_MODE = "image"   # "image" = outlines take the colour of the picture, "black" = old look
OUTLINE_DARKEN     = 0.65      # 1.0 = exact image colour, 0.5 = darker, 0.0 = black
OUTLINE_COLOR_BLUR = 5         # size of the area averaged under each outline point (odd number)

# ---- Pen animation ----
SHOW_PEN         = True    # show a pencil while drawing
PEN_UPDATE_EVERY = 6       # redraw the screen every N moves (smaller = smoother but slower)
FRAME_SLEEP      = 0.0     # extra seconds to wait on each redraw (e.g. 0.002 = slower)
HIDE_PEN_AT_END  = True    # hide the pencil when everything is finished

# ============================================================
# NEW FEATURES - SETTINGS
# ============================================================

# ---- Draw mode ----
#   "fills_first"  : colour the regions, then draw the outlines   (same as before)
#   "sketch_first" : light grey pencil sketch -> colour the regions -> final coloured outlines
DRAW_MODE           = "fills_first"
SKETCH_COLOR        = (0.45, 0.45, 0.45)   # pencil-sketch colour (r, g, b from 0 to 1)
SKETCH_WIDTH        = 1
SKETCH_SPEED_FACTOR = 3                    # the sketch pass is this many times faster

# ---- Draw order ----
#   REGION_ORDER: "big_first", "small_first", "top_to_bottom", "bottom_to_top",
#                 "left_to_right", "center_out", "random"
#   (a region that sits inside a bigger region is always drawn after it, so nothing gets covered)
#   EDGE_ORDER:   "as_found", "top_to_bottom", "left_to_right", "center_out",
#                 "long_first", "short_first", "random"
REGION_ORDER = "big_first"
EDGE_ORDER   = "as_found"
RANDOM_SEED  = 7

PAPER_STYLE       = "sheet"
PAPER_COLOR       = "#000000"
DESK_COLOR        = "#000E07"
SKIP_PAPER_WHITE  = True   # white background of the picture is left as paper instead of painted white

# ---- Colour pencil ----
COLOR_PENCIL = True        # the pencil body changes to the colour it is drawing with

# ---- Heads-up display, timer, keys ----
SHOW_HUD = True            # progress + time written in the window
START_SPEED_LEVEL = 5      # 1 (slowest) ... 9 (fastest); level 5 = PEN_UPDATE_EVERY / FRAME_SLEEP above
# Keys while drawing:  SPACE = pause / resume     + or - (also Up / Down) = speed

SPEED_LEVELS = [
    (1, 0.012), (1, 0.005), (2, 0.002), (3, 0.001),
    (PEN_UPDATE_EVERY, FRAME_SLEEP),
    (10, 0.0), (16, 0.0), (30, 0.0), (60, 0.0),
]

# ============================================================
# FILE PICKER (if no path given)
# ============================================================

def pick_image_file():
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="Choose an image",
        filetypes=[
            ("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff *.gif"),
            ("PNG",  "*.png"),
            ("JPEG", "*.jpg *.jpeg"),
            ("BMP",  "*.bmp"),
            ("WEBP", "*.webp"),
            ("All files", "*.*"),
        ],
    )
    root.destroy()
    return path

if IMAGE_PATH is None or not os.path.isfile(IMAGE_PATH):
    IMAGE_PATH = pick_image_file()
    if not IMAGE_PATH:
        raise SystemExit("No image selected. Exiting.")

print(f"Using image: {IMAGE_PATH}")

# ============================================================
# LOAD + FLATTEN ALPHA
# ============================================================

print("Loading image...")
img_raw = cv2.imread(IMAGE_PATH, cv2.IMREAD_UNCHANGED)
if img_raw is None:
    raise FileNotFoundError(f"Could not read image: {IMAGE_PATH}")

# Handle various channel layouts
if img_raw.ndim == 2:
    # grayscale -> BGR
    img = cv2.cvtColor(img_raw, cv2.COLOR_GRAY2BGR)
elif img_raw.shape[2] == 4:
    print("  -> transparent image, flattening to white")
    alpha = img_raw[:, :, 3]
    img = img_raw[:, :, :3].copy()
    img[alpha < 128] = (255, 255, 255)
elif img_raw.shape[2] == 3:
    img = img_raw.copy()
else:
    raise ValueError(f"Unsupported image shape: {img_raw.shape}")

h0, w0 = img.shape[:2]
scale = min(MAX_IMAGE_W / w0, MAX_IMAGE_H / h0, 1)
new_w, new_h = max(1, int(w0 * scale)), max(1, int(h0 * scale))
img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

if SATURATION_BOOST != 1.0:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * SATURATION_BOOST, 0, 255)
    img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

# ============================================================
# FILL PIPELINE
# ============================================================

print("Smoothing...")
fill_src = cv2.bilateralFilter(img, 9, 75, 75)
# medianBlur requires odd kernel
bk = BLUR_KERNEL if BLUR_KERNEL % 2 == 1 else BLUR_KERNEL + 1
fill_src = cv2.medianBlur(fill_src, bk)

print(f"Quantizing to {NUM_COLORS} colors...")
Z = fill_src.reshape(-1, 3).astype(np.float32)
criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
_, labels, centers = cv2.kmeans(Z, NUM_COLORS, None, criteria, 10,
                                cv2.KMEANS_PP_CENTERS)
centers = np.uint8(centers)
quantized = centers[labels.flatten()].reshape(img.shape)
quantized = cv2.medianBlur(quantized, 5)

# ============================================================
# REGIONS
# ============================================================

print("Finding regions...")
regions = []

for i in range(NUM_COLORS):
    color_bgr = centers[i]
    mask = np.all(quantized == color_bgr, axis=2).astype(np.uint8) * 255

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=1)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
    for c in contours:
        area = cv2.contourArea(c)
        if area < MIN_REGION_AREA:
            continue
        b, g, r = color_bgr

        # leave the white background of the picture as bare paper
        if SKIP_PAPER_WHITE and PAPER_STYLE != "white":
            bx, by, bw, bh = cv2.boundingRect(c)
            touches_border = (bx <= 1 or by <= 1 or
                              bx + bw >= new_w - 1 or by + bh >= new_h - 1)
            if touches_border and min(int(r), int(g), int(b)) >= 235:
                continue

        full_pts = [tuple(int(v) for v in p[0]) for p in c]
        approx = cv2.approxPolyDP(c, APPROX_EPSILON, closed=True)
        simple_pts = [tuple(int(v) for v in p[0]) for p in approx]
        if len(simple_pts) < 3:
            continue
        regions.append((int(r), int(g), int(b), full_pts, simple_pts, area))

print(f"Found {len(regions)} regions.")
regions.sort(key=lambda r: r[5], reverse=True)

# ============================================================
# EDGE PIPELINE
# ============================================================

print("Building edge map...")
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
gray = cv2.bilateralFilter(gray, 5, 40, 40)
edges = cv2.Canny(gray, CANNY_LOW, CANNY_HIGH)
edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE,
                        np.ones((2, 2), np.uint8), iterations=1)

edge_contours, _ = cv2.findContours(edges, cv2.RETR_LIST,
                                    cv2.CHAIN_APPROX_NONE)
edge_polys = []
for c in edge_contours:
    if cv2.arcLength(c, closed=False) < EDGE_MIN_LEN:
        continue
    approx = cv2.approxPolyDP(c, EDGE_APPROX_EPS, closed=False)
    pts = [tuple(int(v) for v in p[0]) for p in approx]
    if len(pts) >= 2:
        edge_polys.append(pts)

print(f"Found {len(edge_polys)} edge polylines.")

# Image used to pick the outline colours (slightly blurred so the colour is stable)
_cb = OUTLINE_COLOR_BLUR if OUTLINE_COLOR_BLUR % 2 == 1 else OUTLINE_COLOR_BLUR + 1
edge_color_img = cv2.blur(img, (_cb, _cb))

# ============================================================
# DRAW ORDER
# ============================================================

def order_regions(regs, mode):
    """Re-order the regions. A region inside a bigger one always comes after it."""
    if mode == "big_first":
        return sorted(regs, key=lambda r: r[5], reverse=True)

    def centroid(r):
        pts = np.array(r[3], dtype=np.float32)
        return pts.mean(axis=0)          # (x, y) in image coordinates

    cx0, cy0 = new_w / 2, new_h / 2
    if mode == "small_first":
        ordered = sorted(regs, key=lambda r: r[5])
    elif mode == "top_to_bottom":
        ordered = sorted(regs, key=lambda r: centroid(r)[1])
    elif mode == "bottom_to_top":
        ordered = sorted(regs, key=lambda r: -centroid(r)[1])
    elif mode == "left_to_right":
        ordered = sorted(regs, key=lambda r: centroid(r)[0])
    elif mode == "center_out":
        ordered = sorted(regs, key=lambda r: math.hypot(centroid(r)[0] - cx0,
                                                        centroid(r)[1] - cy0))
    elif mode == "random":
        ordered = list(regs)
        random.Random(RANDOM_SEED).shuffle(ordered)
    else:
        print(f"Unknown REGION_ORDER '{mode}', using big_first")
        return sorted(regs, key=lambda r: r[5], reverse=True)

    # nesting: find which bigger regions fully contain each region
    n = len(ordered)
    cnts = [np.array(r[3], dtype=np.int32).reshape(-1, 1, 2) for r in ordered]
    parents = [set() for _ in range(n)]
    for j in range(n):
        pj = ordered[j][3]
        samples = [pj[0], pj[len(pj) // 2], pj[-1]]
        for i in range(n):
            if i == j or ordered[i][5] <= ordered[j][5]:
                continue
            if all(cv2.pointPolygonTest(cnts[i], (float(x), float(y)), True) > 3
                   for x, y in samples):
                parents[j].add(i)

    result, done, remaining = [], set(), list(range(n))
    while remaining:
        for idx in remaining:
            if parents[idx] <= done:
                result.append(idx)
                done.add(idx)
                remaining.remove(idx)
                break
        else:                               # safety net, should not happen
            idx = remaining.pop(0)
            result.append(idx)
            done.add(idx)
    return [ordered[i] for i in result]

def order_edges(polys, mode):
    if mode == "as_found":
        return polys

    def centroid(p):
        a = np.array(p, dtype=np.float32)
        return a.mean(axis=0)

    cx0, cy0 = new_w / 2, new_h / 2
    if mode == "top_to_bottom":
        return sorted(polys, key=lambda p: centroid(p)[1])
    if mode == "left_to_right":
        return sorted(polys, key=lambda p: centroid(p)[0])
    if mode == "center_out":
        return sorted(polys, key=lambda p: math.hypot(centroid(p)[0] - cx0,
                                                      centroid(p)[1] - cy0))
    if mode == "long_first":
        return sorted(polys, key=lambda p: len(p), reverse=True)
    if mode == "short_first":
        return sorted(polys, key=lambda p: len(p))
    if mode == "random":
        out = list(polys)
        random.Random(RANDOM_SEED).shuffle(out)
        return out
    print(f"Unknown EDGE_ORDER '{mode}', using as_found")
    return polys

regions = order_regions(regions, REGION_ORDER)
edge_polys = order_edges(edge_polys, EDGE_ORDER)

# ============================================================
# SMOOTHING MATH
# ============================================================

def angle_between(a, b, c):
    ab = (a[0] - b[0], a[1] - b[1])
    cb = (c[0] - b[0], c[1] - b[1])
    dot = ab[0] * cb[0] + ab[1] * cb[1]
    mag = math.hypot(*ab) * math.hypot(*cb)
    if mag == 0:
        return 180
    return math.degrees(math.acos(max(-1, min(1, dot / mag))))

def split_into_segments(pts, corner_angle_deg):
    if len(pts) < 3:
        return [pts]
    segments = []
    current = [pts[0]]
    for i in range(1, len(pts) - 1):
        ang = angle_between(pts[i - 1], pts[i], pts[i + 1])
        if ang < corner_angle_deg:
            current.append(pts[i])
            if len(current) >= 2:
                segments.append(current)
            current = [pts[i]]
        else:
            current.append(pts[i])
    current.append(pts[-1])
    if len(current) >= 2:
        segments.append(current)
    return segments

def catmull_rom(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * ((2 * p1[0]) +
               (-p0[0] + p2[0]) * t +
               (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
               (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
    y = 0.5 * ((2 * p1[1]) +
               (-p0[1] + p2[1]) * t +
               (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
               (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
    return (x, y)

def smooth_curve(pts, subdivisions):
    if len(pts) < 3:
        return pts
    p = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for s in range(subdivisions):
            t = s / subdivisions
            out.append(catmull_rom(p0, p1, p2, p3, t))
    out.append(p[-2])
    return out

# ============================================================
# TURTLE
# ============================================================

screen = turtle.Screen()
base_title = os.path.basename(IMAGE_PATH)
screen.title(f"Smooth cartoon turtle — {base_title}")
screen.setup(SCREEN_W, SCREEN_H)
screen.tracer(0)              # we redraw manually, so the pencil moves smoothly
screen.colormode(1.0)

half_w, half_h = SCREEN_W / 2, SCREEN_H / 2
screen.setworldcoordinates(-half_w, -half_h, half_w, half_h)

margin = 40
fit = min((SCREEN_W - 2 * margin) / new_w,
          (SCREEN_H - 2 * margin) / new_h)
draw_w, draw_h = new_w * fit, new_h * fit

# ------------------------------------------------------------
# PAPER BACKGROUND
# ------------------------------------------------------------

def draw_rect(pen, x0, y0, x1, y1, fill, outline=None, width=1):
    pen.penup()
    pen.goto(x0, y0)
    pen.color(outline if outline else fill, fill)
    pen.pensize(width)
    pen.begin_fill()
    pen.pendown()
    pen.goto(x1, y0)
    pen.goto(x1, y1)
    pen.goto(x0, y1)
    pen.goto(x0, y0)
    pen.end_fill()
    pen.penup()

if PAPER_STYLE == "sheet":
    screen.bgcolor(DESK_COLOR)
    paper = turtle.Turtle()
    paper.hideturtle()
    paper.speed(0)
    pad = 10
    x0, x1 = -draw_w / 2 - pad, draw_w / 2 + pad
    y0, y1 = -draw_h / 2 - pad, draw_h / 2 + pad
    draw_rect(paper, x0 + 7, y0 - 7, x1 + 7, y1 - 7, "#11341C")            # shadow
    draw_rect(paper, x0, y0, x1, y1, PAPER_COLOR, "#A2CBB6", 2)              # sheet
    HUD_COLOR = "#7DAB95"
elif PAPER_STYLE == "full":
    screen.bgcolor(PAPER_COLOR)
    HUD_COLOR = "#3A2F25"
else:
    screen.bgcolor("white")
    HUD_COLOR = "#241D17"

# ------------------------------------------------------------
# PENCIL SHAPES (tip of the pencil is exactly where the line is drawn)
# ------------------------------------------------------------

PENCIL_COLOR_STEP = 32          # pencil colours are rounded to this step

def build_pencil(body_fill, body_edge):
    ang = math.radians(60)                 # pencil leans up and to the right
    ux, uy = math.cos(ang), math.sin(ang)  # along the pencil
    vx, vy = -uy, ux                       # across the pencil

    def P(a, w):
        # point 'a' along the pencil and 'w' across it, in turtle-shape coordinates
        sx = a * ux + w * vx
        sy = a * uy + w * vy
        return (-sy, sx)

    pencil = turtle.Shape("compound")
    pencil.addcomponent([P(0, 0), P(14, 4.5), P(14, -4.5)], "#F2C894", "#5A4632")   # wood tip
    pencil.addcomponent([P(0, 0), P(4.5, 1.6), P(4.5, -1.6)], "#333333", "#333333") # lead
    pencil.addcomponent([P(14, 4.5), P(56, 4.5), P(56, -4.5), P(14, -4.5)],
                        body_fill, body_edge)                                       # body
    pencil.addcomponent([P(56, 4.5), P(62, 4.5), P(62, -4.5), P(56, -4.5)],
                        "#C0C0C0", "#666666")                                       # metal band
    pencil.addcomponent([P(62, 4.5), P(70, 4.5), P(70, -4.5), P(62, -4.5)],
                        "#F59AB0", "#8A4A5A")                                       # eraser
    return pencil

_pencil_shapes = set()
_current_pencil_key = None

def ensure_pencil_shape(key):
    name = "pencil_%d_%d_%d" % key
    if name not in _pencil_shapes:
        half = PENCIL_COLOR_STEP // 2
        rgb = [min(255, k * PENCIL_COLOR_STEP + half) for k in key]
        body = "#%02x%02x%02x" % tuple(rgb)
        edge = "#%02x%02x%02x" % tuple(int(c * 0.5) for c in rgb)
        screen.register_shape(name, build_pencil(body, edge))
        _pencil_shapes.add(name)
    return name

def set_pencil_color(r, g, b):
    """Make the pencil body match the colour (0-255) it is drawing with."""
    global _current_pencil_key
    if not (SHOW_PEN and COLOR_PENCIL):
        return
    key = (int(r) // PENCIL_COLOR_STEP,
           int(g) // PENCIL_COLOR_STEP,
           int(b) // PENCIL_COLOR_STEP)
    if key == _current_pencil_key:
        return
    t.shape(ensure_pencil_shape(key))
    _current_pencil_key = key

t = turtle.Turtle()
t.speed(TURTLE_SPEED)
t.penup()
if SHOW_PEN:
    screen.register_shape("pencil_default", build_pencil("#F6C945", "#7A5F10"))
    t.shape("pencil_default")
    t.showturtle()
else:
    t.hideturtle()

# ------------------------------------------------------------
# HUD, TIMER, PAUSE, SPEED
# ------------------------------------------------------------

hud = turtle.Turtle()
hud.hideturtle()
hud.speed(0)
hud.penup()
hud.color("white", HUD_COLOR)

HUD_FONT = ("Courier New", 16, "bold")
HUD_FONT_SMALL = ("Courier New", 11, "normal")

speed_level = min(max(START_SPEED_LEVEL, 1), len(SPEED_LEVELS)) - 1
paused = False
pause_started = None
pause_total = 0.0
start_time = time.time()

stage_name = "Starting"
stage_done = 0
stage_total = 0
overall_done = 0
overall_total = len(regions) + len(edge_polys) * (2 if DRAW_MODE == "sketch_first" else 1)
sketching = False
_last_hud = 0.0

def elapsed():
    now = pause_started if (paused and pause_started) else time.time()
    return now - start_time - pause_total

def fmt_time(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"

def refresh_hud(force=False):
    global _last_hud
    now = time.time()
    if not force and now - _last_hud < 0.2:
        return
    _last_hud = now
    pct = int(100 * overall_done / overall_total) if overall_total else 100
    state = "  [PAUSED]" if paused else ""
    screen.title(f"{stage_name} {stage_done}/{stage_total} - {pct}% - "
                 f"{fmt_time(elapsed())} - {base_title}")
    if SHOW_HUD:
        line = (f"{stage_name} {stage_done}/{stage_total}  |  {pct}%  |  "
                f"{fmt_time(elapsed())}  |  speed {speed_level + 1}/{len(SPEED_LEVELS)}{state}")
        hud.clear()
        hud.goto(-half_w + 12, half_h - 28)
        hud.write(line, font=HUD_FONT)
        hud.goto(-half_w + 12, -half_h + 8)
        hud.write("SPACE = pause / resume     + / - = speed", font=HUD_FONT_SMALL)

def set_stage(name, total):
    global stage_name, stage_done, stage_total
    stage_name, stage_done, stage_total = name, 0, total
    refresh_hud(force=True)

def stage_step():
    global stage_done, overall_done
    stage_done += 1
    overall_done += 1

def toggle_pause():
    global paused, pause_started, pause_total
    if not paused:
        paused = True
        pause_started = time.time()
    else:
        paused = False
        pause_total += time.time() - pause_started
        pause_started = None

def speed_up():
    global speed_level
    speed_level = min(speed_level + 1, len(SPEED_LEVELS) - 1)

def slow_down():
    global speed_level
    speed_level = max(speed_level - 1, 0)

for key in ("space",):
    screen.onkey(toggle_pause, key)
for key in ("plus", "equal", "KP_Add", "Up"):
    screen.onkey(speed_up, key)
for key in ("minus", "KP_Subtract", "Down"):
    screen.onkey(slow_down, key)
screen.listen()

def to_turtle(x, y):
    return (-draw_w / 2 + x * fit, draw_h / 2 - y * fit)

_move_count = 0

def move(x, y):
    """Move the pencil and redraw every few moves (speed set with the + / - keys)."""
    global _move_count
    t.goto(x, y)
    _move_count += 1
    every, nap = SPEED_LEVELS[speed_level]
    if sketching:
        every *= SKETCH_SPEED_FACTOR
    if _move_count % every == 0:
        refresh_hud()
        screen.update()
        if nap:
            time.sleep(nap)
        while paused:                       # SPACE pressed: wait here
            refresh_hud(force=True)
            screen.update()
            time.sleep(0.05)

def set_outline_color(x, y):
    """Set the pen colour from the original image at image position (x, y)."""
    if sketching:
        t.pencolor(*SKETCH_COLOR)
        set_pencil_color(170, 170, 170)
        return
    if OUTLINE_COLOR_MODE != "image":
        t.pencolor(0, 0, 0)
        set_pencil_color(40, 40, 40)
        return
    xi = min(max(int(round(x)), 0), new_w - 1)
    yi = min(max(int(round(y)), 0), new_h - 1)
    b, g, r = edge_color_img[yi, xi]
    k = OUTLINE_DARKEN / 255
    t.pencolor(float(r) * k, float(g) * k, float(b) * k)
    set_pencil_color(r, g, b)

def draw_smooth_polyline(pts, corner_angle_deg, close=False):
    if len(pts) < 2:
        return
    if close and pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    segs = split_into_segments(pts, corner_angle_deg)
    X, Y = to_turtle(*pts[0])
    set_outline_color(*pts[0])
    t.penup(); t.goto(X, Y); t.pendown()
    for seg in segs:
        if len(seg) == 2:
            set_outline_color(*seg[1])
            X, Y = to_turtle(*seg[1])
            move(X, Y)
        else:
            smooth = smooth_curve(seg, CURVE_SUBDIVISIONS)
            for p in smooth[1:]:
                set_outline_color(*p)
                X, Y = to_turtle(*p)
                move(X, Y)

# ============================================================
# DRAW FILLS
# ============================================================

def draw_fills():
    print("Filling regions (accurate)...")
    set_stage("Colouring", len(regions))
    for i, (r, g, b, full_pts, simple_pts, area) in enumerate(regions):
        t.fillcolor(r / 255, g / 255, b / 255)
        t.pencolor(r / 255, g / 255, b / 255)
        t.pensize(1)
        set_pencil_color(r, g, b)

        t.begin_fill()
        X, Y = to_turtle(*full_pts[0])
        t.penup(); t.goto(X, Y); t.pendown()
        for p in full_pts[1:]:
            move(*to_turtle(*p))
        move(*to_turtle(*full_pts[0]))
        t.end_fill()

        stage_step()
        screen.update()

# ============================================================
# DRAW OUTLINES (final coloured outlines, or the grey pencil sketch)
# ============================================================

def draw_outlines(sketch=False):
    global sketching
    print("Drawing pencil sketch..." if sketch else "Drawing smooth outlines...")
    sketching = sketch
    t.pensize(SKETCH_WIDTH if sketch else OUTLINE_WIDTH)
    set_stage("Sketching" if sketch else "Outlining", len(edge_polys))

    for i, poly in enumerate(edge_polys):
        draw_smooth_polyline(poly, EDGE_CORNER_ANGLE_DEG, close=False)
        stage_step()

    sketching = False
    t.penup()

# ============================================================
# RUN
# ============================================================

start_time = time.time()
screen.update()

if DRAW_MODE == "sketch_first":
    draw_outlines(sketch=True)
    draw_fills()
    draw_outlines(sketch=False)
else:
    draw_fills()
    draw_outlines(sketch=False)

t.penup()
if HIDE_PEN_AT_END:
    t.hideturtle()

stage_name, stage_done, stage_total = "DONE", overall_done, overall_done
overall_done = overall_total
refresh_hud(force=True)
screen.update()
print(f"DONE! Total drawing time: {fmt_time(elapsed())}")
turtle.done()