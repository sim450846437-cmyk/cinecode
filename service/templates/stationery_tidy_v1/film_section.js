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
function lineAt(i, fallback) {
  if (!COPY_LINES || !COPY_LINES.length) return fallback || '';
  const s = COPY_LINES[i];
  return s && s.trim() ? s.trim() : '';
}
function captionLines(g, str, size, maxW) {
  setType(g, TYPE, 'text', size, { short: 960, weight: 700 });
  const lines = [];
  let cur = '';
  for (const ch of [...String(str)]) {
    const next = cur + ch;
    if (g.measureText(next).width <= maxW || !cur) cur = next;
    else { lines.push(cur); cur = ch; }
  }
  if (cur) lines.push(cur);
  return lines;
}
function caption(g, S, str, yNorm, k) {
  if (!str || k <= 0) return;
  g.save();
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalAlpha = clamp(k);
  g.fillStyle = PALETTE.ink;
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
  lines.forEach((ln, i) => g.fillText(ln, S.W / 2, top + hr.above + i * step));
  g.restore();
}
function pencil(g, x, y, tilt) {
  g.save(); g.translate(x, y); g.rotate(tilt);
  fillRR(g, -0.22, -0.03, 0.4, 0.06, 0.02, PALETTE.water);
  fillRR(g, 0.16, -0.025, 0.06, 0.05, 0.01, PALETTE.accent);
  g.restore();
}
function counterSweep(g, k, t, S) {
  const cam = CAM.base();
  CAM.dolly(cam, EASE.out(k), 1.06, 0.98);
  const wipe = (Math.sin(t * 1.7) + 1) / 2;
  plane(g, S, cam, 0.7, () => wall(g));
  plane(g, S, cam, 0.2, () => counter(g, 4));
  plane(g, S, cam, 0, () => {
    fillRR(g, 0.28, -0.05, 0.42, 0.55, 0.04, PALETTE.cloth);
    for (let i = 0; i < 5; i++) {
      pencil(g, lerp(-0.7, 0.25, wipe) + i * 0.04, 0.02 + i * 0.08 + Math.sin(t * 8 + i) * 0.04, -0.5);
    }
    caption(g, S, lineAt(0, '文具入盒'), -0.58, MOTION.at(t, 0.15, 0.4));
  });
}
function sprayWipe(g, k, t, S) {
  // truck, 4.8 s, ease-in-out, across the bottle
  const cam = CAM.base();
  CAM.truck(cam, EASE.inOut(k), -0.04, 0.05);
  const local = (t - CUES.spray) / 4.6;
  plane(g, S, cam, 0.7, () => wall(g));
  plane(g, S, cam, 0.2, () => counter(g, 6));
  plane(g, S, cam, 0, () => {
    const pump = MOTION.at(t, CUES.spray + 0.1, 0.3);
    fillRR(g, -0.15, 0.05, 0.5, 0.42, 0.04, PALETTE.cloth);
    const labelY = lerp(-0.55, 0.28, Math.min(1, Math.max(0, local)));
    fillRR(g, lerp(-0.45, 0.2, Math.min(1, Math.max(0, local))), labelY, 0.42, 0.16, 0.02, PALETTE.mist);
    pencil(g, lerp(0.4, -0.2, Math.min(1, Math.max(0, local))), 0.35, 0.6);
    caption(g, S, local < 0.45 ? lineAt(1, '贴上标签') : lineAt(2, '分类摆好'), -0.58, pump);
  });
}
function rinsePlate(g, k, t, S) {
  // crane, 5.4 s, ease-in-out, down toward the plate
  const cam = CAM.base();
  CAM.crane(cam, EASE.inOut(k), 0.06, -0.08);
  plane(g, S, cam, 0.55, () => counter(g, 8));
  plane(g, S, cam, 0, () => {
    const flow = (Math.sin(t * 3.5) + 1) / 2;
    for (let i = 0; i < 4; i++) {
      const drop = (Math.sin(t * 4 + i) + 1) / 2;
      pencil(g, -0.4 + i * 0.24 + Math.sin(t * 3 + i) * 0.08, lerp(-0.45, 0.35, drop), 1.2);
    }
    caption(g, S, lineAt(3, '分类摆好'), -0.62, flow);
  });
}
function threeChecks(g, k, t, S) {
  // push in, 3 s, ease-out, on the checks
  const cam = CAM.base();
  CAM.pushTo(cam, EASE.out(k), 0, 0.02, 1.08, 0.92);
  plane(g, S, cam, 0.4, () => wall(g));
  plane(g, S, cam, 0, () => {
    const sweep = (Math.sin((t - CUES.card) * 3.2) + 1) / 2;
    g.save();
    g.translate(lerp(-0.5, 0.5, sweep), 0.02);
    fillRR(g, -0.34, -0.24, 0.68, 0.48, 0.04, PALETTE.cloth);
    pencil(g, 0.05, -0.02, -0.4);
    g.restore();
  });
  const title = lineAt(4, '定期查看');
  caption(g, S, title, -0.62, MOTION.at(t, CUES.card, 0.35));
  const rows = [];
  for (const i of [5, 6, 7]) {
    const s = lineAt(i, '');
    if (s && s !== title && !rows.includes(s)) rows.push(s);
  }
  rows.forEach((word, i) => {
    caption(g, S, word, -0.22 + i * 0.2, MOTION.back(clamp((k - 0.08 * i) / 0.35)));
  });
}
function score(ctx, out) {
  for (const [from, to] of spans('pad')) pad(ctx, out, from, to - from, [hz('C3'), hz('G3'), hz('C4')], 0.07);
  for (const t of beats('kick')) kick(ctx, out, t, 0.32);
  for (const t of beats('pluck', 60 / BPM)) pluck(ctx, out, t, hz('G4'), 0.07);
}
