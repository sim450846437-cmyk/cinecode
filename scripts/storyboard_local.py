"""Ask the local Qwen GGUF for a structured storyboard. The script is not filled in here."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import copy_local
import story_schema

SYS = (
    "只输出一个 JSON 对象，不要 markdown，不要解释。"
    "键为 plot, characters, scenes, shots。"
    "characters 每项含 id, name, description。id 与 name 都用人物姓名，description 写固定外貌。"
    "scenes 每项含 id, description。id 是地点名，description 写固定场景。"
    "shots 的镜数按用户要求，不要为了凑数复制镜头。index 从 1 递增，start_s 不倒退。"
    "每镜含 index, scene_id, character_ids, scale, action, dialogue, start_s, resources。"
    "character_ids 和 scene_id 只能引用上面的 id。scale 只能是全景、中景、近景、特写。"
    "resources 的 image, video, audio 都写 not_generated。"
    "对白里点名的人必须出现在该镜 character_ids。不要儿童，不要真实名人。"
)


def llama_long(cli, model, prompt, predict):
    proc = subprocess.run(
        [cli, "-m", model, "-sys", SYS, "-p", prompt, "-st", "-n", str(predict),
         "-c", "2048", "-t", "1", "--temp", "0.2", "--no-display-prompt"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "LD_LIBRARY_PATH": os.path.dirname(cli)},
    )
    meta = {
        "returncode": proc.returncode,
        "stderr_tail": copy_local._redact(proc.stderr),
        "n_predict": predict,
        "ctx": 2048,
        "temp": 0.2,
        "threads": 1,
    }
    if proc.returncode != 0:
        return None, meta
    return proc.stdout, meta


def attempt(cli, model, prompt, min_shots):
    started = datetime.now(timezone.utc).isoformat()
    text, meta = llama_long(cli, model, prompt, 700)
    finished = datetime.now(timezone.utc).isoformat()
    raw = text or ""
    data = story_schema.extract_json(story_schema.strip_fence(raw))
    normalizations = story_schema.normalize_story(data) if data is not None else []
    errors = story_schema.validate_story(data, min_shots=min_shots) if data is not None else ["not_json"]
    return {
        "started_at": started,
        "finished_at": finished,
        "generation": meta,
        "raw_stdout": raw,
        "parsed": data,
        "normalizations": normalizations,
        "errors": errors,
    }


def main(argv):
    cli = os.environ.get("CINECODE_LLAMA_CLI")
    model = os.environ.get("CINECODE_COPY_MODEL")
    if len(argv) not in (2, 3) or not cli or not model:
        print(json.dumps({"error": "need brief, out path, optional min_shots, CINECODE_LLAMA_CLI and CINECODE_COPY_MODEL"}))
        return 2
    brief, dest = argv[0], Path(argv[1])
    if len(argv) == 3:
        min_shots, floor_basis = int(argv[2]), "caller_argument"
    else:
        min_shots, floor_basis = story_schema.min_shots_for(brief)
    first = attempt(cli, model, brief, min_shots)
    revisions = []
    current = first
    if first["errors"]:
        repair = (
            brief
            + "\n上次输出没有通过结构校验："
            + "、".join(first["errors"][:12])
            + "。请只重新输出完整 JSON，不要沿用空白模板。"
        )
        second = attempt(cli, model, repair, min_shots)
        revisions.append({
            "reason": first["errors"],
            "raw_stdout": second["raw_stdout"],
            "errors": second["errors"],
        })
        current = second
    story = current["parsed"] if not current["errors"] else None
    if isinstance(story, dict):
        story_schema.force_not_generated(story)
    payload = {
        "inference": current["generation"].get("returncode") == 0,
        "model_file": os.path.basename(model),
        "model_sha256": copy_local._file_sha256(model),
        "llama_cli": cli,
        "llama_sha256": copy_local._file_sha256(cli),
        "brief": brief,
        "raw_stdout": first["raw_stdout"],
        "attempts": [first, *([] if not revisions else [{"raw_stdout": revisions[0]["raw_stdout"], "errors": revisions[0]["errors"], "generation": current["generation"]}])],
        "revisions": revisions,
        "errors": current["errors"],
        "story": story,
        "structure_ok": not current["errors"],
        "qualified": False,
        "picture_match": "not_run",
        "listened": False,
        "shot_floor": {"min_shots": min_shots, "basis": floor_basis},
        "quality_note": "structure, character refs, and timeline only; not a prose score",
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "inference": payload["inference"],
        "structure_ok": payload["structure_ok"],
        "errors": payload["errors"][:8],
        "revisions": len(revisions),
    }, ensure_ascii=False))
    return 0 if payload["structure_ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
