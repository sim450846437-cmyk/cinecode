"""Call the pinned procedural lipsync. This is not a neural model and not MiniMax H3.

The picture is drawn here. The sound is a sine burst. Neither is model inference.
qualified stays false. A finished MP4 is not an independent audiovisual pass.
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "vendor" / "character-lipsync" / "scripts" / "lipsync.py"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def draw_face(path, shirt):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (640, 800), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((170, 80, 470, 460), fill=(214, 176, 148, 255))
    d.ellipse((230, 190, 290, 250), fill=(40, 32, 28, 255))
    d.ellipse((350, 190, 410, 250), fill=(40, 32, 28, 255))
    d.rectangle((200, 428, 440, 434), fill=(40, 24, 22, 255))
    d.rounded_rectangle((150, 500, 490, 780), radius=40, fill=shirt)
    im.save(path)


def synth(path, seconds):
    expr = (
        "0.45*sin(2*PI*180*t)*between(t\\,0.35\\,0.75)"
        "+0.5*sin(2*PI*260*t)*between(t\\,1.15\\,1.65)"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"aevalsrc={expr}:s=24000:d={seconds}", "-c:a", "pcm_s16le", path],
        check=True,
    )


def render(work, name, shirt, deps):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    image = work / f"{name}.png"
    audio = work / f"{name}.wav"
    out = work / f"{name}.mp4"
    draw_face(image, shirt)
    synth(str(audio), 2)
    cfg = {
        "audio": audio.name,
        "out": out.name,
        "fps": 24,
        "width": 640,
        "height": 960,
        "background": "#E7E1D6",
        "poses": {"1": {"image": image.name, "lips": [[200, 430], [440, 430]]}},
        "schedule": [[0.0, "1"]],
        "character": {"scale": 1.0, "anchor": "center", "offset": [0, 0]},
        "hmax_ratio": 0.16,
        "levels": 9,
        "threshold": 0.12,
        "gate_db": -40.0,
        "bob": False,
        "pop": False,
    }
    config = work / f"{name}.json"
    config.write_text(json.dumps(cfg), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(deps)
    started = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(
        [sys.executable, str(TOOL), str(config), "--envelope", str(work / f"{name}-envelope.json")],
        cwd=work, env=env, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or proc.stdout)
    proc = subprocess.run(
        [sys.executable, str(TOOL), str(config)],
        cwd=work, env=env, text=True, capture_output=True,
    )
    finished = datetime.now(timezone.utc).isoformat()
    if proc.returncode != 0 or not out.is_file():
        raise SystemExit(proc.stderr or proc.stdout or "no mp4")
    envj = json.loads((work / f"{name}-envelope.json").read_text(encoding="utf-8"))
    return {
        "name": name,
        "started_at": started,
        "finished_at": finished,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "mp4": str(out),
        "sha256": sha256(out),
        "bytes": out.stat().st_size,
        "mouth_min": min(envj["mouth"]),
        "mouth_max": max(envj["mouth"]),
        "frames": len(envj["mouth"]),
    }


def main():
    work = Path(sys.argv[1])
    deps = Path(sys.argv[2])
    sys.path.insert(0, str(deps))
    a = render(work / "a", "shot-a", (70, 110, 150, 255), deps)
    b = render(work / "b", "shot-b", (150, 96, 64, 255), deps)
    joined = work / "two-shot.mp4"
    listing = work / "list.txt"
    listing.write_text(f"file '{a['mp4']}'\nfile '{b['mp4']}'\n", encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)],
        check=True,
    )
    report = {
        "tool": "character-lipsync",
        "upstream_commit": "abdcbda875256749bbc14e895b521e145a05d921",
        "inference": False,
        "model": None,
        "qualified": False,
        "listened": False,
        "independent_av": "not_reviewed",
        "chinese_voiceover": False,
        "audio": "synthetic sine bursts, not speech",
        "picture": "drawn by this script, not an image model",
        "full_head": "not_run",
        "shots": [a, b],
        "joined": {"path": str(joined), "sha256": sha256(joined), "bytes": joined.stat().st_size},
    }
    dest = work / "result.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"joined_sha256": report["joined"]["sha256"], "qualified": False, "mouth": [a["mouth_min"], a["mouth_max"], b["mouth_min"], b["mouth_max"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
