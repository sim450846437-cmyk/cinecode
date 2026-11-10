"""Render a talking 2D character video (lip sync + pose switches) from static pose images.

    python3 lipsync.py config.json            # render video
    python3 lipsync.py config.json --envelope envelope.json   # only export mouth values per frame
    python3 lipsync.py config.json --preview 1.0 2.5 7.3      # save preview PNGs at those seconds

config.json (all keys except audio/poses optional):
{
  "audio": "voice.wav",
  "out": "talking.mp4",                 # .mp4 (with background) or .mov (transparent, ProRes 4444)
  "fps": 30, "width": 1080, "height": 1920,
  "background": "#ECEAE5",              # hex colour | path to image | "transparent"
  "poses": {
    "1": {"image": "1.png", "lips": [[505,549],[650,534]]},
    "2": {"image": "2.png", "lips": [[640,520],[785,505]]}
  },
  "schedule": [[0, "1"], [5.15, "2"]],  # [start_second, pose_id]; default: first pose only
  "character": {"scale": 0.57, "anchor": "bottom-right", "offset": [80, 40]},
  "hmax_ratio": 0.186,                  # max mouth opening = lip width * ratio
  "levels": 9,                          # number of pre-rendered mouth states
  "threshold": 0.12,                    # envelope below this = closed mouth
  "bob": true, "pop": true              # idle breathing bob, bounce on pose change
}
Frames are written to <out>_frames/ as JPEG/PNG, then encoded with low-memory ffmpeg settings
(1 GB sandboxes OOM-kill ffmpeg when raw 1080x1920 frames are piped with preset medium, or
when '-shortest' is used: it makes ffmpeg buffer video while waiting on audio).
"""
import json, math, os, shutil, subprocess, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mouth import open_mouth


FFMPEG_BIN = shutil.which('ffmpeg') or ('/opt/homebrew/bin/ffmpeg' if os.path.exists('/opt/homebrew/bin/ffmpeg') else 'ffmpeg')


def load_audio(path, sr=24000):
    try:
        import librosa
        y, _ = librosa.load(path, sr=sr, mono=True)
    except ImportError:  # fallback through ffmpeg
        raw = subprocess.run([FFMPEG_BIN, '-v', 'error', '-i', path, '-f', 's16le', '-ac', '1', '-ar', str(sr), '-'],
                             capture_output=True, check=True).stdout
        y = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    return y, sr


def mouth_envelope(y, sr, fps, threshold=0.12, gate_db=-40.0):
    """Per-video-frame mouth opening 0..1.  The key trick: compare each frame's loudness
    with the local average over ~0.4 s, so syllable peaks open the mouth and the dips
    between syllables close it. Plain RMS keeps the mouth half-open all the time."""
    hop = sr // fps
    n = int(math.ceil(len(y) / hop))
    pad = np.pad(y, (hop // 2, hop * 2))
    rms = np.array([np.sqrt(np.mean(pad[i * hop:i * hop + hop] ** 2) + 1e-12) for i in range(n)])
    rms = rms / (np.percentile(rms, 95) + 1e-9)
    win = max(3, int(round(0.4 * fps)))
    loc = np.convolve(rms, np.ones(win) / win, mode='same')
    env = rms * np.clip(0.55 + 0.6 * (rms - loc) / (loc + 1e-3), 0.25, 1.4)
    env = np.convolve(env, [0.2, 0.6, 0.2], mode='same')
    env = np.where(env < threshold, 0.0, np.clip((env - threshold) / 0.85, 0, 1))
    if gate_db is not None:
        # тишина в TTS тихая, но не нулевая: без абсолютного порога рот шевелится в паузах
        db = 20 * np.log10(np.maximum(rms, 1e-7))
        g = np.clip((db - gate_db) / 12.0, 0, 1)
        env = env * (g * g * (3 - 2 * g))
    return env


def eback(x):
    x = min(1, max(0, x)); c1 = 1.70158; c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def main():
    cfg = json.load(open(sys.argv[1]))
    base = os.path.dirname(os.path.abspath(sys.argv[1]))

    def P(p):
        if not p or os.path.isabs(p):
            return p
        c1 = os.path.normpath(os.path.join(base, p))
        if os.path.exists(c1):
            return c1
        c2 = os.path.normpath(os.path.join(base, "..", p))
        if os.path.exists(c2):
            return c2
        curr = base
        while curr != os.path.dirname(curr):
            c3 = os.path.join(curr, p.lstrip("./"))
            if os.path.exists(c3):
                return c3
            if os.path.exists(os.path.join(curr, "char", os.path.basename(p))):
                return os.path.join(curr, "char", os.path.basename(p))
            curr = os.path.dirname(curr)
        return c1

    fps = cfg.get('fps', 30); W = cfg.get('width', 1080); H = cfg.get('height', 1920)
    y, sr = load_audio(P(cfg['audio'])); dur = len(y) / sr
    env = mouth_envelope(y, sr, fps, cfg.get('threshold', 0.12), cfg.get('gate_db', -40.0))
    if '--envelope' in sys.argv:
        out = sys.argv[sys.argv.index('--envelope') + 1]
        json.dump({'fps': fps, 'mouth': [round(float(v), 3) for v in env]}, open(out, 'w'))
        print('saved', out); return

    poses = cfg['poses']; levels = cfg.get('levels', 9); ratio = cfg.get('hmax_ratio', 0.186)
    ch = cfg.get('character', {}); scale = ch.get('scale', 0.57)
    anchor = ch.get('anchor', 'bottom-right'); ox, oy = ch.get('offset', [80, 40])
    sched = sorted(cfg.get('schedule', [[0, next(iter(poses))]]))
    src = {k: np.array(Image.open(P(v['image'])).convert('RGBA')) for k, v in poses.items()}
    cache = {}

    def sprite(pid, lvl):
        if (pid, lvl) not in cache:
            (x0, y0), (x1, y1) = poses[pid]['lips']
            h = (x1 - x0) * ratio * lvl / (levels - 1)
            crv = poses[pid].get('curve')
            im = Image.fromarray(open_mouth(src[pid], ((x0, y0), (x1, y1)), h, curve=crv))
            pose_scale = poses[pid].get('scale', 1.0) * scale
            cache[(pid, lvl)] = im.resize((int(im.width * pose_scale), int(im.height * pose_scale)), Image.LANCZOS)
        return cache[(pid, lvl)]

    bgv = cfg.get('background', '#ECEAE5'); transparent = bgv == 'transparent'
    if transparent:
        bg = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    elif bgv.startswith('#'):
        bg = Image.new('RGBA', (W, H), tuple(int(bgv[i:i + 2], 16) for i in (1, 3, 5)) + (255,))
    else:
        bg = Image.open(P(bgv)).convert('RGBA').resize((W, H), Image.LANCZOS)

    def frame(fi):
        t = fi / fps
        st, pid = sched[0]
        for s, p in sched:
            if s <= t: st, pid = s, p
        lvl = int(round(env[min(fi, len(env) - 1)] * (levels - 1)))
        im = sprite(pid, lvl)
        
        # Pop bounce when changing pose
        s = 1.0
        if cfg.get('pop', True) and st > 0:
            dt = t - st
            if dt < 0.35:
                s = 0.92 + 0.08 * eback(dt / 0.30)
                
        # Bob & Sway (organic breathing + horizontal sway + subtle tilt)
        if cfg.get('bob', True):
            bob_y = math.sin(t * 2.4) * 8 + math.sin(t * 4.9) * 3
            sway_x = math.sin(t * 1.6) * 6 + math.cos(t * 3.2) * 2
            rot_deg = math.sin(t * 1.8) * 1.2
        else:
            bob_y = 0
            sway_x = 0
            rot_deg = 0
            
        if abs(s - 1.0) > 0.003:
            im = im.resize((int(im.width * s), int(im.height * s)), Image.BILINEAR)
        if abs(rot_deg) > 0.05:
            im = im.rotate(rot_deg, resample=Image.BICUBIC, expand=True)

        if anchor == 'bottom-right': x = W - im.width + ox + sway_x
        elif anchor == 'bottom-left': x = -ox + sway_x
        else: x = (W - im.width) // 2 + ox + sway_x
        yy = H - im.height + oy + int(bob_y)
        f = bg.copy(); f.alpha_composite(im, (int(x), int(yy)))
        return f

    if '--preview' in sys.argv:
        for ts in sys.argv[sys.argv.index('--preview') + 1:]:
            p = P(f'preview_{float(ts):06.2f}.png'); frame(int(float(ts) * fps)).save(p); print('saved', p)
        return

    out = P(cfg.get('out', 'talking.mp4')); fdir = out + '_frames'; os.makedirs(fdir, exist_ok=True)
    ext = 'png' if transparent else 'jpg'
    n = int(dur * fps)
    for fi in range(n):  # resumable: existing frames are skipped
        p = os.path.join(fdir, f'{fi:05d}.{ext}')
        if os.path.exists(p): continue
        fr = frame(fi)
        fr.save(p) if transparent else fr.convert('RGB').save(p, quality=93)
        if fi % 100 == 0: print(fi, '/', n, flush=True)
    cache.clear(); src.clear()  # free RAM before ffmpeg runs (1 GB sandboxes)
    vcodec = (['-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le'] if transparent else
              ['-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2', '-x264-params', 'rc-lookahead=10',
               '-crf', '19', '-pix_fmt', 'yuv420p'])
    subprocess.run([FFMPEG_BIN, '-y', '-v', 'error', '-framerate', str(fps), '-i', os.path.join(fdir, f'%05d.{ext}'),
                    '-i', P(cfg['audio']), *vcodec, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
                    '-movflags', '+faststart', out], check=True)
    if '--keep-frames' not in sys.argv and os.path.exists(fdir):
        shutil.rmtree(fdir, ignore_errors=True)
    print('done', out)


if __name__ == '__main__':
    main()
