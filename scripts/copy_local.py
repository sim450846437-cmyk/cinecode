#!/usr/bin/env python3
"""Write Chinese lines from a brief with a local Qwen GGUF. No network call, no API key.

The model file is not shipped. Set CINECODE_LLAMA_CLI and CINECODE_COPY_MODEL to the
official llama.cpp binary and the Apache-2.0 Qwen2.5-0.5B-Instruct GGUF fetched from
https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF
Exit 3 when either file is missing. The printed text is model output, not typesetting.
"""
import argparse
import json
import os
import subprocess
import sys


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    cli = os.environ.get("CINECODE_LLAMA_CLI", "")
    model = os.environ.get("CINECODE_COPY_MODEL", "")
    if not cli or not model or not os.path.isfile(cli) or not os.path.isfile(model):
        print(json.dumps({
            "error": "model_host_unavailable",
            "checked": {
                "CINECODE_LLAMA_CLI": bool(cli and os.path.isfile(cli)),
                "CINECODE_COPY_MODEL": bool(model and os.path.isfile(model)),
                "official_model": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF",
                "licence": "Apache-2.0",
            },
        }, ensure_ascii=False))
        return 3
    brief = " ".join(args.brief.split())
    if not brief or len(brief) > 200:
        print(json.dumps({"error": "brief_rejected"}))
        return 2
    proc = subprocess.run(
        [cli, "-m", model, "-sys", "你只输出四行中文，每行不超过14个字，不要编号，不要解释。",
         "-p", brief, "-st", "-n", "160", "-c", "512", "-t", "4", "--temp", "0.4",
         "--no-display-prompt"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "LD_LIBRARY_PATH": os.path.dirname(cli)},
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-1500:])
        return proc.returncode or 1
    text = proc.stdout.strip()
    lines = []
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith((">", "/", "[", "Exiting", "model", "ftype", "modalities", "using ")):
            continue
        if "t/s" in ln or "available commands" in ln:
            continue
        if not any("\u4e00" <= ch <= "\u9fff" for ch in ln):
            continue
        if brief in ln:
            continue
        lines.append(ln.strip(" 0123456789.-、"))
    payload = {
        "model": os.path.basename(model),
        "licence": "Apache-2.0",
        "source": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "ai_generated": True,
        "listened": False,
        "brief": brief,
        "text": "\n".join(lines),
        "lines": lines,
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"lines": lines}, ensure_ascii=False))
    return 0 if lines else 1


if __name__ == "__main__":
    if sys.platform == "win32" and not sys.flags.utf8_mode:  # Windows reads, writes and prints in a legacy code page
        sys.exit(subprocess.call([sys.executable] + sys.argv, env=dict(os.environ, PYTHONUTF8="1")))
    sys.exit(main(sys.argv[1:]))
