"""Install the narrative runtime into a new directory. It does not read secrets or open ports."""
import argparse
import hashlib
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "scripts" / "local-runtime.lock.json"
DEFAULT_TARGET = "/workspace/short-video-production/runtime-20261110"


def sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def safe_extract(tar_path, dest):
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with tarfile.open(tar_path) as handle:
        for member in handle.getmembers():
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise SystemExit("unsafe tar member: " + name)
            if member.issym() or member.islnk():
                raise SystemExit("unsafe tar link: " + name)
            target = (root / name).resolve()
            if root != target and root not in target.parents:
                raise SystemExit("unsafe tar path: " + name)
        handle.extractall(root, filter="data")


def place(url, dest, expect, cache):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if cache:
        cached = cache / dest.name
        if cached.is_file() and sha256(cached) == expect:
            shutil.copy2(cached, dest)
            return "cache"
        # llama binary is inside a directory in the cache layout
        nested = list(cache.rglob(dest.name))
        for item in nested:
            if item.is_file() and sha256(item) == expect:
                shutil.copy2(item, dest)
                return "cache"
    print("download", url, flush=True)
    urllib.request.urlretrieve(url, dest)
    got = sha256(dest)
    if got != expect:
        dest.unlink(missing_ok=True)
        raise SystemExit("sha256 mismatch for " + dest.name + ": " + got)
    return "url"


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--cache", default="", help="optional directory of already verified files")
    args = parser.parse_args(argv)
    target = Path(args.target)
    if target.exists():
        raise SystemExit("refuse: " + str(target) + " already exists; nothing was overwritten")
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    target.mkdir(parents=True)
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {".local-models", ".local-tools"}:
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    cache = Path(args.cache) if args.cache else None
    model = lock["qwen2.5-3b-instruct-q4_k_m.gguf"]
    model_dest = target / model["path"]
    model_from = place(model["url"], model_dest, model["sha256"], cache)
    cli = lock["llama-cli"]
    cli_dest = target / cli["path"]
    cli_dest.parent.mkdir(parents=True, exist_ok=True)
    tar_path = target / ".local-tools" / "llama-b12195-bin-ubuntu-x64.tar.gz"
    if cache:
        cached_cli = cache / cli["path"]
        if cached_cli.is_file() and sha256(cached_cli) == cli["binary_sha256"]:
            if not cli_dest.exists():
                shutil.copytree(cached_cli.parent, cli_dest.parent, dirs_exist_ok=True)
            cli_from = "cache"
        else:
            cli_from = "url"
    else:
        cli_from = "url"
    if cli_from == "url":
        print("download", cli["url"], flush=True)
        urllib.request.urlretrieve(cli["url"], tar_path)
        expect_tar = cli.get("tarball_sha256")
        if not expect_tar:
            raise SystemExit("lock has no tarball_sha256")
        got_tar = sha256(tar_path)
        if got_tar != expect_tar:
            tar_path.unlink(missing_ok=True)
            raise SystemExit("tarball sha256 mismatch: " + got_tar)
        safe_extract(tar_path, target / ".local-tools")
        tar_path.unlink(missing_ok=True)
    got = sha256(cli_dest)
    if got != cli["binary_sha256"]:
        raise SystemExit("llama-cli sha256 mismatch: " + got)
    report = {
        "target": str(target),
        "overwritten": False,
        "ports_touched": [],
        "secrets_copied": False,
        "weights_in_package": False,
        "model_from": model_from,
        "llama_from": cli_from,
        "model_sha256": sha256(model_dest),
        "llama_sha256": got,
        "host_repo_modified": False,
        "external_generation": "GenerateImage and GenerateVideo are not called by this installer",
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
