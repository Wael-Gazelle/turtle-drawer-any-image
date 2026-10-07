(() => {
const $ = id => document.getElementById(id), S = 2, MAXPX = 1200;
const PRESETS = {
  Soft: {sharpness: 30, colors: 8, texture: 75, detail: 30},
  Balanced: {sharpness: 50, colors: 12, texture: 50, detail: 50},
  Crisp: {sharpness: 75, colors: 16, texture: 25, detail: 75},
};
const cv = $("cv"), ctx = cv.getContext("2d");
const base = document.createElement("canvas"), bctx = base.getContext("2d");
let blob, ctl, res, ops = [], cum = [], info = {}, total = 0, pos = 0, done = 0, rate = 1;
let speed = 1, elapsed = 0, last = 0, playing = false, first = true, timer = 0;

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
  const sketch = $("draw_mode").value === "sketch", skip = $("paper_style").value !== "white";
  const K = sketch ? res.edges.map(e => ({k: "sketch", p: e.p, c: [150, 150, 150]})) : [];
  const F = res.regions.filter(r => !(skip && r.w)).map(r => ({k: "fill", p: r.p, c: r.c}));
  const L = res.edges.map(e => ({k: "line", p: e.p, c: e.c}));
  ops = [...K, ...F, ...L]; cum = []; info = {}; total = 0;
  ops.forEach((o, i) => {
    o.n = o.p.length / 2; cum.push(total); total += o.n;
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
  if (o.k === "fill") {
    c.fillStyle = c.strokeStyle = rgb(o.c); c.lineWidth = 1;
    if (n >= o.n) { c.closePath(); c.fill(); }
  } else { c.strokeStyle = rgb(o.c); c.lineWidth = o.k === "sketch" ? 1 : 1.2; }
  c.stroke();
}

function tip(x, y, col) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(-Math.PI / 3);
  const body = $("color_pencil").checked ? rgb(col) : "#f2b705";
  ctx.fillStyle = "#f2c894"; ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(9, -3); ctx.lineTo(9, 3); ctx.fill();
  ctx.fillStyle = body; ctx.fillRect(9, -3, 30, 6);
  ctx.fillStyle = "#c0c0c0"; ctx.fillRect(39, -3, 4, 6);
  ctx.fillStyle = "#f59ab0"; ctx.fillRect(43, -3, 6, 6);
  ctx.strokeStyle = "rgba(0,0,0,.45)"; ctx.lineWidth = .6; ctx.strokeRect(9, -3, 40, 6);
  ctx.restore();
}

function render() {
  while (done < ops.length && cum[done] + ops[done].n <= pos) { draw(bctx, ops[done], ops[done].n); done++; }
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.drawImage(base, 0, 0); ctx.setTransform(S, 0, 0, S, 0, 0);
  if (done < ops.length) {
    const o = ops[done], n = Math.floor(pos - cum[done]), m = Math.max(n, 1);
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
  if (playing) requestAnimationFrame(frame);
}
function play(on) {
  if (on && pos >= total) restart(false);
  playing = on;
  if (on) { last = performance.now(); requestAnimationFrame(frame); }
  render();
}
function restart(auto) { resetBase(); pos = 0; elapsed = 0; auto ? play(true) : render(); }
function seek(p) { if (p < pos) resetBase(); pos = p; render(); }
function setSpeed(v) { speed = Math.min(8, Math.max(0.25, v)); $("speed").value = speed; $("o_speed").textContent = speed + "x"; }

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
    if (chips.length === 10) break;
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
$("scrub").addEventListener("input", e => seek(total * e.target.value / 1000));
$("speed").addEventListener("input", e => setSpeed(+e.target.value));

document.querySelectorAll("[data-k]").forEach(el => el.addEventListener("input", () => {
  const out = $("o_" + el.id); if (out) out.textContent = el.value;
  clearTimeout(timer); timer = setTimeout(run, 400);          // wait for the slider to settle
}));
document.querySelectorAll("[data-f]").forEach(el => el.addEventListener("change", () => {
  $("paper").dataset.paper = $("paper_style").value;
  if (res) { build(); playing = false; pos = total; render(); }
}));

function applyPreset(name) {
  Object.entries(PRESETS[name]).forEach(([k, v]) => { $(k).value = v; $("o_" + k).textContent = v; });
  clearTimeout(timer); run();
}
document.querySelectorAll(".preset").forEach(b => b.addEventListener("click", () => applyPreset(b.dataset.p)));
$("reset").addEventListener("click", () => applyPreset("Balanced"));

$("theme").addEventListener("click", () => {
  const d = document.documentElement;
  const dark = (d.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  d.dataset.theme = dark ? "light" : "dark";
});

document.addEventListener("keydown", e => {
  if (!res || /^(INPUT|SELECT)$/.test(e.target.tagName) && e.target.type !== "range") return;
  if (e.key === " ") { e.preventDefault(); play(!playing); }
  else if (e.key === "+" || e.key === "=") setSpeed(speed * 1.25);
  else if (e.key === "-") setSpeed(speed / 1.25);
});
})();
