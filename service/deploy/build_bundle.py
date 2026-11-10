#!/usr/bin/env python3
"""Copy a runnable subset of this checkout into a directory and write SHA256SUMS.

The archive contains source, not secrets, not model weights, and not MP4s.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
INCLUDE = [
    "SKILL.md",
    "service",
    "scripts",
    "templates/quick/film.html",
    "templates/quick/STATE.md",
    "templates/LICENSES.csv",
    "templates/type-specimen.html",
    "references/type-library.json",
    "starter/type.mjs",
    "styles/index.json",
]
SKIP_PARTS = {".git", "__pycache__", "jobs.sqlite", "auth.token"}


def sha256(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main(argv):
    dest = Path(argv[1]).resolve()
    if dest.exists():
        sys.exit(f"refusing to overwrite {dest}")
    dest.mkdir(parents=True)
    for rel in INCLUDE:
        src = KIT / rel
        if not src.exists():
            sys.exit(f"missing {rel}")
        target = dest / rel
        if src.is_dir():
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "auth.token"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    for script in (dest / "service" / "deploy").glob("*"):
        if script.is_file() and script.suffix != ".md":
            script.chmod(0o755)
    head = subprocess.run(["git", "-C", str(KIT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    sums = []
    for dirpath, dirnames, filenames in os.walk(dest):
        dirnames[:] = [name for name in dirnames if name not in SKIP_PARTS]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(dest).as_posix()
            if rel == "SHA256SUMS" or rel == "MANIFEST.json":
                continue
            sums.append(f"{sha256(path)}  {rel}")
    sums.sort()
    (dest / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    manifest = {
        "git_sha": head,
        "purpose": "localhost cinecode job process for a persistent host",
        "contains_secrets": False,
        "contains_model_weights": False,
        "contains_mp4": False,
        "target_assumption_not_measured_here": {
            "os": "Debian 13 x86_64",
            "python": "3.13.5",
            "node": "24.22.1",
            "ffmpeg": "7.1.5",
            "chrome": "156",
            "disk_free": "about 63GB",
            "pid1": "tini",
            "systemctl": "offline",
        },
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(dest)


if __name__ == "__main__":
    main(sys.argv)
