#!/usr/bin/env python3
"""Write Chinese lines from a brief with a local Qwen GGUF, then screen them.

The model file is not shipped. Set CINECODE_LLAMA_CLI and CINECODE_COPY_MODEL.
Official Apache-2.0 files:
  https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF
  https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF
  https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF

A host that reported about 3.2 GB available and no swap cannot be assumed to
load the 3B file. This process refuses to start llama when MemAvailable is
below twice the GGUF size. One llama process, one thread.

The screen can block or ask the same model to rewrite once. It does not
replace the text with a handwritten script. Passing the screen is not a
prose-quality pass. Exit 3 when the model cannot run. Exit 4 when the text
is rejected.
"""
import argparse
import json
import os
import re
import subprocess
import sys

SOURCES = {
    "0.5b": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF",
    "1.5b": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF",
    "3b": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF",
}
NAME_RE = re.compile(r"qwen2\.5-(0\.5b|1\.5b|3b)-instruct-q[0-9].*\.gguf$")
SYS = (
    "你只输出四行中文，每行8到14个字。不要编号，不要解释，不要品牌。"
    "四句必须是四个不同的步骤，不能互相重复。"
    "用过的液体倒进废水，禁止倒回原瓶或原容器。禁止混用清洁剂。"
    "禁止漂白水配洁厕灵或氨。不要写杀菌率。"
)
HAZARDS = (
    ("pour_back", re.compile(r"倒回|灌回|注回|倒进原|倒入原|回灌")),
    ("mix_agents", re.compile(
        r"(清洁剂|消毒液|漂白|洁厕|氨|84消毒液).{0,8}(混用|混合)"
        r"|(混用|混合).{0,8}(清洁剂|消毒液|漂白|洁厕|氨)"
        r"|掺在一起|兑在一起"
    )),
    ("bleach_acid", re.compile(r"(漂白|84).{0,8}(洁厕|氨|盐酸)|(洁厕|氨|盐酸).{0,8}(漂白|84)")),
    ("medical_claim", re.compile(r"杀菌率|99%|百分之九十九")),
)


def mem_available():
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def memory_budget(model_path):
    """Refuse a GGUF that needs a second copy of itself on top of MemAvailable."""
    size = os.path.getsize(model_path)
    need = size * 2
    avail = mem_available()
    return {"file_bytes": size, "need_bytes": need, "available_bytes": avail, "allowed": avail is not None and avail >= need}


def model_source(path):
    name = os.path.basename(path).lower()
    match = NAME_RE.search(name)
    if not match:
        return None
    return SOURCES[match.group(1)], "Apache-2.0", match.group(1)


def hazard_codes(lines):
    found = []
    for line in lines:
        for code, pattern in HAZARDS:
            for hit in pattern.finditer(line):
                clause = line[:hit.start()].split("，")[-1]
                if re.search(r"不要|禁止|别|勿|不能|不可", clause):
                    continue
                if code not in found:
                    found.append(code)
    return found


def repetition_codes(lines):
    found = []
    norm = [re.sub(r"\s+", "", line) for line in lines if line.strip()]
    if len(norm) < 4:
        found.append("too_few_lines")
    if len(set(norm)) < len(norm):
        found.append("duplicate_line")
    for line in norm:
        chars = [ch for ch in line if "\u4e00" <= ch <= "\u9fff"]
        seen = {}
        for i in range(len(chars) - 2):
            gram = "".join(chars[i:i + 3])
            seen[gram] = seen.get(gram, 0) + 1
        if any(count >= 2 for count in seen.values()):
            found.append("repeated_phrase")
            break
    shared = {}
    for line in norm:
        chars = [ch for ch in line if "\u4e00" <= ch <= "\u9fff"]
        grams = {"".join(chars[i:i + 4]) for i in range(len(chars) - 3)}
        for gram in grams:
            shared[gram] = shared.get(gram, 0) + 1
    if any(count >= 3 for count in shared.values()) and "repeated_phrase" not in found:
        found.append("repeated_phrase")
    return found


def parse_lines(text, brief):
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((">", "/", "[", "Exiting", "model", "ftype", "modalities", "using ")):
            continue
        if "t/s" in line or "available commands" in line or line.startswith("build"):
            continue
        if not any("\u4e00" <= ch <= "\u9fff" for ch in line):
            continue
        if brief and brief in line:
            continue
        lines.append(line.strip(" 0123456789.-、"))
    return lines[:8]


def llama(cli, model, sys_prompt, prompt, predict):
    proc = subprocess.run(
        [cli, "-m", model, "-sys", sys_prompt, "-p", prompt, "-st", "-n", str(predict),
         "-c", "512", "-t", "1", "--temp", "0.2", "--no-display-prompt"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "LD_LIBRARY_PATH": os.path.dirname(cli)},
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-1500:])
        return None
    return proc.stdout


def review_verdict(cli, model, lines):
    prompt = "有安全问题或明显重复就输出 REVISE，否则输出 PASS。\n" + "\n".join(lines)
    text = llama(cli, model, "你只输出 PASS 或 REVISE。", prompt, 24)
    if not text:
        return "unparsed"
    for line in text.splitlines():
        token = line.strip().split()[:1]
        if not token:
            continue
        word = token[0].strip("：:.")
        if word == "PASS":
            return "PASS"
        if word == "REVISE":
            return "REVISE"
    return "unparsed"


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
            },
        }, ensure_ascii=False))
        return 3
    known = model_source(model)
    if known is None:
        print(json.dumps({"error": "model_not_on_allowlist", "file": os.path.basename(model)}, ensure_ascii=False))
        return 3
    source, licence, size_name = known
    budget = memory_budget(model)
    if not budget["allowed"]:
        print(json.dumps({"error": "memory_insufficient", "model_size": size_name, **budget}, ensure_ascii=False))
        return 3
    brief = " ".join(args.brief.split())
    if not brief or len(brief) > 200:
        print(json.dumps({"error": "brief_rejected"}))
        return 2
    drafts = []
    problems = ["not_run"]
    revised = False
    for attempt, prompt in enumerate((brief, None)):
        if attempt == 1:
            prompt = brief + "。上一稿没有通过：" + "、".join(problems) + "。请重写四个不同的步骤。"
            revised = True
        text = llama(cli, model, SYS, prompt, 160)
        if text is None:
            return 1
        lines = parse_lines(text, brief)
        drafts.append(lines)
        problems = hazard_codes(lines) + repetition_codes(lines)
        if problems:
            continue
        verdict = review_verdict(cli, model, lines)
        # The same small model is not a second veto. A REVISE here asks for one rewrite.
        # After that rewrite, only the hazard and repetition screens can still block.
        if verdict == "REVISE" and attempt == 0:
            problems = ["model_review"]
            continue
        payload = {
            "model": os.path.basename(model),
            "model_size": size_name,
            "licence": licence,
            "source": source,
            "memory": budget,
            "threads": 1,
            "ai_generated": True,
            "revised": revised,
            "passed_screen": True,
            "prose_quality_pass": False,
            "listened": False,
            "screen": problems and problems or ["hazard_codes", "repetition_codes", "model_review:" + verdict],
            "review": verdict,
            "brief": brief,
            "drafts": drafts,
            "lines": lines,
            "text": "\n".join(lines),
        }
        # screen list above is the checks that ran, not failures.
        payload["screen"] = ["hazard_codes", "repetition_codes", "model_review:" + verdict]
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(json.dumps({"lines": lines, "revised": revised, "prose_quality_pass": False}, ensure_ascii=False))
        return 0
    payload = {
        "model": os.path.basename(model),
        "model_size": size_name,
        "licence": licence,
        "source": source,
        "memory": budget,
        "ai_generated": True,
        "revised": True,
        "passed_screen": False,
        "prose_quality_pass": False,
        "listened": False,
        "problems": problems,
        "brief": brief,
        "drafts": drafts,
        "lines": drafts[-1] if drafts else [],
        "error": "copy_quality_rejected",
    }
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"error": "copy_quality_rejected", "problems": problems}, ensure_ascii=False))
    return 4


if __name__ == "__main__":
    if sys.platform == "win32" and not sys.flags.utf8_mode:  # Windows reads, writes and prints in a legacy code page
        sys.exit(subprocess.call([sys.executable] + sys.argv, env=dict(os.environ, PYTHONUTF8="1")))
    sys.exit(main(sys.argv[1:]))
