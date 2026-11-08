const TITLE = '台面三步';
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
  cloth: '#2f6d62', clothEdge: '#1e4c44', water: '#6f97a0', plate: '#f7f1e8',
  sponge: '#d7a15e', bottle: '#f7f4ef', mist: '#d5e4e6',
};
const TYPE = {
  lang: 'zh',
  roles: {
    display: { family: 'Droid Sans Fallback', files: { 400: 'fonts/DroidSansFallbackFull.ttf', 700: 'fonts/DroidSansFallbackFull.ttf' } },
    text: { family: 'Droid Sans Fallback', files: { 400: 'fonts/DroidSansFallbackFull.ttf', 700: 'fonts/DroidSansFallbackFull.ttf' } },
    mono: { family: 'Droid Sans Fallback', files: { 400: 'fonts/DroidSansFallbackFull.ttf' } },
  },
  check: {
    strings: { display: ['先清台面', '三步做完'], text: ['喷一点', '顺纹擦开', '热水过盘'] },
    sizes: { text: 0.05 },
  },
};
const CUES = { sweep: 0, spray: beat(8), sink: beat(16), card: beat(25), end: DURATION };
const VO = [];
const CAPTIONS = null;
const CAPTION_STYLE = { role: 'text', accentRole: 'text', size: 0.05, caps: false, ink: PALETTE.ink, hi: PALETTE.ink, accent: PALETTE.accent, punch: 0 };
const SCENES = [
  { chapter: 'C1', from: CUES.sweep, to: CUES.spray, draw: counterSweep, action: 'the cloth sweeps crumbs off the counter', amb: { kind: 'room', gain: 0.05 } },
  { chapter: 'C1', from: CUES.spray, to: CUES.sink, draw: sprayWipe, action: 'mist leaves the bottle and a wipe clears a circle', in: { type: 'wipe', dur: 0.36, dir: 1 }, amb: { kind: 'room', gain: 0.045 } },
  { chapter: 'C1', from: CUES.sink, to: CUES.card, draw: rinsePlate, action: 'water runs and the sponge scrubs the plate', in: { type: 'cut' }, amb: { kind: 'water', gain: 0.03 } },
  { chapter: 'C1', from: CUES.card, to: CUES.end, draw: threeChecks, action: 'three checks land one after another', in: { type: 'dissolve', dur: 0.32 }, amb: { kind: 'room', gain: 0.04 } },
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
function lineAbout(keys, index, fallback) {
  for (const row of COPY_LINES || []) {
    if (row && keys.some((k) => row.includes(k))) return row.trim();
  }
  return lineAt(index, fallback);
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
function stain(g, remain) {
  if (remain <= 0.02) return;
  g.save();
  g.globalAlpha = Math.min(1, remain);
  for (let i = 0; i < 5; i++) {
    g.fillStyle = i % 2 ? '#9ec4c8' : '#7eb0b6';
    g.beginPath();
    g.ellipse(-0.08 + (i % 3) * 0.1, 0.08 + Math.floor(i / 3) * 0.08, 0.055 * remain, 0.03 * remain, 0, 0, TAU);
    g.fill();
  }
  g.restore();
}
function cleanKind(line) {
  const s = line || '';
  if (s.includes('擦干') || s.includes('水渍') || s.includes('冲')) return 'dry';
  if (s.includes('喷') || s.includes('擦') || s.includes('抹')) return 'wipe';
  if (s.includes('做完') || s.includes('查看')) return 'done';
  return 'sweep';
}
function dryPlate(g, k, remain) {
  g.fillStyle = PALETTE.plate;
  g.beginPath(); g.ellipse(0.05, 0.12, 0.28, 0.14, 0, 0, TAU); g.fill();
  g.strokeStyle = PALETTE.dim; g.lineWidth = 0.012; g.stroke();
  stain(g, remain);
  fillRR(g, lerp(-0.42, 0.36, k), 0.02, 0.32, 0.14, 0.03, PALETTE.sponge);
}
function stroke(k, turns) {
  return (Math.sin(Math.max(0, Math.min(1, k)) * Math.PI * turns) + 1) / 2;
}
function paintClean(g, k, line, S) {
  const kind = cleanKind(line);
  const p = Math.max(0, Math.min(1, k));
  if (kind === 'wipe') {
    fillRR(g, -0.62, -0.28, 0.2, 0.42, 0.04, PALETTE.bottle);
    for (let i = 0; i < 6; i++) dot(g, S, -0.2 + i * 0.12, 0.04, 0.03 * (1 - p), PALETTE.mist, 0.95 * (1 - p));
    g.save();
    g.translate(lerp(-0.55, 0.62, stroke(p, 4)), 0.16);
    g.rotate(-0.2);
    fillRR(g, -0.34, -0.18, 0.68, 0.36, 0.05, PALETTE.cloth);
    g.restore();
    return;
  }
  if (kind === 'done') {
    g.fillStyle = PALETTE.plate;
    g.beginPath(); g.ellipse(0.02, 0.08, 0.3, 0.12, 0, 0, TAU); g.fill();
    g.strokeStyle = PALETTE.dim; g.lineWidth = 0.012; g.stroke();
    g.save();
    g.translate(lerp(-0.55, 0.36, p), 0.36);
    g.rotate(lerp(-0.8, 0.2, p));
    fillRR(g, -0.3, -0.14, 0.6, 0.28, 0.04, PALETTE.cloth);
    g.restore();
    return;
  }
  if (kind === 'dry') {
    g.fillStyle = PALETTE.plate;
    g.beginPath(); g.ellipse(0.05, 0.12, 0.34, 0.16, 0, 0, TAU); g.fill();
    g.strokeStyle = PALETTE.dim; g.lineWidth = 0.014; g.stroke();
    stain(g, 1 - p);
    fillRR(g, lerp(-0.5, 0.42, stroke(p, 5)), 0.02, 0.36, 0.18, 0.03, PALETTE.sponge);
    return;
  }
  const cleared = lerp(-0.55, 0.7, p);
  for (let i = 0; i < 7; i++) {
    const along = -0.5 + i * 0.16;
    dot(g, S, along, 0.05, 0.04, PALETTE.accent, along < cleared ? 0 : 0.95);
  }
  g.save();
  g.translate(lerp(-0.7, 0.7, stroke(p, 4)), 0.1);
  g.rotate(-0.15);
  fillRR(g, -0.34, -0.16, 0.68, 0.32, 0.05, PALETTE.cloth);
  g.restore();
}
function stageClean(g, k, t, S, sceneIndex, camMove) {
  const line = sceneLine(sceneIndex, k) || '先清台面';
  const kind = cleanKind(line);
  const cam = CAM.base();
  camMove(cam, k);
  if (kind === 'dry' || kind === 'done') {
    plane(g, S, cam, 0.45, () => {
      g.fillStyle = '#d7e3e4';
      g.beginPath(); g.ellipse(0, 0.04, 0.46, 0.24, 0, 0, TAU); g.fill();
    });
  } else {
    plane(g, S, cam, 0.7, () => wall(g));
    plane(g, S, cam, 0.2, () => counter(g, 4 + sceneIndex));
  }
  plane(g, S, cam, 0, () => {
    paintClean(g, k, line, S);
    caption(g, S, line, -0.58, 1);
  });
}
function counterSweep(g, k, t, S) {
  stageClean(g, k, t, S, 0, (cam, p) => CAM.dolly(cam, p, 1.01, 1));
}
function sprayWipe(g, k, t, S) {
  stageClean(g, k, t, S, 1, (cam, p) => CAM.truck(cam, p, 0, 0.02));
}
function rinsePlate(g, k, t, S) {
  stageClean(g, k, t, S, 2, (cam, p) => CAM.crane(cam, p, 0, -0.02));
}
function threeChecks(g, k, t, S) {
  stageClean(g, k, t, S, 3, (cam, p) => CAM.pushTo(cam, p, 0, 0, 1.01, 1));
}
function score(ctx, out) {
  for (const [from, to] of spans('pad')) pad(ctx, out, from, to - from, [hz('C3'), hz('G3'), hz('C4')], 0.07);
  for (const t of beats('kick')) kick(ctx, out, t, 0.32);
  for (const t of beats('pluck', 60 / BPM)) pluck(ctx, out, t, hz('G4'), 0.07);
}
