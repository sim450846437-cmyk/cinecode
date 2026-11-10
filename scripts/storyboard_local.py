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
    "shots 必须写满用户要求的镜数。每镜 action 必须不同，禁止复制上一镜来凑数。"
    "index 从 1 递增，start_s 不倒退。"
    "每镜含 index, scene_id, character_ids, scale, action, dialogue, start_s, resources。"
    "character_ids 是数组，只能引用上面的人物 id。scene_id 只能引用上面的场景 id。"
    "scale 只能是全景、中景、近景、特写。"
    "resources 的 image, video, audio 都写 not_generated。"
    "对白里点名的人必须出现在该镜 character_ids。不要儿童，不要真实名人。"
)


def official_prompt(brief, min_shots):
    """Ask for distinct shots. Do not fill the missing shots in after the model replies."""
    return (
        brief
        + "\n请写出 "
        + str(min_shots)
        + " 个彼此不同的镜头，index 从 1 连续到 "
        + str(min_shots)
        + "。每镜 action 写成不同的可见动作，不要把同一句对白拆成重复镜头。"
    )


def llama_long(cli, model, prompt, predict):
    proc = subprocess.run(
        [cli, "-m", model, "-sys", SYS, "-p", prompt, "-st", "-n", str(predict),
         "-c", "4096", "-t", "1", "--temp", "0.2", "--no-display-prompt"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "LD_LIBRARY_PATH": os.path.dirname(cli)},
    )
    meta = {
        "returncode": proc.returncode,
        "stderr_tail": copy_local._redact(proc.stderr),
        "n_predict": predict,
        "ctx": 4096,
        "temp": 0.2,
        "threads": 1,
    }
    if proc.returncode != 0:
        return None, meta
    return proc.stdout, meta


def attempt(cli, model, prompt, min_shots):
    started = datetime.now(timezone.utc).isoformat()
    text, meta = llama_long(cli, model, prompt, 320 * min_shots)
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
        requested = int(argv[2])
        if requested > story_schema.OFFICIAL_MIN_SHOTS:
            min_shots, floor_basis = requested, "caller_argument"
        else:
            min_shots, floor_basis = story_schema.OFFICIAL_MIN_SHOTS, "official_minimum_four"
    else:
        min_shots, floor_basis = story_schema.min_shots_for(brief)
    asked = official_prompt(brief, min_shots)
    first = attempt(cli, model, asked, min_shots)
    revisions = []
    current = first
    if first["errors"]:
        repair = (
            asked
            + "\n上次输出没有通过结构校验："
            + "、".join(first["errors"][:12])
            + "。请重新输出完整 JSON，shots 必须正好有 "
            + str(min_shots)
            + " 个，且每镜 action 不同。不要复制镜头，不要沿用空白模板。"
        )
        second = attempt(cli, model, repair, min_shots)
        revisions.append({
            "reason": first["errors"],
            "raw_stdout": second["raw_stdout"],
            "errors": second["errors"],
        })
        current = second
    story = current["parsed"] if not current["errors"] else None
    parsed = current["parsed"] if isinstance(current["parsed"], dict) else {}
    parsed_shots = parsed.get("shots") if isinstance(parsed.get("shots"), list) else []
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
        "shot_count": len(parsed_shots),
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
        "qualified": False,
        "shot_count": payload["shot_count"],
        "shot_floor": min_shots,
        "errors": payload["errors"][:8],
        "revisions": len(revisions),
    }, ensure_ascii=False))
    return 0 if payload["structure_ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
