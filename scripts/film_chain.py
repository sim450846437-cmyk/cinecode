"""Text board to distinct shots to a head replacement. No film is written when a step is missing."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shot_protocol

SHORT_MIN_SHOTS = 2
FEATURE_MIN_S = 120
FEATURE_MAX_S = 180


def sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def probe_duration(path):
    import subprocess
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True, capture_output=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def assess(manifest):
    """Distinct real videos and a finished head swap are required. Looping one file is not a film."""
    reasons = []
    if manifest.get("fiction") is not True:
        reasons.append("fiction_flag_required")
    shots = shot_protocol.shot_list(manifest)
    if manifest.get("target") == "feature" and not shots:
        reasons.append("feature_has_no_shots")
    seen = {}
    durations = []
    for shot in shots:
        if not isinstance(shot, dict):
            reasons.append("shot_not_object")
            continue
        video = (shot.get("resources") or {}).get("video")
        index = shot.get("index")
        if video in (None, "", "not_generated"):
            reasons.append("not_generated:" + str(index))
            continue
        path = Path(str(video))
        if not path.is_file():
            reasons.append("file_missing:" + str(index))
            continue
        digest = sha256(path)
        if digest in seen:
            reasons.append("duplicate_shot:" + str(index))
        seen[digest] = str(path)
        durations.append(probe_duration(path) or 0)
    distinct = len(seen)
    if manifest.get("target") == "feature":
        total = sum(durations)
        if distinct < SHORT_MIN_SHOTS:
            reasons.append("feature_needs_distinct_shots")
        if total < FEATURE_MIN_S or total > FEATURE_MAX_S:
            reasons.append("feature_duration:" + str(round(total, 3)))
    elif distinct < SHORT_MIN_SHOTS:
        reasons.append("short_needs_two_distinct_shots")
    replacement = manifest.get("replacement") or {}
    if replacement.get("status") != "head_shape_and_hair_done":
        reasons.append("head_not_run")
    return {"distinct_shots": distinct, "duration_s": round(sum(durations), 3), "reasons": reasons}


def run(manifest_path, out_path, log_path):
    started = datetime.now(timezone.utc).isoformat()
    manifest = shot_protocol.load_manifest(manifest_path)
    result = assess(manifest)
    log = {
        "started_at": started,
        "manifest": str(manifest_path),
        "fiction": manifest.get("fiction") is True,
        "target": manifest.get("target"),
        "distinct_shots": result["distinct_shots"],
        "duration_s": result["duration_s"],
        "reasons": result["reasons"],
        "head_shape_and_hair": False,
        "qualified": False,
        "chain_complete": False,
        "batch": "not_started",
        "out": None,
    }
    if result["reasons"]:
        log["finished_at"] = datetime.now(timezone.utc).isoformat()
        log["error"] = result["reasons"][0]
        Path(log_path).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        return log
    # A later runner may set CINECODE_HEAD_RUNNER. Nothing here invents a swapped face.
    runner = os.environ.get("CINECODE_HEAD_RUNNER")
    if not runner:
        log["error"] = "head_runner_missing"
        log["finished_at"] = datetime.now(timezone.utc).isoformat()
        Path(log_path).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        return log
    log["error"] = "head_runner_not_invoked_in_this_build"
    log["finished_at"] = datetime.now(timezone.utc).isoformat()
    Path(log_path).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return log


def main(argv):
    if len(argv) != 3:
        print(json.dumps({"error": "need manifest, out path, and log path"}))
        return 2
    log = run(argv[0], argv[1], argv[2])
    print(json.dumps({"error": log.get("error"), "distinct_shots": log["distinct_shots"], "qualified": False}, ensure_ascii=False))
    return 0 if log.get("chain_complete") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
