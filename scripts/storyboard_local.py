"""Ask the local Qwen GGUF for a four-shot storyboard. Nothing here is a canned script."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import copy_local

SYS = "你只写四行简体中文。每行一个镜头，写出地点、动作和一句对白。四行不能相同，不能写在同一句。不要解释。"


def main(argv):
    cli = os.environ.get("CINECODE_LLAMA_CLI")
    model = os.environ.get("CINECODE_COPY_MODEL")
    if len(argv) != 2 or not cli or not model:
        print(json.dumps({"error": "need brief, out path, CINECODE_LLAMA_CLI and CINECODE_COPY_MODEL"}))
        return 2
    brief, dest = argv[0], Path(argv[1])
    started = datetime.now(timezone.utc).isoformat()
    text, meta = copy_local.llama(cli, model, SYS, brief, 240)
    finished = datetime.now(timezone.utc).isoformat()
    explained = copy_local.explain_parse(text or "", brief)
    lines = explained["lines"]
    scenes = []
    for index, line in enumerate(lines, start=1):
        scenes.append({
            "index": index,
            "visual": line,
            "action": line,
            "dialogue": line,
            "picture_status": "not_generated",
            "video_status": "not_generated",
        })
    payload = {
        "started_at": started,
        "finished_at": finished,
        "inference": text is not None,
        "model_file": os.path.basename(model),
        "model_sha256": copy_local._file_sha256(model),
        "llama_cli": cli,
        "llama_sha256": copy_local._file_sha256(cli),
        "generation": meta,
        "brief": brief,
        "raw_stdout": explained["raw_stdout"],
        "lines": lines,
        "parse_trace": explained["parse_trace"],
        "qualified": False,
        "picture_match": "not_run",
        "listened": False,
        "scenes": scenes,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"inference": payload["inference"], "lines": len(lines), "returncode": meta.get("returncode")}, ensure_ascii=False))
    return 0 if text is not None and len(lines) >= 4 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
