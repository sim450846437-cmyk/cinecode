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
function lineAt(i, fallback) {
  const rows = COPY_LINES && COPY_LINES.length ? COPY_LINES : [];
  const s = rows[i] || rows[rows.length - 1] || '';
  return s.trim() ? s : fallback;
}
function lineText(g, S, str, y, k) {
  const show = clamp(k);
  const size = str.length > 10 ? 0.052 : 0.072;
  text(g, S, str, 0, y, size, PALETTE.ink, 1, null, { reveal: show, spread: 0.35, weight: 700 });
}
function counterSweep(g, k, t, S) {
  // dolly in, 4.8 s, ease-out, toward the cloth
  const cam = CAM.base();
  CAM.dolly(cam, EASE.out(k), 1.06, 0.98);
  const wipe = EASE.out(Math.min(1, (t - CUES.sweep) / 3.2));
  plane(g, S, cam, 0.7, () => wall(g));
  plane(g, S, cam, 0.2, () => counter(g, 4));
  plane(g, S, cam, 0, () => {
    for (let i = 0; i < 6; i++) {
      const along = lerp(-0.15, 0.72, wipe) + i * 0.07;
      const fall = Math.sin(t * 7 + i) * 0.04 + i * 0.015;
      dot(g, S, along, 0.02 + fall, 0.02, PALETTE.accent, along < lerp(-0.55, 0.62, wipe) ? 0 : 0.95);
    }
    clothAt(g, lerp(-0.58, 0.62, wipe), 0.12 + Math.sin(t * 8) * 0.03, -0.35 + 0.5 * Math.sin(t * 6));
    lineText(g, S, lineAt(0, '先清台面'), -0.58, MOTION.at(t, 0.15, 0.4));
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
    fillRR(g, -0.28, -0.22, 0.18, 0.4, 0.04, PALETTE.bottle);
    fillRR(g, -0.23, -0.34, 0.08, 0.14, 0.02, PALETTE.dim);
    for (let i = 0; i < 7; i++) {
      const p = (local * 1.4 + i * 0.09) % 1;
      dot(g, S, -0.05 + p * 0.55, -0.08 + Math.sin(t * 9 + i) * 0.05, 0.018, PALETTE.mist, 0.85);
    }
    const sweep = EASE.inOut((Math.sin(t * 2.2) + 1) / 2);
    clothAt(g, lerp(0.15, 0.55, sweep), 0.22, 0.4);
    lineText(g, S, local < 0.45 ? lineAt(1, '喷一点') : lineAt(2, '顺纹擦开'), -0.58, pump);
  });
}
function rinsePlate(g, k, t, S) {
  // crane, 5.4 s, ease-in-out, down toward the plate
  const cam = CAM.base();
  CAM.crane(cam, EASE.inOut(k), 0.06, -0.08);
  plane(g, S, cam, 0.55, () => {
    g.fillStyle = '#d7e3e4';
    g.beginPath(); g.ellipse(0, 0.05, 0.42, 0.28, 0, 0, TAU); g.fill();
    g.strokeStyle = PALETTE.dim; g.lineWidth = 0.02; g.stroke();
  });
  plane(g, S, cam, 0, () => {
    const flow = MOTION.at(t, CUES.sink, 0.45);
    g.fillStyle = PALETTE.water;
    g.fillRect(-0.03, -0.55, 0.035, 0.28 * flow);
    g.fillStyle = PALETTE.plate;
    g.beginPath(); g.ellipse(0.05, 0.12, 0.22, 0.1, 0, 0, TAU); g.fill();
    g.strokeStyle = PALETTE.dim; g.lineWidth = 0.012; g.stroke();
    const scrub = (Math.sin(t * 5.5) + 1) / 2;
    fillRR(g, -0.2 + scrub * 0.36, 0.02 + Math.sin(t * 5.5) * 0.05, 0.2, 0.12, 0.03, PALETTE.sponge);
    lineText(g, S, lineAt(3, '热水过盘'), -0.62, flow);
  });
}
function threeChecks(g, k, t, S) {
  // push in, 3 s, ease-out, on the checks
  const cam = CAM.base();
  CAM.pushTo(cam, EASE.out(k), 0, 0.02, 1.08, 0.92);
  const rows = [lineAt(5, '台面'), lineAt(6, '喷擦'), lineAt(7, '过盘')];
  plane(g, S, cam, 0.4, () => wall(g));
  plane(g, S, cam, 0, () => {
    lineText(g, S, lineAt(4, '三步做完'), -0.55, MOTION.at(t, CUES.card, 0.35));
    const sweep = (Math.sin((t - CUES.card) * 4) + 1) / 2;
    clothAt(g, lerp(-0.45, 0.45, sweep), 0.55, 0.2);
    rows.forEach((word, i) => {
      const p = MOTION.back(clamp((k - 0.08 * i) / 0.35));
      const y = -0.18 + i * 0.22 + Math.sin(t * 6 + i) * 0.012;
      g.globalAlpha = clamp(p);
      fillRR(g, -0.34, y - 0.07, 0.68, 0.16, 0.03, '#fffaf3');
      g.fillStyle = PALETTE.accent;
      g.beginPath(); g.arc(-0.22, y + 0.01, 0.045, 0, TAU); g.fill();
      if (p > 0.65) {
        g.strokeStyle = '#fffaf3'; g.lineWidth = 0.012;
        g.beginPath(); g.moveTo(-0.24, y + 0.01); g.lineTo(-0.22, y + 0.03); g.lineTo(-0.18, y - 0.02); g.stroke();
      }
      text(g, S, word, 0.06, y + 0.02, 0.055, PALETTE.ink, 1, null, { weight: 700 });
      g.globalAlpha = 1;
    });
  });
}
function score(ctx, out) {
  for (const [from, to] of spans('pad')) pad(ctx, out, from, to - from, [hz('C3'), hz('G3'), hz('C4')], 0.07);
  for (const t of beats('kick')) kick(ctx, out, t, 0.32);
  for (const t of beats('pluck', 60 / BPM)) pluck(ctx, out, t, hz('G4'), 0.07);
}
