const TITLE = '文具归位';
const PURPOSE = 'ad';
const LOOKS = {
  'papercut-collage': {
    grade: null, bloom: 0, texture: 'paper', vignette: 0.12, grain: 0, grainHold: 1, hold: 24,
    line: 0, steps: 2,
    palette: { bg: '#f3eadf', ink: '#2a211c', accent: '#c65a3a', dim: '#8d7b6a' },
  },
};
const LOOK_ID = 'papercut-collage';
const LOOK = LOOKS[LOOK_ID];
const FINISH = { shutter: null, weave: 0, tone: null };
const FPS = 24;
const BPM = 100;
const BEAT0 = 0;
const beat = (n) => BEAT0 + n * 60 / BPM;
const DURATION = 18;
const OWN_MUSIC = null;
const INSTRUMENTS = [];
const CAST = {};
const FORMULAS = {};
const PALETTE = {
  bg: '#f3eadf', ink: '#2a211c', accent: '#c65a3a', dim: '#8d7b6a',
  tile: '#f6efe4', grout: '#d9cbb8', counter: '#e4d2b8', speck: '#c9b396',
  cloth: '#3d6f8f', clothEdge: '#2a516b', water: '#e7c15a', plate: '#f7f1e8',
  sponge: '#d7a15e', bottle: '#f7f4ef', mist: '#efe2c2',
};
const TYPE = {
  lang: 'zh',
  roles: {
    display: { family: 'Droid Sans Fallback', files: { 400: 'fonts/DroidSansFallbackFull.ttf', 700: 'fonts/DroidSansFallbackFull.ttf' } },
    text: { family: 'Droid Sans Fallback', files: { 400: 'fonts/DroidSansFallbackFull.ttf', 700: 'fonts/DroidSansFallbackFull.ttf' } },
    mono: { family: 'Droid Sans Fallback', files: { 400: 'fonts/DroidSansFallbackFull.ttf' } },
  },
  check: {
    strings: { display: ['文具入盒', '定期查看'], text: ['贴上标签', '分类摆好'] },
    sizes: { text: 0.05 },
  },
};
const CUES = { sweep: 0, spray: beat(8), sink: beat(16), card: beat(25), end: DURATION };
const VO = [];
const CAPTIONS = null;
const CAPTION_STYLE = { role: 'text', accentRole: 'text', size: 0.05, caps: false, ink: PALETTE.ink, hi: PALETTE.ink, accent: PALETTE.accent, punch: 0 };
const SCENES = [
  { chapter: 'C1', from: CUES.sweep, to: CUES.spray, draw: counterSweep, action: 'a pencil slides across the desk into the box', amb: { kind: 'room', gain: 0.05 } },
  { chapter: 'C1', from: CUES.spray, to: CUES.sink, draw: sprayWipe, action: 'a label is pressed onto the box', in: { type: 'wipe', dur: 0.36, dir: 1 }, amb: { kind: 'room', gain: 0.045 } },
  { chapter: 'C1', from: CUES.sink, to: CUES.card, draw: rinsePlate, action: 'pens drop into sorted rows', in: { type: 'cut' }, amb: { kind: 'room', gain: 0.03 } },
  { chapter: 'C1', from: CUES.card, to: CUES.end, draw: threeChecks, action: 'three checks land one after another', in: { type: 'cut' }, amb: { kind: 'room', gain: 0.04 } },
];
const SFX = [
  { at: 0.2, voice: 'foley', kind: 'step', gain: 0.2, wet: 0.05 },
  { at: 2.2, voice: 'foley', kind: 'step', gain: 0.16, wet: 0.04 },
  { at: 5.4, voice: 'tick', gain: 0.18, wet: 0.04 },
  { at: 7.2, voice: 'foley', kind: 'tap', gain: 0.2, wet: 0.06 },
  { at: 10.4, voice: 'foley', kind: 'tap', gain: 0.18, wet: 0.05 },
  { at: 12.6, voice: 'foley', kind: 'step', gain: 0.16, wet: 0.04 },
  { at: 15.6, voice: 'tick', gain: 0.16, wet: 0.03 },
  { at: 16.4, voice: 'tick', gain: 0.14, wet: 0.03 },
];
const ROOM = { secs: 1.1, decay: 2.4, tone: 1400 };
const ARRANGEMENT = [
  { section: 'sweep', from: CUES.sweep, to: CUES.spray, parts: ['pad', 'kick'] },
  { section: 'spray', from: CUES.spray, to: CUES.sink, parts: ['pad', 'kick', 'pluck'] },
  { section: 'sink', from: CUES.sink, to: CUES.card, parts: ['pad', 'kick'] },
  { section: 'card', from: CUES.card, to: CUES.end, parts: ['pad', 'pluck'] },
];

function rr(g, x, y, w, h, r) {
  const rad = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2);
  g.beginPath();
  g.moveTo(x + rad, y);
  g.arcTo(x + w, y, x + w, y + h, rad);
  g.arcTo(x + w, y + h, x, y + h, rad);
  g.arcTo(x, y + h, x, y, rad);
  g.arcTo(x, y, x + w, y, rad);
  g.closePath();
}
function fillRR(g, x, y, w, h, r, color) {
  rr(g, x, y, w, h, r); g.fillStyle = color; g.fill();
}
function wall(g) {
  g.fillStyle = PALETTE.tile;
  g.fillRect(-0.85, -1.05, 1.7, 0.72);
  g.strokeStyle = PALETTE.grout; g.lineWidth = 0.012;
  for (let col = 0; col < 4; col++) for (let row = 0; row < 3; row++) {
    g.strokeRect(-0.78 + col * 0.4, -0.98 + row * 0.22, 0.36, 0.18);
  }
}
function counter(g, salt) {
  g.fillStyle = PALETTE.counter;
  g.fillRect(-0.95, -0.28, 1.9, 1.35);
  const r = rng(salt);
  for (let i = 0; i < 22; i++) {
    dot(g, S, -0.8 + r() * 1.6, -0.18 + r() * 1.05, 0.004 + r() * 0.008, PALETTE.speck, 0.45);
  }
}
function clothAt(g, x, y, tilt) {
  g.save(); g.translate(x, y); g.rotate(tilt);
  fillRR(g, -0.16, -0.1, 0.32, 0.2, 0.03, PALETTE.cloth);
  g.fillStyle = PALETTE.clothEdge; g.fillRect(-0.16, -0.02, 0.32, 0.018);
  g.restore();
}
let COPY_LINES = null;
function loadCopy() {
  return new Promise((ok, fail) => {
    const x = new XMLHttpRequest();
    x.open('GET', 'copy.json');
    x.onload = () => {
      if (x.status !== 0 && x.status !== 200) { fail(new Error('copy.json ' + x.status)); return; }
      try {
        const data = JSON.parse(x.responseText);
        if (!data || !Array.isArray(data.lines) || data.lines.some((s) => typeof s !== 'string')) throw new Error('copy.json lines');
        COPY_LINES = data.lines;
        const sample = COPY_LINES.filter(Boolean).slice(0, 4);
        TYPE.check.strings = { display: sample.slice(0, 2), text: sample.slice(2, 4) };
        ok();
      } catch (e) { fail(e); }
    };
    x.onerror = () => fail(new Error('copy.json'));
    x.send();
  });
}
function lineAt(i, fallback) {
  if (!COPY_LINES || !COPY_LINES.length) return fallback || '';
  const s = COPY_LINES[i];
  return s && s.trim() ? s.trim() : '';
}
function spokenLines() {
  return (COPY_LINES || []).map((s) => String(s || '').trim()).filter(Boolean);
}
function sceneLine(sceneIndex, k) {
  const rows = spokenLines();
  if (!rows.length) return '';
  const n = SCENES.length;
  const groups = Array.from({ length: n }, () => []);
  rows.forEach((row, i) => groups[Math.min(n - 1, Math.floor(i * n / rows.length))].push(row));
  const mine = groups[sceneIndex];
  if (!mine.length) {
    const prior = groups.slice(0, sceneIndex + 1).flat();
    return prior.length ? prior[prior.length - 1] : rows[0];
  }
  return mine[Math.min(mine.length - 1, Math.floor(Math.max(0, Math.min(0.999, k)) * mine.length))];
}
function actionKind(line) {
  const s = line || '';
  if (s.includes('橡皮')) return 'eraser';
  if (s.includes('尺')) return 'ruler';
  if (s.includes('标签') || s.includes('便签')) return 'label';
  if (s.includes('铅笔') || s.includes('入筒') || s.includes('笔筒')) return 'pencil';
  return 'tidy';
}
function captionUnits(str) {
  const units = [];
  let buf = '';
  const flush = () => { if (buf) { units.push(buf); buf = ''; } };
  for (const ch of [...String(str)]) {
    if ('，。！？；、,. '.includes(ch)) { flush(); units.push(ch); }
    else { buf += ch; if (buf.length === 2) flush(); }
  }
  flush();
  const packed = [];
  for (const unit of units) {
    if (packed.length && '，。！？；、,. '.includes(unit)) packed[packed.length - 1] += unit;
    else packed.push(unit);
  }
  return packed;
}
function captionLines(g, str, size, maxW) {
  setType(g, TYPE, 'text', size, { short: 960, weight: 700 });
  const lines = [];
  let cur = '';
  for (const unit of captionUnits(str)) {
    const next = cur + unit;
    if (g.measureText(next).width <= maxW || !cur) cur = next;
    else { lines.push(cur); cur = unit; }
  }
  if (cur) lines.push(cur);
  return lines;
}
function caption(g, S, str, yNorm, k) {
  if (!str || k <= 0) return;
  g.save();
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalAlpha = 1;
  g.textAlign = 'center';
  g.textBaseline = 'alphabetic';
  const maxW = S.W * 0.84;
  let size = Math.round(S.H * 0.046);
  const minSize = Math.round(S.H * 0.026);
  let lines = captionLines(g, str, size, maxW);
  while ((lines.length > 2 || lines.some((ln) => g.measureText(ln).width > maxW)) && size > minSize) {
    size -= 2;
    lines = captionLines(g, str, size, maxW);
  }
  setType(g, TYPE, 'text', size, { short: S.H, weight: 700 });
  const hr = headroom(g);
  const step = (hr.above + hr.below) * 1.35;
  const block = lines.length * step;
  let top = S.H * 0.5 + yNorm * S.H * 0.42 - hr.above;
  const low = S.H * 0.06;
  const high = S.H * 0.94;
  if (top < low) top = low;
  if (top + block > high) top = Math.max(low, high - block);
  lines.forEach((ln, i) => {
    const y = top + hr.above + i * step;
    const w = g.measureText(ln).width;
    g.fillStyle = '#fffaf3';
    g.fillRect(S.W / 2 - w / 2 - 12, y - hr.above - 6, w + 24, step);
    g.fillStyle = '#1a120e';
    g.fillText(ln, S.W / 2, y);
  });
  g.restore();
}
function pencil(g, x, y, tilt) {
  g.save(); g.translate(x, y); g.rotate(tilt);
  fillRR(g, -0.11, -0.014, 0.03, 0.028, 0.006, PALETTE.accent);
  fillRR(g, -0.08, -0.016, 0.14, 0.032, 0.008, PALETTE.water);
  fillRR(g, 0.05, -0.012, 0.03, 0.024, 0.004, PALETTE.ink);
  g.restore();
}
function ruler(g, x, y, tilt) {
  g.save(); g.translate(x, y); g.rotate(tilt);
  fillRR(g, -0.1, -0.01, 0.2, 0.02, 0.004, '#c9843a');
  g.fillStyle = '#f6efe4';
  for (let m = 0; m < 5; m++) g.fillRect(-0.08 + m * 0.032, -0.01, 0.006, 0.009);
  g.restore();
}
function coverBox(g, x, y, w, h, color) {
  g.save();
  g.beginPath();
  g.rect(x, y, w, h);
  g.clip();
  fillRR(g, x, y, w, h, 0.04, color);
  g.restore();
}
function forward(k) {
  const p = Math.max(0, Math.min(1, k));
  return p < 0.4 ? p / 0.4 * 0.72 : 0.72 + (p - 0.4) / 0.6 * 0.28;
}
function pencilsInto(g, k) {
  const p = Math.max(0, Math.min(1, k));
  const rush = Math.min(1, p / 0.42);
  const settle = Math.max(0, (p - 0.42) / 0.58);
  const boxX = lerp(0.48, 0.22, rush) - settle * 0.08;
  for (let i = 0; i < 4; i++) {
    const lag = i * 0.07;
    const local = Math.max(0, Math.min(1, (rush - lag) / (1 - 3 * 0.07)));
    pencil(g, lerp(-0.36, 0.0, local) + settle * 0.12, -0.18 + i * 0.13 + settle * 0.05, lerp(0.18, -0.02, local));
  }
  coverBox(g, boxX, -0.14 + settle * 0.05, 0.2, 0.6, PALETTE.cloth);
}
function eraserInto(g, k) {
  const p = Math.max(0, Math.min(1, k));
  const boxX = 0.14;
  g.save();
  g.translate(lerp(-0.3, 0.2, p), lerp(0.16, 0, p));
  g.rotate(lerp(0.7, 0, p));
  fillRR(g, -0.16, -0.06, 0.24, 0.12, 0.02, '#f7f4ef');
  fillRR(g, 0.04, -0.06, 0.1, 0.12, 0.016, '#d4537e');
  g.restore();
  coverBox(g, boxX, -0.16, 0.24, 0.34, '#c9843a');
}
function rulersNeat(g, k) {
  const p = Math.max(0, Math.min(1, k));
  const fan = [-1.05, 0.75, -0.55, 1.1];
  const fromX = [-0.24, 0.08, -0.16, 0.12];
  const fromY = [-0.3, -0.06, 0.14, 0.32];
  for (let i = 0; i < 4; i++) {
    g.save();
    g.translate(lerp(fromX[i], -0.02, p), lerp(fromY[i], -0.24 + i * 0.12, p));
    g.rotate(lerp(fan[i], 0, p));
    fillRR(g, -0.17, -0.018, 0.34, 0.036, 0.006, '#c9843a');
    g.fillStyle = '#f6efe4';
    for (let m = 0; m < 6; m++) g.fillRect(-0.14 + m * 0.046, -0.018, 0.008, 0.016);
    g.restore();
  }
}
function labelOn(g, k) {
  fillRR(g, 0.16, -0.08, 0.42, 0.4, 0.04, PALETTE.cloth);
  fillRR(g, lerp(-0.55, 0.22, k), 0.02, 0.28, 0.12, 0.02, PALETTE.mist);
}
function tidyFinish(g, k) {
  const p = Math.max(0, Math.min(1, k));
  for (let i = 0; i < 4; i++) ruler(g, lerp(0.04, -0.26, p), 0.4 + i * 0.1, lerp((i - 1.5) * 0.4, 0, p));
  g.save();
  g.translate(lerp(-0.22, 0.0, p), 0.82);
  fillRR(g, -0.08, -0.03, 0.12, 0.06, 0.012, '#e7e2dc');
  fillRR(g, 0.02, -0.03, 0.04, 0.06, 0.008, '#d4537e');
  g.restore();
  coverBox(g, 0.04, 0.74, 0.14, 0.14, '#c9843a');
  for (let i = 0; i < 4; i++) pencil(g, lerp(-0.16, 0.0, p), -0.18 + i * 0.1, -0.02);
  coverBox(g, 0.22, -0.22, 0.16, 0.48, PALETTE.cloth);
}
function drawKind(g, kind, k) {
  if (kind === 'eraser') eraserInto(g, k);
  else if (kind === 'ruler') rulersNeat(g, k);
  else if (kind === 'label') labelOn(g, k);
  else if (kind === 'tidy') tidyFinish(g, k);
  else pencilsInto(g, k);
}
function counterSweep(g, k, t, S) {
  const cam = CAM.base();
  CAM.dolly(cam, k, 1.01, 1);
  const line = sceneLine(0, k) || '铅笔入筒';
  plane(g, S, cam, 0.2, () => counter(g, 4));
  plane(g, S, cam, 0, () => {
    drawKind(g, actionKind(line), k);
    caption(g, S, line, -0.58, 1);
  });
}
function sprayWipe(g, k, t, S) {
  const cam = CAM.base();
  CAM.truck(cam, k, 0, 0.02);
  const line = sceneLine(1, k) || '贴上标签';
  plane(g, S, cam, 0.2, () => counter(g, 6));
  plane(g, S, cam, 0, () => {
    drawKind(g, actionKind(line), k);
    caption(g, S, line, -0.58, 1);
  });
}
function rinsePlate(g, k, t, S) {
  const cam = CAM.base();
  CAM.crane(cam, k, 0, -0.02);
  const line = sceneLine(2, k) || '分类摆好';
  plane(g, S, cam, 0.55, () => counter(g, 8));
  plane(g, S, cam, 0, () => {
    drawKind(g, actionKind(line), k);
    caption(g, S, line, -0.62, 1);
  });
}
function threeChecks(g, k, t, S) {
  const cam = CAM.base();
  CAM.pushTo(cam, k, 0, 0, 1.01, 1);
  const line = sceneLine(3, k) || '定期查看';
  plane(g, S, cam, 0, () => {
    const kind = actionKind(line);
    drawKind(g, kind === 'pencil' ? 'tidy' : kind, k);
    caption(g, S, line, -0.62, 1);
  });
}
function score(ctx, out) {
  for (const [from, to] of spans('pad')) pad(ctx, out, from, to - from, [hz('C3'), hz('G3'), hz('C4')], 0.07);
  for (const t of beats('kick')) kick(ctx, out, t, 0.32);
  for (const t of beats('pluck', 60 / BPM)) pluck(ctx, out, t, hz('G4'), 0.07);
}
