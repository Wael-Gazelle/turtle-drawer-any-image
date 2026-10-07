(() => {
const $ = id => document.getElementById(id), S = 2, MAXPX = 1200;
/* paper presets: background colour + a matching sketch colour (both can be changed afterwards with the colour pickers) */
const PAPERS = {
  sheet:   {bg: "#fffdf6", ink: [120, 120, 120]},
  full:    {bg: "#f3ead3", ink: [120, 120, 120]},
  white:   {bg: "#ffffff", ink: [120, 120, 120]},
  ancient: {bg: "#e6cf9c", ink: [110, 84, 48]},
  kraft:   {bg: "#b98f5e", ink: [70, 45, 25]},
  gray:    {bg: "#9a9a9a", ink: [55, 55, 55]},
  black:   {bg: "#15151a", ink: [225, 225, 225]},
  red:     {bg: "#b3262d", ink: [245, 225, 225]},
  blue:    {bg: "#1d3f8f", ink: [225, 232, 250]},
};
const hex = c => "#" + c.map(v => Math.round(v).toString(16).padStart(2, "0")).join("");
const unhex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const autoInk = bg => {                                    // a readable sketch colour for any background
  const [r, g, b] = unhex(bg), L = .299 * r + .587 * g + .114 * b;
  return L >= 190 ? [120, 120, 120] : L >= 130 ? [55, 55, 55] : [235, 235, 235];
};

/* ---------- tools: how they look and how they draw (the tool always takes the colour of what it draws) ---------- */
const TOOLS = {
  pencil: {w: {sketch: 1, line: 1.2}, a: {sketch: 1, line: 1},
    draw(c, body) {
      c.fillStyle = "#f2c894"; c.beginPath(); c.moveTo(0, 0); c.lineTo(9, -3); c.lineTo(9, 3); c.fill();
      c.fillStyle = "#3b3b3b"; c.beginPath(); c.moveTo(0, 0); c.lineTo(3, -1.1); c.lineTo(3, 1.1); c.fill();
      c.fillStyle = body; c.fillRect(9, -3, 30, 6);
      c.fillStyle = "#c0c0c0"; c.fillRect(39, -3, 4, 6);
      c.fillStyle = "#f59ab0"; c.fillRect(43, -3, 6, 6);
      c.strokeStyle = "rgba(0,0,0,.45)"; c.lineWidth = .6; c.strokeRect(9, -3, 40, 6);
    }},
  brush: {w: {sketch: 2.4, line: 2.8}, a: {sketch: .7, line: .95},
    draw(c, body) {
      c.fillStyle = body; c.beginPath(); c.moveTo(0, 0); c.quadraticCurveTo(5, -5, 15, -3.6); c.lineTo(15, 3.6); c.quadraticCurveTo(5, 5, 0, 0); c.fill();
      c.fillStyle = "#b9bcc6"; c.fillRect(15, -3.8, 11, 7.6);
      c.fillStyle = "#7a4a22"; c.beginPath(); c.moveTo(26, -3); c.lineTo(66, -1.6); c.lineTo(66, 1.6); c.lineTo(26, 3); c.fill();
      c.strokeStyle = "rgba(0,0,0,.45)"; c.lineWidth = .6; c.strokeRect(15, -3.8, 11, 7.6);
    }},
};

const cv = $("cv"), ctx = cv.getContext("2d");
const base = document.createElement("canvas"), bctx = base.getContext("2d");
let blob, ctl, res, ops = [], cum = [], info = {}, total = 0, pos = 0, done = 0, rate = 1, st = {w: {}, a: {}};
let speed = 1, elapsed = 0, last = 0, playing = false, first = true, timer = 0, raf = 0, inkTimer = 0;

const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
const fmt = t => `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const msg = t => { $("msg").textContent = t || ""; };

/* ---------- upload (the image stays in this tab; the server never stores it) ---------- */
async function pick(file) {
  msg("");
  if (!file) return;
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return msg("Please choose a PNG, JPEG or WebP image.");
  try {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, MAXPX / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    const g = c.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(bmp, 0, 0, c.width, c.height);
    blob = await new Promise(r => c.toBlob(r, "image/jpeg", 0.9));
    first = true; $("hero").hidden = true; $("studio").hidden = false;
    run();
  } catch { msg("That file could not be read as an image."); }
}

async function run() {
  if (ctl) ctl.abort();
  const mine = ctl = new AbortController();
  $("spin").hidden = false; msg("");
  const q = new URLSearchParams();
  document.querySelectorAll("[data-k]").forEach(e => q.set(e.id, e.value));
  try {
    const r = await fetch("/api/process?" + q, {method: "POST", body: blob, signal: mine.signal,
      headers: {"Content-Type": "application/octet-stream"}});
    if (!r.ok) {
      const d = (await r.json().catch(() => ({}))).detail;
      throw new Error(typeof d === "string" ? d : "Those settings were not accepted.");
    }
    load(await r.json());
  } catch (e) { if (e.name !== "AbortError") msg(e.message); }
  finally { if (ctl === mine) $("spin").hidden = true; }
}

/* ---------- drawing ---------- */
function load(data) {
  res = data;
  cv.width = base.width = res.w * S; cv.height = base.height = res.h * S;
  fx.width = cv.width; fx.height = cv.height;
  build(); palette();
  if (first) { first = false; restart(true); }
  else { playing = false; pos = total; render(); }
}

function build() {
  const T = TOOLS[$("tool").value] || TOOLS.pencil, k = $("thick").value / 100;
  st = {w: {sketch: T.w.sketch * k, line: T.w.line * k}, a: T.a};
  const sketch = $("draw_mode").value === "sketch", skip = $("paper_style").value !== "white";
  const ink = unhex($("sketch_color").value);
  const K = sketch ? (res.sketch || res.edges).map(e => ({k: "sketch", p: e.p, c: ink})) : [];
  const F = res.regions.filter(r => !(skip && r.w)).map(r => ({k: "fill", p: r.p, c: r.c}));
  const L = res.edges.map(e => ({k: "line", p: e.p, c: e.c}));
  ops = [...K, ...F, ...L]; cum = []; info = {}; total = 0;
  const pts = kind => ops.filter(o => o.k === kind).reduce((a, o) => a + o.p.length / 2, 0);
  const sk = pts("sketch"), rest = pts("fill") + pts("line");
  const scale = sk ? Math.max(1, 0.4 * rest / (0.6 * sk)) : 1;   // the sketch gets about 40% of the timeline
  ops.forEach((o, i) => {
    o.n = o.p.length / 2;
    o.len = o.k === "sketch" ? o.n * scale : o.n;                // time this step takes
    cum.push(total); total += o.len;
    (info[o.k] ||= {first: i, count: 0}).count++;
  });
  rate = Math.max(200, Math.min(4000, total / 30));      // 1x = about 30 seconds
  resetBase();
}

function resetBase() { base.width = cv.width; bctx.setTransform(S, 0, 0, S, 0, 0); done = 0; }

function path(c, p, n) {                                  // smooth curve through n points
  c.beginPath(); c.moveTo(p[0], p[1]);
  for (let i = 1; i < n - 1; i++)
    c.quadraticCurveTo(p[2 * i], p[2 * i + 1], (p[2 * i] + p[2 * i + 2]) / 2, (p[2 * i + 1] + p[2 * i + 3]) / 2);
  if (n > 1) c.lineTo(p[2 * n - 2], p[2 * n - 1]);
}

function draw(c, o, n) {
  path(c, o.p, n);
  c.lineCap = c.lineJoin = "round";
  if (o.k === "fill") {
    c.fillStyle = c.strokeStyle = rgb(o.c); c.lineWidth = 1;
    if (n >= o.n) { c.closePath(); c.fill(); }
  } else { c.strokeStyle = rgb(o.c); c.lineWidth = st.w[o.k]; c.globalAlpha = st.a[o.k]; }
  c.stroke(); c.globalAlpha = 1;
}

function tip(x, y, col) {
  const tool = $("tool").value;
  if (tool === "off") return;
  const sc = Math.max(.8, Math.min(2.4, res.w / 700)) * $("tool_size").value / 100;
  ctx.save(); ctx.translate(x, y); ctx.scale(sc, sc); ctx.rotate(-Math.PI / 3);
  TOOLS[tool].draw(ctx, rgb(col));
  ctx.restore();
}

function render() {
  while (done < ops.length && cum[done] + ops[done].len <= pos) { draw(bctx, ops[done], ops[done].n); done++; }
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.drawImage(base, 0, 0); ctx.setTransform(S, 0, 0, S, 0, 0);
  if (done < ops.length) {
    const o = ops[done], n = Math.floor((pos - cum[done]) * o.n / o.len), m = Math.max(n, 1);
    if (n >= 2) draw(ctx, o, n);
    tip(o.p[2 * m - 2], o.p[2 * m - 1], o.c);
  }
  ui();
}

function ui() {
  const o = ops[Math.min(done, ops.length - 1)] || {k: "line"}, inf = info[o.k] || {first: 0, count: 0};
  const name = {sketch: "Sketching", fill: "Colouring", line: "Outlining"}[o.k];
  const pct = total ? Math.floor(100 * pos / total) : 100;
  $("label").textContent = pos >= total ? `Done - ${fmt(elapsed)}`
    : `${name} ${Math.min(inf.count, done - inf.first + 1)}/${inf.count} - ${pct}% - ${fmt(elapsed)}`;
  $("scrub").value = total ? Math.round(1000 * pos / total) : 0;
  $("play").textContent = playing ? "Pause" : pos >= total ? "Replay" : "Play";
}

function frame(t) {
  if (!playing) return;
  const dt = Math.min((t - last) / 1000, 0.1); last = t; elapsed += dt;
  pos = Math.min(total, pos + dt * rate * speed);
  if (pos >= total) { playing = false; celebrate(); }
  render();
  if (playing) raf = requestAnimationFrame(frame);
}
function play(on) {
  if (on && pos >= total) restart(false);
  const was = playing; playing = on;
  if (on && !was) { last = performance.now(); cancelAnimationFrame(raf); raf = requestAnimationFrame(frame); }   // never two loops
  render();
}
function restart(auto) { resetBase(); pos = 0; elapsed = 0; auto ? play(true) : render(); }
function seek(p) { if (p < pos) resetBase(); pos = p; render(); }
function setSpeed(v) { speed = Math.min(8, Math.max(0.25, v)); $("speed").value = speed; $("o_speed").textContent = speed + "x"; }

function save() {                                         // the finished drawing as a PNG
  if (!res) return;
  const c = document.createElement("canvas"); c.width = cv.width; c.height = cv.height;
  const g = c.getContext("2d");
  g.fillStyle = $("bg_color").value; g.fillRect(0, 0, c.width, c.height);
  g.setTransform(S, 0, 0, S, 0, 0);
  for (const o of ops) draw(g, o, o.n);
  c.toBlob(b => {
    const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "drawing.png";
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  });
}

/* ---------- palette chips and finish burst ---------- */
const fx = $("fx"), fctx = fx.getContext("2d");

function palette() {
  const seen = new Set(), chips = [];
  for (const r of res.regions) {
    const c = rgb(r.c);
    if (r.w || seen.has(c)) continue;
    seen.add(c);
    const s = document.createElement("span");
    s.className = "chip"; s.style.background = c; s.title = c;
    chips.push(s);
  }
  $("chips").replaceChildren(...chips);
}

function celebrate() {
  if (!res || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const cols = [...new Set(res.regions.map(r => rgb(r.c)))].slice(0, 8);
  if (!cols.length) return;
  const ps = Array.from({length: 46}, (_, i) => {
    const a = Math.random() * 6.283, v = 2 + Math.random() * 5;
    return {x: res.w / 2, y: res.h / 2, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 2,
            r: 2 + Math.random() * 4, c: cols[i % cols.length], life: 1};
  });
  fctx.setTransform(S, 0, 0, S, 0, 0);
  (function step() {
    fctx.clearRect(0, 0, res.w, res.h);
    let alive = false;
    for (const p of ps) {
      p.x += p.vx; p.y += p.vy; p.vy += 0.18; p.life -= 0.016;
      if (p.life <= 0) continue;
      alive = true; fctx.globalAlpha = p.life; fctx.fillStyle = p.c;
      fctx.beginPath(); fctx.arc(p.x, p.y, p.r, 0, 6.283); fctx.fill();
    }
    fctx.globalAlpha = 1;
    if (alive) requestAnimationFrame(step); else fctx.clearRect(0, 0, res.w, res.h);
  })();
}

/* ---------- controls ---------- */
$("drop").addEventListener("click", () => $("file").click());
$("drop").addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file").click(); } });
$("drop").addEventListener("dragover", e => { e.preventDefault(); $("drop").classList.add("over"); });
$("drop").addEventListener("dragleave", () => $("drop").classList.remove("over"));
$("drop").addEventListener("drop", e => { e.preventDefault(); $("drop").classList.remove("over"); pick(e.dataTransfer.files[0]); });
$("file").addEventListener("change", e => pick(e.target.files[0]));
$("again").addEventListener("click", () => {
  if (ctl) ctl.abort(); playing = false; blob = res = null; $("file").value = "";
  $("studio").hidden = true; $("hero").hidden = false; msg("");
});

$("play").addEventListener("click", () => play(!playing));
$("restart").addEventListener("click", () => restart(true));
$("end").addEventListener("click", () => { playing = false; pos = total; render(); });
$("save").addEventListener("click", save);
$("scrub").addEventListener("input", e => seek(total * e.target.value / 1000));
$("speed").addEventListener("input", e => setSpeed(+e.target.value));

/* data-k  = server settings (re-processes the image)
   data-f  = how the drawing is built/looks (rebuilt in the browser)
   data-u  = live options that only need a redraw (tool size) */
function keepPlace() {                                    // rebuild but stay at the same place in the drawing
  if (!res) return;
  const f = total ? pos / total : 1;
  build(); pos = Math.min(total, f * total); render();
}
document.querySelectorAll("[data-k]").forEach(el => el.addEventListener("input", () => {
  const out = $("o_" + el.id); if (out) out.textContent = el.value;
  clearTimeout(timer); timer = setTimeout(run, 400);          // wait for the slider to settle
}));
document.querySelectorAll("input[type=range][data-f]").forEach(el => el.addEventListener("input", () => {
  const out = $("o_" + el.id); if (out) out.textContent = el.value;
}));
document.querySelectorAll("[data-f]").forEach(el => el.addEventListener("change", () => {
  if (!res) return;
  if (el.id === "draw_mode") { build(); restart(true); return; }   // replay so the new order is seen
  keepPlace();
}));
document.querySelectorAll("[data-u]").forEach(el => el.addEventListener("input", () => {
  const out = $("o_" + el.id); if (out) out.textContent = el.value;
  if (res) render();
}));

/* ---------- paper, background colour and sketch colour ---------- */
function paperCss() {                                     // presets use the stylesheet, custom colours are set directly
  const p = $("paper"), v = $("paper_style").value;
  p.dataset.paper = v; p.style.background = v === "custom" ? $("bg_color").value : "";
}
$("paper_style").addEventListener("change", () => {
  const P = PAPERS[$("paper_style").value];
  if (P) { $("bg_color").value = P.bg; $("sketch_color").value = hex(P.ink); }   // a preset sets both colours
  paperCss(); keepPlace();
});
$("bg_color").addEventListener("input", () => { $("paper_style").value = "custom"; paperCss(); });   // live preview
$("bg_color").addEventListener("change", () => {
  $("sketch_color").value = hex(autoInk($("bg_color").value));    // pick a readable sketch colour, then you can change it
  keepPlace();
});
$("sketch_color").addEventListener("input", () => { clearTimeout(inkTimer); inkTimer = setTimeout(keepPlace, 120); });

function applyPreset(name) {
  Object.entries(PRESETS[name]).forEach(([k, v]) => { $(k).value = v; $("o_" + k).textContent = v; });
  clearTimeout(timer); run();
}
document.addEventListener("keydown", e => {
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) && e.target.type !== "range") return;
  if (!res) return;

  const step = rate * speed;   // one second of playback worth of progress

  if (e.key === " ") {
    e.preventDefault();
    play(!playing);
  }
  else if (e.key === "+" || e.key === "=") {
    setSpeed(speed * 1.25);
  }
  else if (e.key === "-") {
    setSpeed(speed / 1.25);
  }
  else if (e.key === "ArrowRight") {
    e.preventDefault();
    playing = false;
    seek(Math.min(total, pos + step));
  }
  else if (e.key === "ArrowLeft") {
    e.preventDefault();
    playing = false;
    seek(Math.max(0, pos - step));
  }
  else if (e.key === "End") {
    e.preventDefault();
    playing = false;
    pos = total;
    render();
  }
  else if (e.key === "Home") {
    e.preventDefault();
    playing = false;
    seek(0);
  }
});
})();
