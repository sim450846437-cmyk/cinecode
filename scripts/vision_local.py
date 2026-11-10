#!/usr/bin/env python3
"""Earlier drawn-face and green-screen measurement. The job service does not call this.

background_replace composites a green-screen frame with ffmpeg chromakey.
face_swap warps one drawn face onto another. Those inputs are drawings.
A photograph is not handled here.
"""
import argparse
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path


def run(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        sys.exit(proc.stderr.decode("utf-8", "replace")[-1500:])
    return proc


def write_png(path, w, h, rgb):
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    Path(path).write_bytes(png)


def read_png_rgb(path):
    proc = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                  "-of", "csv=s=x:p=0", str(path)])
    w, h = (int(x) for x in probe.stdout.decode().strip().split("x"))
    rgb = proc.stdout
    if len(rgb) != w * h * 3:
        sys.exit(f"decoded {path} is {len(rgb)} bytes, expected {w * h * 3}")
    return w, h, rgb


def put(rgb, w, x, y, color):
    if 0 <= x < w and y >= 0:
        i = (y * w + x) * 3
        if i + 2 < len(rgb):
            rgb[i:i + 3] = bytes(color)


def fill_disc(rgb, w, h, cx, cy, r, color):
    r2 = r * r
    for y in range(max(0, cy - r), min(h, cy + r + 1)):
        for x in range(max(0, cx - r), min(w, cx + r + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                put(rgb, w, x, y, color)


def synthetic_screen(path):
    w = h = 160
    rgb = bytearray([0, 220, 0] * w * h)
    fill_disc(rgb, w, h, 80, 78, 36, (214, 176, 140))
    fill_disc(rgb, w, h, 66, 70, 6, (40, 40, 40))
    fill_disc(rgb, w, h, 94, 70, 6, (40, 40, 40))
    fill_disc(rgb, w, h, 80, 102, 10, (180, 60, 60))
    write_png(path, w, h, rgb)
    return path


def paper_bg(path):
    w = h = 160
    rgb = bytearray()
    for y in range(h):
        for x in range(w):
            rgb += bytes((232, 214, 188))
    write_png(path, w, h, rgb)


def background_replace(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fg, bg, after = out / "before.png", out / "new-background.png", out / "after.png"
    synthetic_screen(fg)
    paper_bg(bg)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(fg), "-i", str(bg), "-filter_complex",
         "[0:v]chromakey=0x00DC00:0.18:0.08[fg];[1:v][fg]overlay", "-frames:v", "1", str(after)])
    bw, bh, before = read_png_rgb(fg)
    aw, ah, done = read_png_rgb(after)
    corner_before, corner_after = tuple(before[0:3]), tuple(done[0:3])
    center = (80 * bw + 80) * 3
    paper, green = (232, 214, 188), (0, 220, 0)

    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b))

    report = {
        "tool": "ffmpeg chromakey",
        "licence": "ffmpeg is the machine's installed build; chromakey processes the input pixels",
        "before_corner_rgb": corner_before,
        "after_corner_rgb": corner_after,
        "before_center_rgb": tuple(before[center:center + 3]),
        "after_center_rgb": tuple(done[center:center + 3]),
        "green_removed": dist(corner_after, paper) < dist(corner_after, green),
        "subject_kept": dist(tuple(done[center:center + 3]), tuple(before[center:center + 3])) < 800,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not (report["green_removed"] and report["subject_kept"]):
        sys.exit("background replace did not change the keyed pixels while keeping the subject: " + json.dumps(report))
    print(json.dumps(report))


def bary(px, py, a, b, c):
    den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(den) < 1e-6:
        return None
    w0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / den
    w1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / den
    w2 = 1 - w0 - w1
    if w0 < -0.01 or w1 < -0.01 or w2 < -0.01:
        return None
    return w0, w1, w2


def sample(rgb, w, h, x, y):
    if x < 0 or y < 0 or x >= w - 1 or y >= h - 1:
        x = min(max(x, 0), w - 1)
        y = min(max(y, 0), h - 1)
        i = (int(y) * w + int(x)) * 3
        return rgb[i:i + 3]
    x0, y0 = int(x), int(y)
    dx, dy = x - x0, y - y0
    i = (y0 * w + x0) * 3
    j = i + 3
    k = i + w * 3
    m = k + 3
    out = bytearray(3)
    for c in range(3):
        out[c] = int((rgb[i + c] * (1 - dx) + rgb[j + c] * dx) * (1 - dy) + (rgb[k + c] * (1 - dx) + rgb[m + c] * dx) * dy)
    return bytes(out)


def warp_face(src, sw, sh, dst, dw, dh, src_pts, dst_pts, tris):
    out = bytearray(dst)
    for a, b, c in tris:
        sp = (src_pts[a], src_pts[b], src_pts[c])
        dp = (dst_pts[a], dst_pts[b], dst_pts[c])
        minx = max(0, int(min(p[0] for p in dp)))
        maxx = min(dw - 1, int(max(p[0] for p in dp)) + 1)
        miny = max(0, int(min(p[1] for p in dp)))
        maxy = min(dh - 1, int(max(p[1] for p in dp)) + 1)
        for y in range(miny, maxy + 1):
            for x in range(minx, maxx + 1):
                wts = bary(x + 0.5, y + 0.5, *dp)
                if not wts:
                    continue
                sx = wts[0] * sp[0][0] + wts[1] * sp[1][0] + wts[2] * sp[2][0]
                sy = wts[0] * sp[0][1] + wts[1] * sp[1][1] + wts[2] * sp[2][1]
                pix = sample(src, sw, sh, sx, sy)
                i = (y * dw + x) * 3
                out[i:i + 3] = pix
    return out


FACE_TRIS = [(3, 0, 4), (3, 4, 5), (3, 5, 1), (0, 4, 6), (4, 5, 6), (5, 6, 7), (5, 1, 7), (0, 6, 2), (6, 7, 2), (7, 1, 2)]


def draw_face(w, h, skin, eye, mouth, shift=0):
    rgb = bytearray([70, 90, 120] * w * h)
    pts = [(40 + shift, 70), (120 + shift, 74), (82 + shift, 150), (80 + shift, 36),
           (62 + shift, 78), (102 + shift, 80), (68 + shift, 112), (100 + shift, 114)]
    fill_disc(rgb, w, h, 80 + shift, 90, 48, skin)
    fill_disc(rgb, w, h, pts[4][0], pts[4][1], 7, eye)
    fill_disc(rgb, w, h, pts[5][0], pts[5][1], 7, eye)
    fill_disc(rgb, w, h, 84 + shift, 116, 12, mouth)
    return rgb, pts


def face_swap(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    w, h = 160, 180
    face_a, pts_a = draw_face(w, h, (222, 186, 150), (20, 20, 20), (170, 50, 50), 0)
    face_b, pts_b = draw_face(w, h, (196, 150, 110), (20, 120, 40), (120, 40, 150), 0)
    swapped = warp_face(face_b, w, h, face_a, w, h, pts_b, pts_a, FACE_TRIS)
    write_png(out / "face-a.png", w, h, face_a)
    write_png(out / "face-b.png", w, h, face_b)
    write_png(out / "swapped-b-onto-a.png", w, h, swapped)
    eye = (pts_a[4][1] * w + pts_a[4][0]) * 3
    report = {
        "tool": "triangle barycentric warp of drawn faces",
        "photographic_swap": "blocked",
        "missing": "No redistributable landmark model is bundled. InsightFace inswapper weights are not used.",
        "landmarks": "explicit coordinates of these drawings, not a detector",
        "eye_before_rgb": list(face_a[eye:eye + 3]),
        "eye_source_rgb": list(face_b[eye:eye + 3]),
        "eye_after_rgb": list(swapped[eye:eye + 3]),
    }
    before = report["eye_before_rgb"]
    after = report["eye_after_rgb"]
    source = report["eye_source_rgb"]
    report["corner_unchanged"] = list(face_a[0:3]) == list(swapped[0:3])
    report["eye_moved_toward_source"] = abs(after[1] - source[1]) < abs(before[1] - source[1])
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not (report["eye_moved_toward_source"] and report["corner_unchanged"]):
        sys.exit("face warp did not move only the face pixels: " + json.dumps(report))
    print(json.dumps(report))


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cmd", choices=["background", "face"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "background":
        background_replace(args.out)
    else:
        face_swap(args.out)
    return 0


if __name__ == "__main__":
    if sys.platform == "win32" and not sys.flags.utf8_mode:   # Windows reads, writes and prints in a legacy code page
        sys.exit(subprocess.call([sys.executable] + sys.argv, env=dict(__import__("os").environ, PYTHONUTF8="1")))
    sys.exit(main(sys.argv[1:]))
