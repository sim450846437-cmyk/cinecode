#!/usr/bin/env python3
"""Photo face swap and person-video background replacement.

Landmarks: MediaPipe Face Landmarker (Apache-2.0 model, fetched from Google, not packed).
Person mask: MediaPipe selfie segmenter (Apache-2.0), same terms.
Face pixels are warped with Delaunay triangles and OpenCV seamlessClone.
The source frames are photographs, not drawings and not a green screen.

Set CINECODE_FACE_MODEL and CINECODE_SEG_MODEL. Exit 3 when a model file is absent.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# The operator supplies photographs. This script does not download people.
# A usable pair is two CC0 synthetic faces (not real persons), for example
# https://commons.wikimedia.org/wiki/File:2023-01_ai_image_of_man_02.png
# and https://commons.wikimedia.org/wiki/File:GAN_Mensch_StyleGAN2.png


def local_photo(name):
    path = os.environ.get(name, "")
    if not path or not os.path.isfile(path):
        return None
    return Path(path)


def landmarks(path, model):
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=model), num_faces=1)
    landmarker = vision.FaceLandmarker.create_from_options(options)
    image = mp.Image.create_from_file(str(path))
    result = landmarker.detect(image)
    if not result.face_landmarks:
        return None
    h, w = image.height, image.width
    return np.array([[p.x * w, p.y * h] for p in result.face_landmarks[0]], dtype=np.float32), (w, h)


def triangles(pts, shape):
    w, h = shape
    rect = (0, 0, w, h)
    subdiv = cv2.Subdiv2D(rect)
    for p in pts:
        px, py = float(np.clip(p[0], 1, w - 2)), float(np.clip(p[1], 1, h - 2))
        try:
            subdiv.insert((px, py))
        except cv2.error:
            continue
    found = []
    for tri in subdiv.getTriangleList():
        corners = [(tri[0], tri[1]), (tri[2], tri[3]), (tri[4], tri[5])]
        idx = []
        for corner in corners:
            dist = np.sum((pts - corner) ** 2, axis=1)
            i = int(np.argmin(dist))
            if dist[i] > 4:
                idx = []
                break
            idx.append(i)
        if len(idx) == 3 and len(set(idx)) == 3:
            found.append(tuple(idx))
    return found


def warp(src, dst_shape, src_pts, dst_pts, tris):
    out = np.zeros((dst_shape[1], dst_shape[0], 3), np.uint8)
    for a, b, c in tris:
        s = np.float32([src_pts[a], src_pts[b], src_pts[c]])
        d = np.float32([dst_pts[a], dst_pts[b], dst_pts[c]])
        rect = cv2.boundingRect(d)
        if rect[2] < 1 or rect[3] < 1:
            continue
        s_rect = s - [rect[0], rect[1]]
        d_rect = d - [rect[0], rect[1]]
        matrix = cv2.getAffineTransform(s, d)
        patch = cv2.warpAffine(src, matrix, (dst_shape[0], dst_shape[1]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        mask = np.zeros((dst_shape[1], dst_shape[0]), np.uint8)
        cv2.fillConvexPoly(mask, np.int32(d), 255)
        out[mask == 255] = patch[mask == 255]
    return out


def face_swap(out_dir, model):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = [local_photo("CINECODE_FACE_A"), local_photo("CINECODE_FACE_B")]
    if any(path is None for path in paths):
        print(json.dumps({"error": "photos_missing", "env": ["CINECODE_FACE_A", "CINECODE_FACE_B"]}))
        return 3
    found = []
    images = []
    for path in paths:
        hit = landmarks(path, model)
        if hit is None:
            print(json.dumps({"error": "no_face", "file": path.name}))
            return 1
        pts, shape = hit
        images.append(cv2.imread(str(path)))
        step = max(1, len(pts) // 40)
        found.append((pts[::step], shape))
    src_pts, src_shape = found[1]
    dst_pts, dst_shape = found[0]
    n = min(len(src_pts), len(dst_pts))
    src_pts, dst_pts = src_pts[:n], dst_pts[:n]
    tris = triangles(dst_pts, dst_shape)
    if len(tris) < 8:
        print(json.dumps({"error": "too_few_triangles", "n": len(tris)}))
        return 1
    swapped = warp(images[1], dst_shape, src_pts, dst_pts, tris)
    hull = cv2.convexHull(dst_pts.astype(np.int32))
    mask = np.zeros(images[0].shape[:2], np.uint8)
    cv2.fillConvexPoly(mask, hull, 255)
    center = tuple(np.mean(dst_pts, axis=0).astype(int))
    blended = cv2.seamlessClone(swapped, images[0], mask, center, cv2.NORMAL_CLONE)
    cv2.imwrite(str(out / "swap-before-a.jpg"), images[0])
    cv2.imwrite(str(out / "swap-before-b.jpg"), images[1])
    cv2.imwrite(str(out / "swap-after.jpg"), blended)
    # The hull interior must change; a corner far from the face should stay close.
    changed = float(np.mean(np.abs(blended.astype(int) - images[0].astype(int))[mask == 255]))
    h, w = images[0].shape[:2]
    corner = float(np.mean(np.abs(blended[:20, :20].astype(int) - images[0][:20, :20].astype(int))))
    report = {
        "detector": "MediaPipe Face Landmarker",
        "model_licence": "Apache-2.0",
        "model_source": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        "points_a": int(len(found[0][0])),
        "triangles": len(tris),
        "mean_abs_change_inside_face": round(changed, 2),
        "mean_abs_change_corner": round(corner, 2),
        "sources": [str(path) for path in paths],
        "source_note": os.environ.get("CINECODE_FACE_NOTE", "operator-supplied photographs; licence is not declared by this script"),
        "inswapper": "not used",
    }
    (out / "swap-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if changed < 2:
        print(json.dumps({"error": "swap_did_not_change_face", **report}))
        return 1
    print(json.dumps({k: report[k] for k in ("points_a", "triangles", "mean_abs_change_inside_face", "mean_abs_change_corner")}))
    return 0


def segment_video(out_dir, seg_model):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    src = local_photo("CINECODE_FACE_A")
    if src is None:
        print(json.dumps({"error": "photos_missing", "env": "CINECODE_FACE_A"}))
        return 3
    image = cv2.imread(str(src))
    h, w = image.shape[:2]
    options = vision.ImageSegmenterOptions(
        base_options=python.BaseOptions(model_asset_path=seg_model),
        output_confidence_masks=True)
    segmenter = vision.ImageSegmenter.create_from_options(options)
    frames, masks = [], []
    for i in range(16):
        M = np.float32([[1, 0, i * 2], [0, 1, i]])
        frame = cv2.warpAffine(image, M, (w, h), borderMode=cv2.BORDER_REFLECT)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = segmenter.segment(mp_image)
        conf = np.squeeze(result.confidence_masks[0].numpy_view())
        person = np.where(conf >= 0.5, 255, 0).astype(np.uint8)
        if person.shape[:2] != frame.shape[:2]:
            person = cv2.resize(person, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST)
        bg = np.zeros_like(frame)
        bg[:, :] = (188, 214, 232)
        comp = np.where(person[:, :, None] == 0, bg, frame)
        frames.append(comp)
        masks.append(person)
    raw = out / "frames.raw"
    with raw.open("wb") as handle:
        for frame in frames:
            handle.write(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).tobytes())
    run = subprocess.run
    proc = run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                "-r", "8", "-i", str(raw), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                str(out / "segment-after.mp4")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        sys.exit(proc.stderr.decode()[-1500:])
    cv2.imwrite(str(out / "segment-before.jpg"), image)
    cv2.imwrite(str(out / "segment-mask.jpg"), masks[0])
    cv2.imwrite(str(out / "segment-after.jpg"), frames[0])
    share = float(np.mean(masks[0] > 0))
    report = {
        "segmenter": "MediaPipe selfie segmenter",
        "model_licence": "Apache-2.0",
        "model_source": "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite",
        "frames": 16,
        "person_pixel_share": round(share, 3),
        "green_screen": False,
        "motion": "16-frame translation of the still photograph, not a green screen",
        "source": str(src),
        "source_note": os.environ.get("CINECODE_FACE_NOTE", ""),
    }
    (out / "segment-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not 0.05 < share < 0.9:
        print(json.dumps({"error": "mask_not_a_person", **report}))
        return 1
    print(json.dumps({"person_pixel_share": report["person_pixel_share"], "frames": 16}))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cmd", choices=["face", "segment"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "face":
        model = os.environ.get("CINECODE_FACE_MODEL", "")
        if not model or not os.path.isfile(model):
            print(json.dumps({"error": "landmark_model_unavailable", "env": "CINECODE_FACE_MODEL"}))
            return 3
        return face_swap(args.out, model)
    model = os.environ.get("CINECODE_SEG_MODEL", "")
    if not model or not os.path.isfile(model):
        print(json.dumps({"error": "segmenter_unavailable", "env": "CINECODE_SEG_MODEL"}))
        return 3
    return segment_video(args.out, model)


if __name__ == "__main__":
    if sys.platform == "win32" and not sys.flags.utf8_mode:  # Windows reads, writes and prints in a legacy code page
        sys.exit(subprocess.call([sys.executable] + sys.argv, env=dict(os.environ, PYTHONUTF8="1")))
    sys.exit(main(sys.argv[1:]))
