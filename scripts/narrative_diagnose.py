"""Check the local narrative runtime. It does not download weights or call a paid API."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "scripts" / "local-runtime.lock.json"


def sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main():
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    checks = []
    model_info = lock["qwen2.5-3b-instruct-q4_k_m.gguf"]
    model = ROOT / model_info["path"]
    if model.is_file():
        got = sha256(model)
        checks.append({"name": "qwen_gguf", "present": True, "sha256": got, "match": got == model_info["sha256"]})
    else:
        checks.append({"name": "qwen_gguf", "present": False, "expected_sha256": model_info["sha256"], "match": False})
    cli_info = lock["llama-cli"]
    cli = ROOT / cli_info["path"]
    if cli.is_file():
        got = sha256(cli)
        checks.append({"name": "llama_cli", "present": True, "sha256": got, "match": got == cli_info["binary_sha256"], "release": cli_info["release"]})
    else:
        checks.append({"name": "llama_cli", "present": False, "expected_sha256": cli_info["binary_sha256"], "match": False})
    gauges = ROOT / "vendor" / "dfg-gauges"
    if (gauges / "dfg" / "cli.py").is_file():
        proc = subprocess.run(
            [sys.executable, "-m", "dfg.cli", "selftest"],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(gauges)},
            text=True, capture_output=True,
        )
        checks.append({
            "name": "dfg_selftest",
            "commit": lock["dfg-gauges"]["commit"],
            "returncode": proc.returncode,
            "tail": proc.stdout.strip().splitlines()[-1:],
            "role": "evaluation_not_generation",
        })
    report = {
        "package": "narrative-local",
        "host_installed": False,
        "paid_generation": False,
        "chain_complete": False,
        "checks": checks,
        "call": {
            "storyboard": "CINECODE_LLAMA_CLI=.local-tools/llama-b12195/llama-cli CINECODE_COPY_MODEL=.local-models/qwen2.5-3b-instruct-q4_k_m.gguf python3 scripts/storyboard_local.py BRIEF out.json",
            "import": "python3 scripts/shot_protocol.py manifest.json out.mp4",
            "gauges": "PYTHONPATH=vendor/dfg-gauges python3 -m dfg.cli selftest",
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    ok = all(item.get("match", item.get("returncode") == 0) for item in checks)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
