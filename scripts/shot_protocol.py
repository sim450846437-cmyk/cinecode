"""Import and concat shot files. Missing media is a recorded failure, not a film."""
import json
import re
import subprocess
import sys
from pathlib import Path


def load_manifest(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def shot_list(manifest):
    if isinstance(manifest.get("shots"), list):
        return manifest["shots"]
    story = manifest.get("story")
    if isinstance(story, dict) and isinstance(story.get("shots"), list):
        return story["shots"]
    return []


def missing_media(manifest):
    """Shots that cannot be cut because no file was imported."""
    missing = []
    shots = shot_list(manifest)
    if not shots:
        return [{"index": None, "reason": "no_shots"}]
    for shot in shots:
        if not isinstance(shot, dict):
            missing.append({"index": None, "reason": "shot_not_object"})
            continue
        resources = shot.get("resources") if isinstance(shot.get("resources"), dict) else {}
        video = resources.get("video")
        index = shot.get("index")
        if video in (None, "", "not_generated"):
            missing.append({"index": index, "reason": "not_generated"})
            continue
        if not Path(str(video)).is_file():
            missing.append({"index": index, "reason": "file_missing", "path": str(video)})
    return missing


def has_subtitle(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        text=True, capture_output=True,
    )
    return bool(proc.stdout.strip())


def subtitle_cues(path):
    """Timing and text of the first soft-subtitle stream. Empty when that stream is absent."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:s:0", "-f", "srt", "-"],
        text=True, capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    cues = []
    for block in re.split(r"\n\s*\n", proc.stdout.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing = next((line for line in lines if "-->" in line), "")
        if not timing:
            continue
        text = "\n".join(line for line in lines if line != timing and not line.isdigit())
        cues.append({"timing": re.sub(r"\s+", "", timing), "text": text})
    return cues


def same_soft_subs(src, out_path):
    source = subtitle_cues(src)
    return bool(source) and subtitle_cues(out_path) == source


def copy_one(src, out_path, keep_subs):
    maps = ["-map", "0:v:0", "-map", "0:a:0?"]
    if keep_subs:
        maps.extend(["-map", "0:s:0"])
    return subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", src, *maps, "-c", "copy", str(out_path)],
        text=True, capture_output=True,
    )


def assemble(manifest_path, out_path):
    manifest = load_manifest(manifest_path)
    gaps = missing_media(manifest)
    report = {
        "protocol": "import_then_concat",
        "chain_complete": False,
        "qualified": False,
        "manifest": str(manifest_path),
        "missing": gaps,
    }
    if gaps:
        report["error"] = "media_not_imported"
        report["out"] = None
        return report
    paths = [str(shot["resources"]["video"]) for shot in shot_list(manifest)]
    if len(paths) != len(set(paths)):
        report["error"] = "duplicate_source"
        report["out"] = None
        return report
    subtitle = manifest.get("subtitle")
    if len(paths) == 1 and not subtitle and has_subtitle(paths[0]):
        proc = copy_one(paths[0], out_path, True)
        report["protocol"] = "import_one_keep_audio_and_soft_subs"
        report["ffmpeg_returncode"] = proc.returncode
        report["ffmpeg_stderr"] = proc.stderr[-500:]
        report["shots_imported"] = 1
        report["subtitle_preserved"] = False
        if proc.returncode != 0 or not Path(out_path).is_file():
            report["error"] = "ffmpeg_failed"
            report["out"] = None
            return report
        if not same_soft_subs(paths[0], out_path):
            Path(out_path).unlink(missing_ok=True)
            report["error"] = "subtitle_not_kept"
            report["imported"] = False
            report["out"] = None
            return report
        report["subtitle_cues"] = subtitle_cues(out_path)
        report["subtitle_preserved"] = True
        report["out"] = str(out_path)
        report["imported"] = True
        return report
    if subtitle and len(paths) == 1:
        if not Path(str(subtitle)).is_file():
            report["error"] = "subtitle_missing"
            report["out"] = None
            return report
        proc = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", paths[0], "-i", str(subtitle),
             "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
             "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
             "-metadata:s:s:0", "language=zho", str(out_path)],
            text=True, capture_output=True,
        )
        report["protocol"] = "import_one_keep_audio_add_soft_subs"
        report["ffmpeg_returncode"] = proc.returncode
        report["ffmpeg_stderr"] = proc.stderr[-500:]
        report["shots_imported"] = 1
        if proc.returncode != 0 or not Path(out_path).is_file():
            report["error"] = "ffmpeg_failed"
            report["out"] = None
            return report
        report["out"] = str(out_path)
        report["imported"] = True
        report["chain_complete"] = False
        return report
    listing = Path(out_path).with_suffix(".txt")
    lines = []
    for shot in shot_list(manifest):
        lines.append("file '" + str(shot["resources"]["video"]).replace("'", "'\\''") + "'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out_path)],
        text=True, capture_output=True,
    )
    report["ffmpeg_returncode"] = proc.returncode
    report["ffmpeg_stderr"] = proc.stderr[-500:]
    if proc.returncode != 0 or not Path(out_path).is_file():
        report["error"] = "ffmpeg_failed"
        report["out"] = None
        return report
    report["out"] = str(out_path)
    report["imported"] = True
    return report


def main(argv):
    if len(argv) != 2:
        print(json.dumps({"error": "need manifest and out path"}))
        return 2
    report = assemble(argv[0], argv[1])
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report.get("imported") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
