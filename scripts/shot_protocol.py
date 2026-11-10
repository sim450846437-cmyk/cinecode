"""Import and concat shot files. Missing media is a recorded failure, not a film."""
import json
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
