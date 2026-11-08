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

The screen can block. It does not ask for another sample and it does not
replace the text with a handwritten script. Passing the screen is not a
prose-quality pass, and the substance list is not a general safety proof.
Exit 3 when the model cannot run. Exit 4 when the text is rejected.
"""
import argparse
import hashlib
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


# Closed names the checker can verify. Forbidding 清洁剂 also closes 白醋 and 酒精,
# the substitutes a rewrite used after 「不使用清洁剂」. This is not every chemical.
SUBSTANCES = {
    "清洁剂": ("清洁剂", "清洁液", "洗洁精", "洗涤剂"),
    "白醋": ("白醋", "食醋", "米醋", "食用醋", "醋精", "醋"),
    "酒精": ("医用酒精", "酒精", "乙醇"),
    "漂白": ("漂白剂", "漂白粉", "漂白水", "漂白"),
    "氨": ("氨水", "氨"),
    "清水": ("清水",),
}
CLEANER_CLOSURE = ("白醋", "酒精")
FORBID_FRAMES = ("禁止使用", "不要使用", "不准使用", "不使用", "禁止用", "不要用", "别用", "勿用", "不用")
ALLOW_FRAMES = ("仅允许使用", "仅用", "只用", "只许用")
UNKNOWN_CUES = ("切勿", "严禁", "不得使用", "不得用", "避免使用", "不能用", "不可用", "不准用")
NON_OBJECT = set("的力心手劲功完太再了着过很就也")
COVERAGE = "limited list: named substances plus the cleaner substitutes 白醋 and 酒精; not a general safety proof"


def input_constraints(brief):
    """Hard limits checked before the model runs. Not a general safety proof."""
    found = []
    rules = (
        ("pour_back", re.compile(r"(清洁|液|剂|漂白|醋|酒精).{0,10}(倒回|回灌|灌回|倒进原|倒入原)|(倒回|回灌|灌回).{0,8}(瓶|容器|原)")),
        ("mix_agents", re.compile(r"(漂白|洁厕|氨|清洁剂).{0,12}(混|兑)|(混|兑).{0,12}(漂白|洁厕|氨)")),
    )
    for code, pattern in rules:
        hit = pattern.search(brief)
        if hit:
            found.append({"code": code, "span": hit.group(0)})
    return found


def _object_after(text, index):
    buf = []
    for ch in text[index:]:
        if ch in "，。！？；、,. \n" or not ("\u4e00" <= ch <= "\u9fff"):
            break
        buf.append(ch)
        if len(buf) >= 8:
            break
    return "".join(buf)


def _known_substance(token):
    best = None
    for name, aliases in SUBSTANCES.items():
        for alias in aliases:
            if token.startswith(alias) and (best is None or len(alias) > best[0]):
                best = (len(alias), name)
    return None if best is None else best[1]


def _looks_like_substance(token):
    return bool(re.search(r"剂|液|醇|醋|粉|精|化学|消毒|清洁|喷雾|漂白|氨", token))


def _scan_frames(text):
    rules, unparsed = [], []
    occupied = [False] * len(text)
    for cue in sorted(UNKNOWN_CUES, key=len, reverse=True):
        start = 0
        while True:
            found = text.find(cue, start)
            if found < 0:
                break
            if not any(occupied[found:found + len(cue)]):
                obj = _object_after(text, found + len(cue))
                span = text[found:found + len(cue) + len(obj)]
                for j in range(found, found + len(span)):
                    occupied[j] = True
                unparsed.append({"span": span, "reason": "unknown_negation"})
            start = found + len(cue)
    frames = [(len(phrase), "allow_only", phrase) for phrase in ALLOW_FRAMES]
    frames += [(len(phrase), "forbid", phrase) for phrase in FORBID_FRAMES]
    frames.sort(reverse=True)
    i = 0
    while i < len(text):
        matched = None
        for _, kind, phrase in frames:
            if text.startswith(phrase, i) and not any(occupied[i:i + len(phrase)]):
                matched = (kind, phrase)
                break
        if matched is None:
            i += 1
            continue
        kind, phrase = matched
        obj = _object_after(text, i + len(phrase))
        span = text[i:i + len(phrase) + len(obj)]
        for j in range(i, i + len(span)):
            occupied[j] = True
        if not obj or obj[0] in NON_OBJECT:
            i += len(phrase)
            continue
        substance = _known_substance(obj)
        if substance:
            rules.append({"kind": kind, "frame": phrase, "span": span, "substance": substance})
        elif _looks_like_substance(obj):
            unparsed.append({"span": span, "reason": "unknown_substance"})
        i += max(1, len(phrase))
    return rules, unparsed


def build_policy(brief, constraints=None):
    """One policy for an explicit constraints object and for the brief's negations."""
    constraints = constraints or {}
    rules, unparsed = _scan_frames(brief or "")
    forbid, allow = [], []

    def add(bucket, name):
        if name not in bucket:
            bucket.append(name)

    for name in constraints.get("forbid_substances") or []:
        if name not in SUBSTANCES:
            unparsed.append({"span": name, "reason": "unknown_constraint"})
        else:
            add(forbid, name)
    for name in constraints.get("allow_only") or []:
        if name not in SUBSTANCES:
            unparsed.append({"span": name, "reason": "unknown_constraint"})
        else:
            add(allow, name)
    for rule in rules:
        add(allow if rule["kind"] == "allow_only" else forbid, rule["substance"])
        rule["also"] = []
    if allow:
        for name in SUBSTANCES:
            if name not in allow:
                add(forbid, name)
    if "清洁剂" in forbid:
        for extra in CLEANER_CLOSURE:
            if extra not in forbid:
                add(forbid, extra)
                for rule in rules:
                    if rule["substance"] == "清洁剂":
                        rule["also"] = list(CLEANER_CLOSURE)
    return {
        "status": "needs_review" if unparsed else "clear",
        "brief": brief or "",
        "constraints": {
            "forbid_substances": list((constraints or {}).get("forbid_substances") or []),
            "allow_only": list((constraints or {}).get("allow_only") or []),
        },
        "parsed_rules": rules,
        "unparsed": unparsed,
        "forbid_substances": forbid,
        "allow_only": allow,
        "coverage": COVERAGE,
    }


def find_substances(text, names):
    """Substance mentions, including ones quoted inside 不要用. Longest alias wins."""
    hits = []
    occupied = [False] * len(text)
    aliases = []
    for name in names:
        for alias in SUBSTANCES.get(name, ()):
            aliases.append((len(alias), name, alias))
    aliases.sort(reverse=True)
    for _, name, alias in aliases:
        start = 0
        while True:
            found = text.find(alias, start)
            if found < 0:
                break
            if alias == "氨" and text.startswith("氨基", found):
                start = found + 1
                continue
            if not any(occupied[found:found + len(alias)]):
                for j in range(found, found + len(alias)):
                    occupied[j] = True
                hits.append({"substance": name, "span": alias})
            start = found + len(alias)
    return hits


def apply_policy(brief, lines, constraints=None):
    policy = build_policy(brief, constraints)
    if policy["status"] != "clear":
        return policy, [{"code": "constraint_needs_review", **item} for item in policy["unparsed"]]
    problems = []
    for hit in find_substances("\n".join(lines), policy["forbid_substances"]):
        problems.append({"code": "forbidden_substance", **hit})
    return policy, problems


def output_constraints(brief, lines, constraints=None):
    policy, problems = apply_policy(brief, lines, constraints)
    found = list(hazard_codes(lines))
    if policy["status"] != "clear":
        found.append("constraint_needs_review")
    for item in problems:
        if item["code"] == "forbidden_substance":
            found.append("forbidden_substance:" + item["substance"])
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


ACTION = set("移擦收排放进入抹扫喷整理归贴摆清干吸蘸拿刷洗过")
NUMBERED = re.compile(r"(?:^|\n)\s*(?:\d{1,2}[.、．]|[（(]\d{1,2}[）)])")


def _cjk_count(text):
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def _has_action(text):
    return any(ch in ACTION for ch in text)


def _banner(line):
    if not line or line.startswith((">", "/", "Exiting", "model", "ftype", "modalities", "using ")):
        return True
    if line.startswith("[") and '"' not in line and not any("\u4e00" <= ch <= "\u9fff" for ch in line):
        return True
    if "t/s" in line or "available commands" in line or line.startswith("build"):
        return True
    return False


def _json_array(text):
    """Use a JSON string list only when the raw text actually parses as one."""
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return None, "no_json_array"
    blob = text[start:end + 1]
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None, "json_invalid"
    if not isinstance(data, list) or not all(isinstance(item, str) and item.strip() for item in data):
        return None, "json_not_string_list"
    return [item.strip() for item in data], "json_verified"


def explain_parse(text, brief):
    """Parsed lines are separate from raw_stdout. Each drop records a reason."""
    raw = text or ""
    trace = []
    kept_blocks = []
    for raw_line in raw.splitlines() or [""]:
        line = raw_line.strip()
        if _banner(line):
            if line:
                trace.append({"stage": "banner", "text": line[:240], "reason": "llama_banner"})
            continue
        if brief and line == brief:
            trace.append({"stage": "filter", "text": line[:240], "reason": "exact_brief"})
            continue
        kept_blocks.append(line)
    body = "\n".join(kept_blocks)
    items, json_status = _json_array(body)
    trace.append({"stage": "json", "status": json_status, "count": 0 if items is None else len(items)})
    pieces = []
    if items is not None:
        pieces = items
    else:
        numbered = NUMBERED.split(body)
        if len(numbered) > 1:
            trace.append({"stage": "numbered", "count": len([p for p in numbered if p.strip()])})
            chunks = numbered
        else:
            chunks = re.split(r"(?<=[。！？；\n])", body)
            trace.append({"stage": "sentences", "count": len([p for p in chunks if p.strip()])})
        for chunk in chunks:
            sentence = chunk.strip().strip(" 0123456789.-、）)")
            if not sentence:
                continue
            clauses = [part.strip() for part in re.split(r"[，、]", sentence) if part.strip()]
            if len(clauses) > 1 and all(_has_action(part) and _cjk_count(part) >= 2 for part in clauses):
                trace.append({"stage": "clauses", "text": sentence[:240], "parts": clauses, "reason": "each_clause_has_an_action"})
                pieces.extend(clauses)
            else:
                if len(clauses) > 1:
                    trace.append({"stage": "clauses", "text": sentence[:240], "reason": "kept_together"})
                pieces.append(sentence)
    lines = []
    truncated_tail = ""
    for index, piece in enumerate(pieces):
        line = piece.strip().strip(" 0123456789.-、）)")
        if not line:
            continue
        if not any("\u4e00" <= ch <= "\u9fff" for ch in line):
            trace.append({"stage": "filter", "text": line[:240], "reason": "no_cjk"})
            continue
        if brief and line == brief:
            trace.append({"stage": "filter", "text": line[:240], "reason": "exact_brief"})
            continue
        numbered = json_status != "json_verified" and NUMBERED.search("\n" + body) is not None
        finished = bool(re.search(r"[。！？；]$", line)) or json_status == "json_verified" or (numbered and _cjk_count(line) >= 4)
        last = index == len(pieces) - 1
        if last and not finished:
            truncated_tail = line
            trace.append({"stage": "filter", "text": line[:240], "reason": "truncated_tail"})
            continue
        lines.append(line)
        trace.append({"stage": "keep", "text": line[:240]})
    return {
        "raw_stdout": raw,
        "lines": lines[:8],
        "parse_trace": trace,
        "json_status": json_status,
        "truncated_tail": truncated_tail,
        "truncated": bool(truncated_tail),
        "drafts_are_parsed": True,
    }


def parse_lines(text, brief):
    """Parsed sentences only. Synonyms of the brief are kept; the exact brief echo is not."""
    return explain_parse(text, brief)["lines"]


def _redact(text):
    kept = []
    for line in (text or "").splitlines():
        if re.search(r"bearer |authorization|api[_-]?key|token|password|secret|credential", line, re.I):
            continue
        kept.append(line)
    return "\n".join(kept[-24:])


def _file_sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _stop_reason(stderr, stdout, predict):
    low = (stderr or "").lower()
    if "context full" in low or ("n_ctx" in low and "exceed" in low):
        return "context_limit"
    if "error" in low and "llama" in low:
        return "runtime_error"
    return "not_reported_by_runtime"


def llama(cli, model, sys_prompt, prompt, predict):
    proc = subprocess.run(
        [cli, "-m", model, "-sys", sys_prompt, "-p", prompt, "-st", "-n", str(predict),
         "-c", "512", "-t", "1", "--temp", "0.2", "--no-display-prompt"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "LD_LIBRARY_PATH": os.path.dirname(cli)},
    )
    meta = {
        "returncode": proc.returncode,
        "stderr_tail": _redact(proc.stderr),
        "stop_reason": _stop_reason(proc.stderr, proc.stdout, predict),
        "n_predict": predict,
        "ctx": 512,
        "temp": 0.2,
        "threads": 1,
    }
    if proc.returncode != 0:
        return None, meta
    return proc.stdout, meta


def review_verdict(cli, model, lines):
    prompt = "有安全问题或明显重复就输出 REVISE，否则输出 PASS。\n" + "\n".join(lines)
    text, _meta = llama(cli, model, "你只输出 PASS 或 REVISE。", prompt, 24)
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
    parser.add_argument("--constraints", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.constraints:
        try:
            constraints = json.loads(args.constraints)
        except json.JSONDecodeError:
            print(json.dumps({"error": "constraints_rejected"}))
            return 2
        if not isinstance(constraints, dict):
            print(json.dumps({"error": "constraints_rejected"}))
            return 2
    else:
        constraints = {}
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
    blocked_input = input_constraints(brief)
    if blocked_input:
        payload = {
            "error": "input_constraint_rejected",
            "passed_screen": False,
            "prose_quality_pass": False,
            "ai_generated": False,
            "brief": brief,
            "input_constraints": blocked_input,
            "lines": [],
            "coverage": COVERAGE,
        }
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(json.dumps({"error": "input_constraint_rejected", "input_constraints": blocked_input}, ensure_ascii=False))
        return 4
    policy = build_policy(brief, constraints)
    if policy["status"] != "clear":
        payload = {
            "error": "constraint_needs_review",
            "passed_screen": False,
            "prose_quality_pass": False,
            "ai_generated": False,
            "brief": brief,
            "substance_policy": policy,
            "lines": [],
            "coverage": COVERAGE,
        }
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(json.dumps({"error": "constraint_needs_review", "unparsed": policy["unparsed"]}, ensure_ascii=False))
        return 4
    text, gen = llama(cli, model, SYS, brief, 160)
    if text is None:
        payload = {
            "error": "model_run_failed",
            "generation": {**gen, "model_sha256": _file_sha256(model), "model_file": os.path.basename(model)},
            "raw_stdout": None,
            "lines": [],
            "drafts_are_parsed": True,
        }
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return 1
    explained = explain_parse(text, brief)
    lines = explained["lines"]
    generation = {
        **gen,
        "model_file": os.path.basename(model),
        "model_sha256": _file_sha256(model),
        "model_size": size_name,
        "stop_reason": "possible_predict_limit" if explained["truncated"] else gen["stop_reason"],
    }
    _, substance_problems = apply_policy(brief, lines, constraints)
    problems = output_constraints(brief, lines, constraints) + repetition_codes(lines)
    drafts = [lines]
    revised = False
    common = {
        "model": os.path.basename(model),
        "model_size": size_name,
        "licence": licence,
        "source": source,
        "memory": budget,
        "threads": 1,
        "generation": generation,
        "raw_stdout": explained["raw_stdout"],
        "raw_stdout_sha256": hashlib.sha256(explained["raw_stdout"].encode("utf-8")).hexdigest(),
        "parse_trace": explained["parse_trace"],
        "json_status": explained["json_status"],
        "truncated": explained["truncated"],
        "truncated_tail": explained["truncated_tail"],
        "drafts_are_parsed": True,
        "ai_generated": True,
        "revised": False,
        "prose_quality_pass": False,
        "listened": False,
        "brief": brief,
        "substance_policy": policy,
        "drafts": drafts,
        "lines": lines,
    }
    if not problems:
        payload = {
            **common,
            "passed_screen": True,
            "screen": ["input_constraints", "substance_policy", "repetition_codes"],
            "text": "\n".join(lines),
        }
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(json.dumps({"lines": lines, "revised": revised, "prose_quality_pass": False}, ensure_ascii=False))
        return 0
    payload = {
        **common,
        "passed_screen": False,
        "problems": problems,
        "substance_hits": substance_problems,
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
