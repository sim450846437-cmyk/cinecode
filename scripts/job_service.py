#!/usr/bin/env python3
"""Localhost queue for one preauthorized cinecode motion template.

The adapter submits a job, runs that job, and returns status plus an artifact.
It binds to 127.0.0.1 only. Motion video typesets locked text; it does not
invent lines. Copy, photo face swap, person segmentation, and continuous-speech
ASR run only when the operator has fetched the named local files. Those weights
are not packed. A missing file is stored as blocked. Drawing a face or a green
screen is not a successful result.

A supported job renders only the checked-in template. The picture and sound
go through the film project's own tools/make.py, which is the Quick-mode
draft path (capture.mjs, master_audio.py, qc.py). User text is never spliced
into the page and never placed on a shell command line.

The upstream guard is not used as a sandbox. Render children do not inherit
credential-shaped environment variables, and cinecode's home files are pointed
at the job directory so the process does not read ~/.cinecode.
"""
import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))
import copy_local  # noqa: E402  substance policy shared with the copy screen
TEMPLATES = KIT / "service" / "templates"
FILM_MARK = "// ============================== FILM =============================="
HELPERS_MARK = "// ============================== HELPERS (picture) =============================="
JOB_ID_RE = re.compile(r"^job_[0-9a-f]{16}$")
IDEM_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*\S+")
ENV_DROP = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AWS_", "GITHUB", "GH_")

ALLOWED_TEMPLATES = {"home_clean_tips_v1", "stationery_tidy_v1"}
UNSUPPORTED = {
    "one_click_replace": "No one-click replace tool. replacement_target is rejected on motion_video.",
}


def _file_ready(name):
    path = os.environ.get(name, "")
    return bool(path) and os.path.isfile(path)


def _copy_model_ready():
    path = os.environ.get("CINECODE_COPY_MODEL", "")
    if not _file_ready("CINECODE_LLAMA_CLI") or not path or not os.path.isfile(path):
        return False
    return re.search(r"qwen2\.5-(0\.5b|1\.5b|3b)-instruct-q[0-9].*\.gguf$", os.path.basename(path).lower()) is not None


def current_capabilities():
    """Honest routes. configured is false until the operator points at local files."""
    copy_ok = _copy_model_ready()
    face_ok = False
    seg_ok = _file_ready("CINECODE_SEG_MODEL") and _file_ready("CINECODE_MOTION_VIDEO")
    asr_ok = importlib.util.find_spec("faster_whisper") is not None and shutil.which("ffmpeg") is not None
    return [
        {
            "id": "motion_video",
            "status": "user_text_typeset",
            "configured": True,
            "template_ids": ["home_clean_tips_v1", "stationery_tidy_v1"],
            "detail": (
                "Typesets locked text into one checked-in Quick draft and renders it with tools/make.py. "
                "home_clean_tips_v1 is only for counter cleaning. stationery_tidy_v1 is only for putting stationery away. "
                "A brief for the other theme is blocked. script.mode generate runs the local GGUF when configured, "
                "screens the lines, and typesets only lines that stay on that theme. "
                "Without the model file, generate stays blocked. Typesetting is not AI writing. "
                "profile full stays blocked because make.py final waits for an independent viewer and a user OK."
            ),
        },
        {
            "id": "copywriting",
            "status": "local_gguf",
            "configured": copy_ok,
            "detail": (
                "Writes Chinese lines with llama.cpp and an allowlisted Apache-2.0 Qwen2.5 Instruct GGUF. "
                "A hazard and repetition screen can block the text. It does not ask for another sample. "
                "The loader refuses a GGUF larger than half of MemAvailable. One thread. "
                "Without the files the job is blocked. Typesetting is not used as a substitute."
            ),
        },
        {
            "id": "face_swap",
            "status": "candidate_unverified",
            "configured": False,
            "detail": (
                "Full head plus hair is candidate_unverified, not an implementation. "
                "The caller's own face and hair photo is the source reference. "
                "The target motion clip may be a licensed stock performance; it does not have to be filmed by the caller. "
                "An ordinary CC video is not face-swap permission. The Commons clip stays a background test only. "
                "Old 3-frame files are not a rerunnable full-head video. INSwapper is inner-face only. "
                "Wan2.2-Animate-14B is not run: the main weights are Apache-2.0, the project page also says academic demonstration, "
                "and those two wordings are both kept. Replacement needs YOLOv10m (AGPL-3.0: internal test is not the same as closed distribution clearance, and AGPL is not a fee), "
                "a ViTPose directory of external tensors whose converted-weight licence is not fully checked, and SAM2 Hiera Large (Apache-2.0, not downloaded). "
                "No GPU was visible on the measured host. This service does not download the 14B."
            ),
        },
        {
            "id": "background_replace",
            "status": "selfie_segmenter",
            "configured": seg_ok,
            "detail": (
                "MediaPipe selfie segmenter on a moving-person video in CINECODE_MOTION_VIDEO. "
                "A pan of a still photograph is not accepted. The model is not packed. "
                "Without that video the job is blocked."
            ),
        },
        {
            "id": "word_accurate_talking_head_edit",
            "status": "whisper_word_times",
            "configured": asr_ok,
            "detail": (
                "Upload a continuous recording. ffmpeg decodes it and faster-whisper returns word times, "
                "then a pause trim runs. espeak-ng is not required. Meaning flags are listed and not applied. "
                "Pass reference_text to score WER and CER. A high error is blocked with asr_quality_warning "
                "instead of a plain success. Nobody listens to the audio here."
            ),
        },
        {"id": "one_click_replace", "status": "unavailable", "configured": False, "detail": UNSUPPORTED["one_click_replace"]},
    ]


CAPABILITIES = current_capabilities()
MAX_QUEUED_PER_BOT = 2


class JobFailure(Exception):
    def __init__(self, code, message, category="render", retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.category = category
        self.retryable = retryable


class Cancelled(Exception):
    pass


class Expired(Exception):
    pass


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def error_body(code, message, category, retryable=False, http=400):
    return http, {"error": {"code": code, "category": category, "message": message, "retryable": retryable}}


def load_manifest(template_id):
    if template_id not in ALLOWED_TEMPLATES:
        raise JobFailure("unknown_template", "template is not allowlisted", "request", False)
    root = (TEMPLATES / template_id).resolve()
    if root.parent != TEMPLATES.resolve() or not (root / "manifest.json").is_file():
        raise JobFailure("unknown_template", "template files are missing", "request", False)
    data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if data.get("template_id") != template_id:
        raise JobFailure("unknown_template", "template manifest does not match its id", "request", False)
    return root, data


def declared_audio_source(body):
    """Caller declaration only. An upload is not evidence that a person spoke."""
    raw = body.get("audio_source")
    if raw is None and body.get("synthetic_test") is True:
        raw = "synthetic"
    if raw is None or raw == "":
        return "unknown"
    if raw in ("synthetic", "declared_recording", "unknown"):
        return raw
    return "invalid"


UNDRAWN = ("勾勒", "测量", "擦去", "灰尘", "合上盖", "用合上", "勾画")
DRAWABLE = ("入笔筒", "入筒", "笔筒", "进盒", "入盒", "排整齐", "归位", "收好")


def action_not_drawn(template_id, lines):
    """A noun is not the action this picture draws. Mismatched verbs do not typeset."""
    if template_id != "stationery_tidy_v1":
        return []
    bad = []
    for line in lines or []:
        text = str(line).strip()
        if not text:
            continue
        if any(word in text for word in UNDRAWN) or not any(word in text for word in DRAWABLE):
            bad.append(text)
    return bad


def template_cannot_show(manifest, text):
    """Lines this picture cannot act. A theme keyword is not enough."""
    missing = []
    banned = [phrase for phrase in manifest.get("cannot_show") or [] if phrase]
    show = [word for word in manifest.get("can_show") or [] if word]
    for line in str(text).splitlines():
        line = line.strip()
        if not line:
            continue
        hit = [phrase for phrase in banned if phrase in line]
        if hit:
            missing.extend(hit)
            continue
        if show and not any(word in line for word in show):
            missing.append(line)
    return list(dict.fromkeys(missing))


def taken_constraints(body):
    raw = body.get("constraints", None)
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - {"forbid_substances", "allow_only"}:
        return error_body("invalid_field", "constraints allows only forbid_substances and allow_only", "request")
    cleaned = {}
    for key in ("forbid_substances", "allow_only"):
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            return error_body("invalid_field", key + " must be a list of substance names", "request")
        cleaned[key] = [item.strip() for item in value]
    return cleaned


def substance_decision(brief, lines, constraints):
    """Parsed rules stay with the decision. An unknown negation is not treated as safe."""
    policy = copy_local.build_policy(brief or "", constraints or {})
    if policy["status"] != "clear":
        return "constraint_needs_review", policy, (
            "A negation or constraint is outside the checked list. It is not treated as safe, and nothing is rendered."
        )
    hard = copy_local.input_constraints(brief or "")
    if hard:
        policy = dict(policy, input_constraints=hard)
        return "input_constraint_rejected", policy, (
            "The brief asks to pour a cleaner back or to mix agents. That is rejected before the model runs."
        )
    if lines:
        hits = copy_local.find_substances("\n".join(lines), policy["forbid_substances"])
        if hits:
            policy = dict(policy, substance_hits=hits)
            return "constraint_rejected", policy, (
                "The text contains a substance the constraint forbids: " + "、".join(hit["span"] for hit in hits)
            )
    return None, policy, ""


def topic_fits(manifest, text):
    """Theme keywords only. They are not a guarantee that the picture matches the words."""
    topic = manifest.get("topic") or {}
    need = [word for word in topic.get("need_any") or [] if word]
    forbid = [word for word in topic.get("forbid") or [] if word]
    if not need:
        return True
    if any(word in text for word in forbid):
        return False
    return any(word in text for word in need)


def prepare_lines(text, limit=240, max_lines=8):
    """Turn caller text into on-screen lines. The text is data, never script source."""
    import unicodedata
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    raw = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in raw):
        raise ValueError("control characters are rejected")
    raw = raw.replace("\t", " ").strip()
    if not raw:
        raise ValueError("text is empty")
    if len(raw) > limit:
        raise ValueError(f"text is longer than {limit} characters")
    lines = []
    for part in raw.split("\n"):
        part = " ".join(part.split())
        if not part:
            continue
        if len(part) > 48:
            raise ValueError("one line is longer than 48 characters; it is not cut off")
        lines.append(part)
        if len(lines) > max_lines:
            raise ValueError(f"text wraps past {max_lines} lines")
    if not lines:
        raise ValueError("text is empty")
    return lines


def _motion_output(body):
    output = body.get("output")
    if not isinstance(output, dict):
        return error_body("invalid_field", "output must be an object", "request")
    if set(output) != {"profile", "width", "height", "duration_s", "fps", "language"}:
        return error_body("invalid_field", "output fields must be profile, width, height, duration_s, fps, language", "request")
    return output


def validate(body):
    if not isinstance(body, dict):
        return error_body("invalid_json", "the body must be a JSON object", "request")
    unknown = sorted(set(body) - {
        "task_type", "template_id", "asset_ids", "brief", "script", "replacement_target",
        "output", "timeout_s", "policy_id", "idempotency_key", "budget", "mode", "upload_id",
        "synthetic_test", "reference_text", "speech_language", "audio_source",
        "constraints",
    })
    if unknown:
        return error_body("unknown_field", "unknown fields: " + ", ".join(unknown), "request")
    constraints = taken_constraints(body)
    if isinstance(constraints, tuple):
        return constraints
    task = body.get("task_type")
    if not isinstance(task, str):
        return error_body("invalid_field", "task_type must be a string", "request")
    if task in UNSUPPORTED:
        return error_body("unsupported_capability", UNSUPPORTED[task], "capability", http=422)
    if task in ("copywriting", "face_swap", "background_replace", "word_accurate_talking_head_edit"):
        return _validate_special(body, task)
    if task != "motion_video":
        return error_body("unsupported_capability", "task_type is not supported", "capability", http=422)
    template_id = body.get("template_id")
    if template_id not in ALLOWED_TEMPLATES:
        return error_body("unknown_template", "motion_video template_id must be home_clean_tips_v1 or stationery_tidy_v1", "request")
    try:
        _, manifest = load_manifest(template_id)
    except JobFailure as exc:
        return error_body(exc.code, exc.message, exc.category)
    policy = body.get("policy_id")
    if policy != manifest["policy_id"]:
        return error_body("policy_rejected", "policy_id is not the preauthorized motion policy", "auth", http=403)
    if "replacement_target" not in body or body["replacement_target"] is not None:
        return error_body("replacement_rejected", "motion_video requires replacement_target null", "request")
    assets = body.get("asset_ids")
    if not isinstance(assets, list):
        return error_body("invalid_field", "asset_ids must be an array", "request")
    if assets:
        return error_body("unknown_asset", "this template has no registered assets; asset_ids must be empty", "request")
    brief = body.get("brief", "")
    if not isinstance(brief, str) or len(brief) > 400 or any(ord(ch) < 32 and ch not in "\t" for ch in brief):
        return error_body("invalid_field", "brief must be a short string without control characters", "request")
    timeout_s = body.get("timeout_s", 900)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or not 1 <= timeout_s <= 1200:
        return error_body("invalid_field", "timeout_s must be an integer from 1 to 1200", "request")
    idem = body.get("idempotency_key")
    if idem is not None and (not isinstance(idem, str) or not IDEM_RE.fullmatch(idem)):
        return error_body("invalid_field", "idempotency_key must match [A-Za-z0-9._:-]{1,80}", "request")
    if "budget" in body:
        budget = body["budget"]
        if not isinstance(budget, dict) or set(budget) - {"currency", "max_total"}:
            return error_body("invalid_field", "budget allows only currency and max_total", "request")
        if "currency" in budget and not isinstance(budget["currency"], str):
            return error_body("invalid_field", "budget.currency must be a string", "request")
        total = budget.get("max_total")
        if total is not None and (isinstance(total, bool) or not isinstance(total, (int, float)) or total < 0):
            return error_body("invalid_field", "budget.max_total must be a number >= 0", "request")
    output = body.get("output")
    if not isinstance(output, dict):
        return error_body("invalid_field", "output must be an object", "request")
    if set(output) != {"profile", "width", "height", "duration_s", "fps", "language"}:
        return error_body("invalid_field", "output fields must be profile, width, height, duration_s, fps, language", "request")
    profile = output["profile"]
    if profile == "full":
        norm = _normalized(body, brief, timeout_s, idem, output, blocked="upstream_final_gate", lines=None, source="blocked")
        return "blocked", norm, (
            "profile full calls make.py final, which waits for an independent viewer report and a user OK. "
            "This adapter will not forge that gate. Use profile draft for the preauthorized CPU draft."
        )
    if profile != manifest["supported_profile"]:
        return error_body("invalid_field", "output.profile must be draft for this template", "request")
    draft = manifest["draft"]
    if output["width"] != draft["width"] or output["height"] != draft["height"]:
        return error_body("invalid_field", f"draft size must be {draft['width']}x{draft['height']}", "request")
    if output["duration_s"] != manifest["duration_s"] or output["fps"] != manifest["fps"]:
        return error_body("invalid_field", "duration_s and fps must match the template", "request")
    lang = output.get("language")
    if not isinstance(lang, str) or not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?", lang):
        return error_body("invalid_field", "output.language must be a short language tag", "request")
    script = body.get("script", None)
    lines = [ln for ln in manifest["locked_script"].split("\n") if ln.strip()]
    source = "template_default"
    if script is not None:
        if not isinstance(script, dict) or set(script) - {"text", "mode"} or "mode" not in script:
            return error_body("invalid_field", "script must be {text, mode} or omitted", "request")
        if script.get("mode") == "generate":
            if not _copy_model_ready():
                norm = _normalized(body, brief, timeout_s, idem, output, blocked="model_host_unavailable", lines=None, source="generate")
                return "blocked", norm, (
                    "No local GGUF is configured, so a brief is not turned into new lines. "
                    "Locked text can still be typeset. Typesetting is not AI writing."
                )
            if not isinstance(brief, str) or len(brief.strip()) < 4:
                return error_body("invalid_field", "generate needs a brief of at least 4 characters", "request")
            decision, policy, why = substance_decision(brief, None, constraints)
            if decision:
                norm = _normalized(body, brief.strip(), timeout_s, idem, output, blocked=decision, lines=None, source="generate", substance_policy=policy)
                return "blocked", norm, why
            if not topic_fits(manifest, brief):
                norm = _normalized(body, brief.strip(), timeout_s, idem, output, blocked="template_topic_mismatch", lines=None, source="generate")
                label = (manifest.get("topic") or {}).get("label") or template_id
                return "blocked", norm, (
                    f"This brief does not match the {label} template. "
                    "The cleaning graphic is not used for other subjects, and the stationery graphic is not a cleaning film."
                )
            norm = _normalized(body, brief.strip(), timeout_s, idem, output, blocked=None, lines=None, source="generate", substance_policy=policy)
            return "ok", norm, ""
        if script.get("mode") != "locked" or not isinstance(script.get("text"), str):
            return error_body("invalid_field", "script.mode must be locked or generate, and locked text must be a string", "request")
        try:
            lines = prepare_lines(script["text"])
        except ValueError as exc:
            return error_body("text_rejected", str(exc), "request")
        if not topic_fits(manifest, "\n".join(lines)):
            norm = _normalized(body, brief, timeout_s, idem, output, blocked="template_topic_mismatch", lines=None, source="user_locked")
            return "blocked", norm, (
                "Locked text is what this template draws, and it does not match the template theme. "
                "The brief is metadata and is not typeset."
            )
        unseen = template_cannot_show(manifest, "\n".join(lines))
        if unseen:
            norm = _normalized(body, brief, timeout_s, idem, output, blocked="template_cannot_show", lines=None, source="user_locked")
            return "blocked", norm, (
                "This template has no action for: " + "、".join(unseen) + ". No film is rendered."
            )
        source = "user_locked"
    decision, policy, why = substance_decision(brief, lines if source == "user_locked" else None, constraints)
    if decision:
        norm = _normalized(body, brief, timeout_s, idem, output, blocked=decision, lines=None, source=source, substance_policy=policy)
        return "blocked", norm, why
    norm = _normalized(body, brief, timeout_s, idem, output, blocked=None, lines=lines, source=source, substance_policy=policy)
    return "ok", norm, ""


def _common(body):
    timeout_s = body.get("timeout_s", 120)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or not 1 <= timeout_s <= 1200:
        return error_body("invalid_field", "timeout_s must be an integer from 1 to 1200", "request")
    idem = body.get("idempotency_key")
    if idem is not None and (not isinstance(idem, str) or not IDEM_RE.fullmatch(idem)):
        return error_body("invalid_field", "idempotency_key must match [A-Za-z0-9._:-]{1,80}", "request")
    if body.get("policy_id") != "preauthorized_motion_v1":
        return error_body("policy_rejected", "policy_id is not the preauthorized policy", "auth", http=403)
    return {"timeout_s": timeout_s, "idempotency_key": idem}


def _validate_special(body, task):
    common = _common(body)
    if isinstance(common, tuple):
        return common
    timeout_s, idem = common["timeout_s"], common["idempotency_key"]

    def blocked(code, message, mode=None, brief="", upload_id=None):
        norm = {
            "task_type": task, "mode": mode, "timeout_s": timeout_s,
            "policy_id": body.get("policy_id"), "idempotency_key": idem,
            "blocked_code": code, "lines": None, "text_source": None, "brief": brief,
            "upload_id": upload_id,
        }
        return "blocked", norm, message

    def ready(mode, brief="", upload_id=None):
        norm = {
            "task_type": task, "mode": mode, "timeout_s": timeout_s,
            "policy_id": body.get("policy_id"), "idempotency_key": idem,
            "blocked_code": None, "lines": None, "text_source": None, "brief": brief,
            "upload_id": upload_id,
            "audio_source": declared_audio_source(body),
            "reference_text": body.get("reference_text") if isinstance(body.get("reference_text"), str) else "",
            "speech_language": body.get("speech_language") if body.get("speech_language") in ("en", "zh") else "",
        }
        return "ok", norm, ""

    if task == "copywriting":
        brief = body.get("brief") or ""
        if not isinstance(brief, str) or not brief.strip() or len(brief) > 200:
            return error_body("invalid_field", "copywriting brief must be 1 to 200 characters", "request")
        if not _copy_model_ready():
            return blocked(
                "model_host_unavailable",
                "No local GGUF is configured. Set CINECODE_LLAMA_CLI and CINECODE_COPY_MODEL. Typesetting is not used as a substitute.",
                "generate", brief.strip(),
            )
        constraints = taken_constraints(body)
        if isinstance(constraints, tuple):
            return constraints
        decision, policy, why = substance_decision(brief.strip(), None, constraints)
        kind, norm, message = (
            blocked(decision, why, "generate", brief.strip()) if decision else ready("generate", brief.strip())
        )
        norm["constraints"] = constraints or None
        norm["substance_policy"] = policy
        return kind, norm, message if decision else message
    if task == "face_swap":
        return blocked(
            "candidate_unverified",
            "Full head plus hair is candidate_unverified. INSwapper inner-face output is not that result, and Wan2.2-Animate-14B is not run.",
            "unavailable",
        )
    if task == "background_replace":
        if not (_file_ready("CINECODE_SEG_MODEL") and _file_ready("CINECODE_MOTION_VIDEO")):
            return blocked(
                "motion_footage_unavailable",
                "Person segmentation needs CINECODE_SEG_MODEL and a moving-person file in CINECODE_MOTION_VIDEO. A still pan is not accepted.",
                "motion",
            )
        return ready("motion")
    if task == "word_accurate_talking_head_edit":
        upload_id = body.get("upload_id")
        reference = body.get("reference_text")
        if reference is not None and (not isinstance(reference, str) or len(reference) > 500):
            return error_body("invalid_field", "reference_text must be at most 500 characters", "request")
        speech_language = body.get("speech_language")
        if speech_language is not None and speech_language not in ("en", "zh"):
            return error_body("invalid_field", "speech_language must be en or zh", "request")
        if declared_audio_source(body) == "invalid":
            return error_body(
                "invalid_field",
                "audio_source must be synthetic, declared_recording, or unknown. An upload is not labeled as a human voice.",
                "request",
            )
        if not isinstance(upload_id, str) or not re.fullmatch(r"[a-f0-9]{16}", upload_id):
            return blocked(
                "audio_required",
                "Upload a continuous recording first. espeak-ng is not a dependency of this task.",
                "uploaded_audio",
            )
        if importlib.util.find_spec("faster_whisper") is None or shutil.which("ffmpeg") is None:
            return blocked(
                "asr_runtime_missing",
                "faster-whisper or ffmpeg is not installed. The upload is kept and no speech was invented.",
                "uploaded_audio",
            )
        return ready("uploaded_audio", body.get("brief") or "", upload_id)
    return error_body("unsupported_capability", "task_type is not supported", "capability", http=422)


def _normalized(body, brief, timeout_s, idem, output, blocked, lines, source, substance_policy=None):
    script = body.get("script", None)
    if isinstance(script, dict):
        script = {"mode": script.get("mode"), "text": script.get("text")}
    return {
        "task_type": "motion_video",
        "template_id": body.get("template_id"),
        "asset_ids": [],
        "brief": brief,
        "script": script,
        "lines": lines,
        "text_source": source,
        "brief_role": "generation_input" if source == "generate" else "metadata",
        "constraints": body.get("constraints") if isinstance(body.get("constraints"), dict) else None,
        "substance_policy": substance_policy,
        "replacement_target": None,
        "output": {
            "profile": output.get("profile"),
            "width": output.get("width"),
            "height": output.get("height"),
            "duration_s": output.get("duration_s"),
            "fps": output.get("fps"),
            "language": output.get("language"),
        },
        "timeout_s": timeout_s,
        "policy_id": body.get("policy_id"),
        "idempotency_key": idem,
        "budget": body.get("budget"),
        "blocked_code": blocked,
    }


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(self.root / "jobs.sqlite", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE,
                request_hash TEXT NOT NULL,
                request_json TEXT NOT NULL,
                state TEXT NOT NULL,
                stage TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                error_json TEXT,
                artifact_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                timeout_s INTEGER NOT NULL,
                pid INTEGER,
                peak_rss_kb INTEGER NOT NULL DEFAULT 0,
                log_rel TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS bots (
                bot_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
        """)
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(jobs)")}
        if "bot_id" not in cols:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN bot_id TEXT NOT NULL DEFAULT 'operator'")
        self.conn.commit()

    def token(self):
        path = self.root / "auth.token"
        if not path.exists():
            path.write_text(os.urandom(24).hex() + "\n", encoding="utf-8")
            os.chmod(path, 0o600)
        return path.read_text(encoding="utf-8").strip()

    def add_bot(self, bot_id):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,32}", bot_id or "") or bot_id == "operator":
            raise JobFailure("invalid_bot", "bot id must be a short lowercase name", "auth", False)
        token = os.urandom(24).hex()
        with self.lock:
            self.conn.execute(
                "INSERT INTO bots (bot_id, token_hash, created_at) VALUES (?, ?, ?)",
                (bot_id, digest(token), now()),
            )
            self.conn.commit()
        return token

    def identify(self, token):
        if token and hmac.compare_digest(token, self.token()):
            return {"bot_id": "operator", "scope": "all"}
        if not token:
            return None
        digest_value = digest(token)
        row = self.conn.execute("SELECT bot_id, token_hash FROM bots WHERE token_hash = ?", (digest_value,)).fetchone()
        if row is None or not hmac.compare_digest(row["token_hash"], digest_value):
            return None
        return {"bot_id": row["bot_id"], "scope": "bot"}

    def submit(self, norm, blocked_message="", bot_id="operator"):
        key = norm.get("idempotency_key")
        body_hash = digest(canonical({k: v for k, v in norm.items() if k != "blocked_code"} | {"blocked_code": norm.get("blocked_code")}))
        stamp = now()
        with self.lock:
            if key:
                row = self.conn.execute(
                    "SELECT * FROM jobs WHERE idempotency_key = ? AND bot_id = ?", (key, bot_id)
                ).fetchone()
                if row is not None:
                    if row["request_hash"] != body_hash:
                        return 409, {"error": {"code": "idempotency_conflict", "category": "request",
                                               "message": "this idempotency_key was already used for a different request",
                                               "retryable": False}}
                    return 200, self.public(row)
            queued = self.conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE bot_id = ? AND state IN ('queued', 'rendering', 'validating')",
                (bot_id,),
            ).fetchone()["n"]
            if not norm.get("blocked_code") and queued >= MAX_QUEUED_PER_BOT:
                return 429, {"error": {"code": "queue_full", "category": "limit",
                                       "message": f"this bot already has {queued} open jobs", "retryable": True}}
            job_id = "job_" + os.urandom(8).hex()
            work = self.root / "work" / job_id
            work.mkdir(parents=True, exist_ok=False)
            state = "blocked" if norm.get("blocked_code") else "queued"
            err = None
            if state == "blocked":
                err = json.dumps({"code": norm["blocked_code"], "category": "gate",
                                  "message": blocked_message, "retryable": False}, ensure_ascii=False)
            try:
                self.conn.execute(
                    """INSERT INTO jobs (id, idempotency_key, request_hash, request_json, state, stage,
                       error_json, created_at, updated_at, finished_at, timeout_s, log_rel, bot_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (job_id, key, body_hash, canonical(norm), state, "blocked" if state == "blocked" else "queued",
                     err, stamp, stamp, stamp if state == "blocked" else None, norm["timeout_s"],
                     f"work/{job_id}/job.log", bot_id),
                )
                self.conn.commit()
            except sqlite3.IntegrityError:
                self.conn.rollback()
                return 409, {"error": {"code": "idempotency_conflict", "category": "request",
                                       "message": "this idempotency_key is already used", "retryable": False}}
            row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return 202, self.public(row)

    def get(self, job_id, caller=None):
        if not JOB_ID_RE.fullmatch(job_id or ""):
            return None
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None or caller is None or caller.get("scope") == "all":
            return row
        if row["bot_id"] != caller["bot_id"]:
            return "forbidden"
        return row

    def public(self, row):
        req = json.loads(row["request_json"])
        artifact = json.loads(row["artifact_json"]) if row["artifact_json"] else None
        if artifact and artifact.get("relative_path"):
            local = (self.root / "work" / row["id"] / artifact["relative_path"]).resolve()
            job_root = (self.root / "work" / row["id"]).resolve()
            artifact["local_path"] = str(local) if job_root in local.parents else None
        err = json.loads(row["error_json"]) if row["error_json"] else None
        stage = row["stage"]
        generated = str(req.get("text_source") or "").startswith("model") or req.get("text_source") == "generate"
        no_model = req.get("blocked_code") == "model_host_unavailable"
        if artifact and artifact.get("model_host"):
            model_host = artifact["model_host"]
        elif generated and not no_model:
            model_host = "local_file"
        else:
            model_host = "unavailable"
        if artifact and artifact.get("generation"):
            generation = artifact["generation"]
        elif generated and model_host == "local_file":
            generation = "local_gguf_then_typeset"
        elif req.get("template_id") in ALLOWED_TEMPLATES:
            generation = "deterministic_template"
        else:
            generation = None
        return {
            "job_id": row["id"],
            "state": row["state"],
            "task_type": req.get("task_type"),
            "template_id": req.get("template_id"),
            "generation": generation,
            "model_host": model_host,
            "brief_role": req.get("brief_role"),
            "constraints": req.get("constraints"),
            "substance_policy": req.get("substance_policy"),
            "audio_source": req.get("audio_source"),
            "progress": None if row["state"] in ("queued", "blocked") else {"stage": stage, "percent": None},
            "artifact": artifact,
            "error": err,
            "cancel_requested": bool(row["cancel_requested"]),
            "timeout_s": row["timeout_s"],
            "peak_rss_kb": row["peak_rss_kb"],
            "bot_id": row["bot_id"] if "bot_id" in row.keys() else "operator",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "log": {"reference": f"/v1/jobs/{row['id']}/logs", "redacted": True},
        }

    def cancel(self, job_id, caller=None):
        row = self.get(job_id, caller)
        if row == "forbidden":
            return 403, {"error": {"code": "forbidden", "category": "auth",
                                   "message": "this job belongs to another bot", "retryable": False}}
        if row is None:
            return 404, {"error": {"code": "not_found", "category": "request", "message": "no such job", "retryable": False}}
        if row["state"] in ("succeeded", "failed", "blocked", "cancelled", "expired"):
            return 200, self.public(row)
        with self.lock:
            if row["state"] == "queued":
                self.conn.execute(
                    "UPDATE jobs SET state = 'cancelled', stage = 'cancelled', finished_at = ?, updated_at = ?, "
                    "error_json = ? WHERE id = ? AND state = 'queued'",
                    (now(), now(), json.dumps({"code": "cancelled", "category": "cancel",
                                               "message": "cancelled before start", "retryable": False}), job_id),
                )
            else:
                self.conn.execute(
                    "UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ? AND state NOT IN "
                    "('succeeded', 'failed', 'blocked', 'cancelled', 'expired')",
                    (now(), job_id),
                )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        payload = self.public(row)
        if row["cancel_requested"] and row["state"] not in ("cancelled", "succeeded", "failed", "expired", "blocked"):
            payload["state"] = "cancel_requested"
        return 200, payload

    def claim_next(self):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM jobs WHERE state = 'queued' ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            cur = self.conn.execute(
                "UPDATE jobs SET state = 'rendering', stage = 'materialize', started_at = COALESCE(started_at, ?), "
                "updated_at = ? WHERE id = ? AND state = 'queued'",
                (now(), now(), row["id"]),
            )
            self.conn.commit()
            if cur.rowcount != 1:
                return None
            return self.conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()

    def update(self, job_id, **fields):
        if not fields:
            return
        fields["updated_at"] = now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.lock:
            self.conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))
            self.conn.commit()

    def cancelled(self, job_id):
        row = self.get(job_id)
        return bool(row and row["cancel_requested"])

    def bump_rss(self, job_id, kb):
        with self.lock:
            self.conn.execute(
                "UPDATE jobs SET peak_rss_kb = MAX(peak_rss_kb, ?), updated_at = ? WHERE id = ?",
                (int(kb), now(), job_id),
            )
            self.conn.commit()

    def resume_orphans(self):
        """A rendering row whose pid is gone is queued again. A decodable MP4 already in the job is kept by the runner."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE state IN ('rendering', 'validating')"
            ).fetchall()
            changed = []
            for row in rows:
                pid = row["pid"]
                alive = False
                if pid:
                    try:
                        os.kill(pid, 0)
                        alive = True
                    except OSError:
                        alive = False
                if alive:
                    continue
                if row["cancel_requested"]:
                    self.conn.execute(
                        "UPDATE jobs SET state = 'cancelled', stage = 'cancelled', finished_at = ?, updated_at = ?, pid = NULL, "
                        "error_json = ? WHERE id = ?",
                        (now(), now(), json.dumps({"code": "cancelled", "category": "cancel",
                                                   "message": "cancel applied after the worker stopped", "retryable": False}),
                         row["id"]),
                    )
                else:
                    self.conn.execute(
                        "UPDATE jobs SET state = 'queued', stage = 'resume', updated_at = ?, pid = NULL WHERE id = ?",
                        (now(), row["id"]),
                    )
                changed.append(row["id"])
            self.conn.commit()
        return changed

    def artifact_file(self, job_id):
        row = self.get(job_id)
        if row is None or not row["artifact_json"]:
            return None
        artifact = json.loads(row["artifact_json"])
        rel = artifact.get("relative_path")
        if not rel:
            return None
        path = (self.root / "work" / job_id / rel).resolve()
        root = (self.root / "work" / job_id).resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path

    def save_upload(self, data, kind, owner):
        folder = self.root / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        uid = secrets.token_hex(8)
        (folder / f"{uid}.json").write_text(json.dumps({
            "bytes": len(data), "kind": kind, "owner": owner, "created_at": now(),
        }), encoding="utf-8")
        (folder / f"{uid}.bin").write_bytes(data)
        return uid

    def upload_for_owner(self, uid, owner):
        """Path only when this owner recorded the upload. Missing, foreign, and ownerless ids all deny."""
        if not isinstance(uid, str) or not re.fullmatch(r"[a-f0-9]{16}", uid):
            return None
        if not isinstance(owner, str) or not owner:
            return None
        folder = (self.root / "uploads").resolve()
        meta_path = (folder / f"{uid}.json").resolve()
        blob = (folder / f"{uid}.bin").resolve()
        if folder not in meta_path.parents or folder not in blob.parents:
            return None
        if not meta_path.is_file() or not blob.is_file():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        recorded = meta.get("owner")
        if not isinstance(recorded, str) or recorded != owner:
            return None
        return blob

    def derived_allowed(self, row, caller):
        """A derived file is readable only when this caller owns the upload the job used."""
        try:
            request = json.loads(row["request_json"] or "{}")
        except json.JSONDecodeError:
            return False
        upload_id = request.get("upload_id")
        if not upload_id:
            return True
        if not caller:
            return False
        if self.upload_for_owner(upload_id, row["bot_id"]) is None:
            return False
        return self.upload_for_owner(upload_id, caller["bot_id"]) is not None

    def log_text(self, job_id, limit=200):
        row = self.get(job_id)
        if row is None:
            return None
        path = self.root / "work" / job_id / "job.log"
        if not path.is_file():
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-limit:])
        return SECRET_RE.sub(r"\1=[redacted]", tail)


def isolated_env(home):
    home.mkdir(parents=True, exist_ok=True)
    env = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(part in upper for part in ENV_DROP):
            continue
        if upper.startswith("GIT_CONFIG") or upper in {"LD_LIBRARY_PATH", "LD_PRELOAD"} or upper.startswith("DYLD_"):
            continue
        env[key] = value
    env.update({
        "CINECODE_NO_OPEN": "1",
        "CINECODE_VIEWER_WAIT": "0",
        "CINECODE_FILMS": str(home / "films.json"),
        "CINECODE_SHOWN_MUSIC": str(home / "shown-music.json"),
        "CINECODE_SHOWN": str(home / "shown-styles.json"),
        "CINECODE_SHOWN_SOUNDS": str(home / "shown-sounds.json"),
        "CINECODE_SHOWN_MOVES": str(home / "shown-moves.json"),
        "CINECODE_SOUNDS_CACHE": str(home / "sounds"),
        "CINECODE_SAMPLES_CACHE": str(home / "samples"),
        "CINECODE_FORMATS": str(home / "formats"),
        "CINECODE_KEYS": str(home / "keys.env"),
        "CINECODE_TASTE": str(home / "taste.json"),
        "CINECODE_SPARKS": str(home / "sparks-seen.json"),
        "CINECODE_GUARD_SEEN": str(home / "guard-seen"),
    })
    return env


def rss_tree_kb(pid):
    total, stack, seen = 0, [pid], set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            text = Path(f"/proc/{current}/status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("VmRSS:"):
                total += int(line.split()[1])
                break
        children = Path(f"/proc/{current}/task/{current}/children")
        try:
            stack.extend(int(part) for part in children.read_text().split())
        except (OSError, ValueError):
            pass
    return total


def kill_group(pid):
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass


class Control:
    def __init__(self, store, row):
        self.store = store
        self.job_id = row["id"]
        self.work_dir = store.root / "work" / row["id"]
        self.log_path = self.work_dir / "job.log"
        elapsed = 0
        if row["started_at"]:
            started = datetime.strptime(row["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            elapsed = max(0, time.time() - started.timestamp())
        self.deadline = time.time() + max(1, int(row["timeout_s"]) - elapsed)
        self._log = self.log_path.open("a", encoding="utf-8")

    def close(self):
        self._log.close()

    def log(self, text):
        self._log.write(text.rstrip() + "\n")
        self._log.flush()

    def check(self):
        if self.store.cancelled(self.job_id):
            raise Cancelled()
        if time.time() > self.deadline:
            raise Expired()

    def set_stage(self, stage):
        self.store.update(self.job_id, stage=stage)
        self.log(f"stage {stage}")

    def pump(self, proc):
        self.store.update(self.job_id, pid=proc.pid)
        while True:
            self.store.bump_rss(self.job_id, rss_tree_kb(proc.pid))
            code = proc.poll()
            if code is not None:
                self.store.update(self.job_id, pid=None)
                return code
            if self.store.cancelled(self.job_id):
                kill_group(proc.pid)
                proc.wait(timeout=5)
                self.store.update(self.job_id, pid=None)
                raise Cancelled()
            if time.time() > self.deadline:
                kill_group(proc.pid)
                proc.wait(timeout=5)
                self.store.update(self.job_id, pid=None)
                raise Expired()
            time.sleep(0.4)

    def run(self, args, cwd, env, stage):
        self.check()
        self.set_stage(stage)
        self.log("argv " + " ".join(args))
        proc = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=self._log, stderr=subprocess.STDOUT,
            start_new_session=True, text=True,
        )
        return self.pump(proc)


def splice_film(template_root, film_html):
    section = (template_root / "film_section.js").read_text(encoding="utf-8")
    if FILM_MARK in section or HELPERS_MARK in section or "fieldGathers" in section:
        raise JobFailure("template_invalid", "the film section is not a safe overlay", "template", False)
    text = film_html.read_text(encoding="utf-8")
    start = text.find(FILM_MARK)
    end = text.find(HELPERS_MARK)
    if start < 0 or end < 0 or end <= start:
        raise JobFailure("template_invalid", "film.html is missing the Quick-mode markers", "template", False)
    written = text[:start + len(FILM_MARK)] + "\n" + section.strip() + "\n\n" + text[end:]
    ready = "window.READY = loadType(TYPE).then(loadFormulas).then(() => document.fonts.ready).then(() => {"
    chained = "window.READY = loadCopy().then(() => loadType(TYPE)).then(loadFormulas).then(() => document.fonts.ready).then(() => {"
    if ready not in written:
        raise JobFailure("template_invalid", "film.html READY hook was not found", "template", False)
    film_html.write_text(written.replace(ready, chained, 1), encoding="utf-8")
    written = film_html.read_text(encoding="utf-8")
    if "fieldGathers" in written or written.count(FILM_MARK) != 1:
        raise JobFailure("template_invalid", "splice left the example scene or duplicated the marker", "template", False)


def prepare_project(work, request, env, ctl=None):
    """Build a Quick film from the allowlisted template. request text is not written into the page."""
    template_id = request["template_id"]
    if request.get("output", {}).get("profile") != "draft":
        raise JobFailure("profile_rejected", "only the draft profile is rendered", "gate", False)
    root, manifest = load_manifest(template_id)
    film = work / "film"
    marker = film / ".materialized"
    if not marker.is_file():
        if film.exists():
            shutil.rmtree(film)
        film.mkdir(parents=True)
        init = [sys.executable, str(KIT / "scripts" / "init_film.py"), str(film), "--quick", "--title", "Counter Steps"]
        if ctl:
            code = ctl.run(init, film, env, "materialize")
            if code != 0:
                raise JobFailure("init_failed", f"init_film.py exited {code}", "render", True)
        else:
            proc = subprocess.run(init, cwd=film, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if proc.returncode != 0:
                raise JobFailure("init_failed", proc.stdout[-500:], "render", True)
        splice_film(root, film / "film.html")
        page = (film / "film.html").read_text(encoding="utf-8")
        brief = request.get("brief") or ""
        script_text = ""
        if isinstance(request.get("script"), dict):
            script_text = request["script"].get("text") or ""
        if (len(brief) >= 12 and brief in page) or (len(script_text) >= 8 and script_text in page):
            raise JobFailure("isolation", "request text leaked into film.html", "security", False)
        lines = request.get("lines") or [ln for ln in manifest["locked_script"].split("\n") if ln.strip()]
        source_name = request.get("text_source") or "template_default"
        (film / "copy.json").write_text(json.dumps({
            "lines": lines,
            "source": source_name,
            "ai_generated": str(source_name).startswith("model"),
            "prose_quality_pass": request.get("prose_quality_pass") is True,
            "storyboard": (manifest.get("topic") or {}).get("label") or manifest["template_id"],
            "listened": False,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        (film / "STATE.md").write_text((root / "STATE.md").read_text(encoding="utf-8"), encoding="utf-8")
        audit = film / "review" / "sound-audit.md"
        audit.parent.mkdir(parents=True, exist_ok=True)
        audit.write_text((root / manifest["sound_audit"]).read_text(encoding="utf-8"), encoding="utf-8")
        font = manifest["font"]
        configured = Path(font["source"])
        source = configured.resolve()
        if not configured.is_absolute() or not str(configured).startswith("/usr/share/fonts/") or not str(source).startswith("/usr/share/fonts/"):
            raise JobFailure("font_missing", "the font allowlist is not a system font path", "template", False)
        if not source.is_file():
            raise JobFailure("font_missing", "the allowlisted system font is not installed", "template", False)
        dest = film / font["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        with (film / "LICENSES.csv").open("a", encoding="utf-8") as handle:
            handle.write(
                f"{font['dest']},{font['family']},{font['author']},{font['source_url']},{font['licence']},"
                f"{font['licence_url']},{font['family']} ({font['licence']}),copied into the job workspace only,"
                f"{now()},{manifest['title']},{font['notes']}\n"
            )
        marker.write_text(manifest["template_id"] + "\n", encoding="utf-8")
    return film, manifest


def draft_argv(film, workers):
    """The only render command. Callers cannot add arguments."""
    try:
        count = int(workers)
    except (TypeError, ValueError):
        raise JobFailure("invalid_workers", "workers must be 1 to 3", "template", False) from None
    if count < 1 or count > 3:
        raise JobFailure("invalid_workers", "workers must be 1 to 3", "template", False)
    return [sys.executable, str(Path(film) / "tools" / "make.py"), "draft", "--workers", str(count)]


def ffprobe_movie(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,sample_rate,nb_frames",
         "-of", "json", str(path)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if proc.returncode != 0:
        raise JobFailure("undecodable", "ffprobe could not read the MP4", "validate", True)
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video:
        raise JobFailure("undecodable", "the file has no video stream", "validate", True)
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    num, den = rate.split("/")
    fps = float(num) / float(den) if float(den) else 0
    return {
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "duration_s": float((data.get("format") or {}).get("duration") or 0),
        "video_codec": video.get("codec_name"),
        "audio_codec": None if audio is None else audio.get("codec_name"),
        "sample_rate": None if audio is None else int(audio.get("sample_rate") or 0),
        "subtitle_streams": sum(1 for s in streams if s.get("codec_type") == "subtitle"),
        "bytes": path.stat().st_size,
    }


def sha256_file(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


class CinecodeDraftRunner:
    """Run the official Quick draft. User fields are not arguments."""

    def _screen_copy(self, request, ctl, env):
        out = ctl.work_dir / "output"
        out.mkdir(parents=True, exist_ok=True)
        dest = out / "copy-gate.json"
        argv = [sys.executable, str(KIT / "scripts" / "copy_local.py"),
                "--brief", request.get("brief") or "", "--out", str(dest)]
        if request.get("constraints"):
            argv.extend(["--constraints", json.dumps(request["constraints"], ensure_ascii=False)])
        code = ctl.run(argv, ctl.work_dir, env, "render")
        payload = {}
        if dest.is_file():
            try:
                payload = json.loads(dest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        if code == 0 and payload.get("passed_screen") and payload.get("prose_quality_pass") is True and payload.get("lines"):
            _, manifest = load_manifest(request["template_id"])
            mismatched = action_not_drawn(request["template_id"], payload["lines"])
            if mismatched:
                return {
                    "state": "blocked",
                    "artifact": {
                        "relative_path": "output/copy-gate.json",
                        "sha256": sha256_file(dest),
                        "bytes": dest.stat().st_size,
                        "delivered": False,
                        "listened": False,
                        "prose_quality_pass": False,
                        "qualified": False,
                        "lines": payload["lines"],
                    },
                    "error": {
                        "code": "action_not_drawn",
                        "category": "gate",
                        "message": "The model lines do not name an action this picture draws. They were not typeset.",
                        "problems": mismatched,
                        "retryable": False,
                    },
                }
            unseen = template_cannot_show(manifest, "\n".join(payload["lines"]))
            if unseen:
                return {
                    "state": "blocked",
                    "artifact": {
                        "relative_path": "output/copy-gate.json",
                        "sha256": sha256_file(dest),
                        "bytes": dest.stat().st_size,
                        "delivered": False,
                        "listened": False,
                        "prose_quality_pass": False,
                    },
                    "error": {
                        "code": "template_cannot_show",
                        "category": "gate",
                        "message": "The model text asks for an action this template does not animate: " + "、".join(unseen),
                        "retryable": False,
                    },
                }
            if not topic_fits(manifest, "\n".join(payload["lines"])):
                return {
                    "state": "blocked",
                    "artifact": {
                        "relative_path": "output/copy-gate.json",
                        "sha256": sha256_file(dest),
                        "bytes": dest.stat().st_size,
                        "delivered": False,
                        "listened": False,
                        "prose_quality_pass": False,
                    },
                    "error": {
                        "code": "template_topic_mismatch",
                        "category": "gate",
                        "message": "The model text left this template's theme. It was not typeset, and no handwritten lines were substituted.",
                        "retryable": False,
                    },
                }
            request["lines"] = payload["lines"]
            request["text_source"] = "model_generate_revised" if payload.get("revised") else "model_generate"
            request["prose_quality_pass"] = True
            return None
        info = None
        if dest.is_file():
            info = {
                "relative_path": "output/copy-gate.json",
                "sha256": sha256_file(dest),
                "bytes": dest.stat().st_size,
                "delivered": False,
                "listened": False,
                "prose_quality_pass": payload.get("prose_quality_pass") is True,
                "qualified": False,
            }
        code_name = payload.get("error") or "copy_quality_rejected"
        if code == 3:
            code_name = payload.get("error") or "model_host_unavailable"
        return {
            "state": "blocked",
            "artifact": info,
            "error": {
                "code": code_name,
                "category": "gate",
                "message": "The local model did not produce lines the screen could accept. No handwritten replacement was used.",
                "problems": payload.get("problems"),
                "retryable": False,
            },
        }

    def run(self, row, ctl):
        request = json.loads(row["request_json"])
        env = isolated_env(ctl.work_dir / "cinecode-home")
        if request.get("text_source") == "generate":
            screened = self._screen_copy(request, ctl, env)
            if screened is not None:
                return screened
        film, manifest = prepare_project(ctl.work_dir, request, env, ctl)
        ctl.check()
        delivered = sorted(film.glob("*-draft.mp4"))
        if not delivered:
            code = ctl.run(draft_argv(film, 1), film, env, "render")
            ctl.log(f"make.py exit {code}")
            delivered = sorted(film.glob("*-draft.mp4"))
        else:
            code = 0
            ctl.log("resume found an existing delivered draft, skipping make.py")
        produced = delivered[-1] if delivered else None
        if produced is None:
            drafts = sorted((film / "renders").glob("draft-v*.mp4"))
            produced = drafts[-1] if drafts else None
        if produced is None or not produced.is_file():
            raise JobFailure("render_failed", f"make.py exited {code} and left no MP4", "render", code != 2)
        ctl.set_stage("validate")
        info = ffprobe_movie(produced)
        expected = manifest["draft"]
        if info["width"] != expected["width"] or info["height"] != expected["height"]:
            raise JobFailure("output_mismatch", f"expected {expected['width']}x{expected['height']}, got {info['width']}x{info['height']}", "validate", False)
        if abs(info["duration_s"] - manifest["duration_s"]) > 0.2:
            raise JobFailure("output_mismatch", f"duration {info['duration_s']} is outside the template", "validate", False)
        if not info["audio_codec"]:
            raise JobFailure("output_mismatch", "the MP4 has no audio stream", "validate", False)
        out = ctl.work_dir / "output"
        out.mkdir(parents=True, exist_ok=True)
        target = out / "film.mp4"
        shutil.copyfile(produced, target)
        info.update({
            "relative_path": "output/film.mp4",
            "sha256": sha256_file(target),
            "delivered": code == 0 and bool(delivered),
            "profile": "draft",
            "template_id": manifest["template_id"],
            "generation": "local_gguf_then_typeset" if str(request.get("text_source", "")).startswith("model") else "deterministic_template",
            "model_host": "local_file" if str(request.get("text_source", "")).startswith("model") else "unavailable",
            "arbitrary_copy": str(request.get("text_source", "")).startswith("model"),
            "ai_generated": str(request.get("text_source", "")).startswith("model"),
            "prose_quality_pass": request.get("prose_quality_pass") is True,
            "qualified": False,
            "storyboard": (manifest.get("topic") or {}).get("label") or manifest["template_id"],
            "listened": False,
            "serial_workers": 1,
            "make_exit": code,
        })
        if code == 0 and produced.is_file():
            return {"state": "succeeded", "artifact": info, "error": None}
        summary = ""
        last = film / "logs" / "last-make.txt"
        if last.is_file():
            summary = " ".join(last.read_text(encoding="utf-8", errors="replace").splitlines()[:8])[:500]
        return {
            "state": "blocked",
            "artifact": info,
            "error": {
                "code": "quality_gate",
                "category": "gate",
                "message": "make.py did not deliver the draft. " + summary,
                "retryable": False,
            },
        }


def finish(store, job_id, state, error=None, artifact=None):
    store.update(
        job_id,
        state=state,
        stage=state,
        finished_at=now(),
        pid=None,
        error_json=None if error is None else json.dumps(error, ensure_ascii=False),
        artifact_json=None if artifact is None else json.dumps(artifact, ensure_ascii=False),
    )


class DispatchRunner:
    """Route a queued job to the tool that matches its task. User text is never a shell argument."""

    def run(self, row, ctl):
        request = json.loads(row["request_json"])
        task = request.get("task_type")
        if task == "motion_video":
            return CinecodeDraftRunner().run(row, ctl)
        out = ctl.work_dir / "output"
        out.mkdir(parents=True, exist_ok=True)
        env = isolated_env(ctl.work_dir / "cinecode-home")
        if task == "copywriting":
            produced = out / "lines.json"
            argv = [sys.executable, str(KIT / "scripts" / "copy_local.py"),
                    "--brief", request.get("brief") or "", "--out", str(produced)]
            if request.get("constraints"):
                argv.extend(["--constraints", json.dumps(request["constraints"], ensure_ascii=False)])
            code = ctl.run(argv, ctl.work_dir, env, "render")
            if code == 4 or code == 3:
                payload = {}
                if produced.is_file():
                    try:
                        payload = json.loads(produced.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        payload = {}
                info = {
                    "relative_path": "output/lines.json",
                    "sha256": sha256_file(produced) if produced.is_file() else None,
                    "bytes": produced.stat().st_size if produced.is_file() else 0,
                    "delivered": False,
                    "listened": False,
                    "prose_quality_pass": False,
                }
                return {
                    "state": "blocked",
                    "artifact": info,
                    "error": {
                        "code": payload.get("error") or "copy_quality_rejected",
                        "category": "gate",
                        "message": "The screen rejected the model text. No handwritten replacement was used.",
                        "problems": payload.get("problems"),
                        "retryable": False,
                    },
                }
        elif task == "background_replace":
            code = ctl.run([sys.executable, str(KIT / "scripts" / "photo_tools.py"), "motion", "--out", str(out)],
                           ctl.work_dir, env, "render")
            produced = out / "segment-after.mp4"
        elif task == "face_swap":
            return {
                "state": "blocked",
                "artifact": None,
                "error": {
                    "code": "candidate_unverified",
                    "category": "gate",
                    "message": "Full head plus hair is candidate_unverified. No model is downloaded or run for this job.",
                    "retryable": False,
                },
            }
        elif task == "word_accurate_talking_head_edit":
            audio = ctl.store.upload_for_owner(request.get("upload_id"), row["bot_id"])
            if audio is None:
                ctl.log("upload denied")
                return {
                    "state": "blocked",
                    "artifact": None,
                    "error": {
                        "code": "forbidden",
                        "category": "auth",
                        "message": "upload is not available to this job",
                        "retryable": False,
                    },
                }
            argv = [sys.executable, str(KIT / "scripts" / "asr_edit.py"),
                    "--audio", str(audio), "--out", str(out),
                    "--audio-source", request.get("audio_source") or "unknown"]
            if request.get("reference_text"):
                argv.extend(["--reference", request["reference_text"]])
            if request.get("speech_language"):
                argv.extend(["--language", request["speech_language"]])
            code = ctl.run(argv, ctl.work_dir, env, "render")
            produced = out / "after.mp4"
            if code == 4 and produced.is_file():
                report = {}
                report_path = out / "report.json"
                if report_path.is_file():
                    try:
                        report = json.loads(report_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        report = {}
                return {
                    "state": "blocked",
                    "artifact": {
                        "relative_path": "output/after.mp4",
                        "sha256": sha256_file(produced),
                        "bytes": produced.stat().st_size,
                        "delivered": True,
                        "listened": False,
                        "acceptance_pass": False,
                        "quality_warning": "asr_quality_warning",
                        "wer": report.get("wer"),
                        "cer": report.get("cer"),
                    },
                    "error": {
                        "code": "asr_quality_warning",
                        "category": "gate",
                        "message": "Recognition error against the reference is too high to count as a plain success. The file can still be downloaded. Meaning edits were not applied.",
                        "retryable": False,
                    },
                }
        else:
            raise JobFailure("unsupported_capability", "this worker does not run that task", "capability", False)
        if task == "copywriting" and produced.is_file():
            try:
                payload = json.loads(produced.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            quality = payload.get("prose_quality_pass") is True
            info = {
                "relative_path": "output/lines.json",
                "sha256": sha256_file(produced),
                "bytes": produced.stat().st_size,
                "delivered": False,
                "listened": False,
                "acceptance_pass": False,
                "qualified": False,
                "prose_quality_pass": quality,
                "ai_generated": True,
                "lines": payload.get("lines") or [],
                "model_file": (payload.get("generation") or {}).get("model_file"),
                "model_sha256": (payload.get("generation") or {}).get("model_sha256"),
            }
            if code != 0 or not quality:
                return {
                    "state": "blocked",
                    "artifact": info,
                    "error": {
                        "code": payload.get("error") or "copy_quality_rejected",
                        "category": "gate",
                        "message": "Model text did not pass the copy screen. It is not queued as a film.",
                        "problems": payload.get("problems"),
                        "retryable": False,
                    },
                }
            info["delivered"] = True
            return {"state": "succeeded", "artifact": info, "error": None}
        if code != 0 or not produced.is_file():
            raise JobFailure("render_failed", f"{task} exited {code}", "render", code not in (2, 3))
        speech_report = {}
        report_path = out / "report.json"
        if task == "word_accurate_talking_head_edit" and report_path.is_file():
            try:
                speech_report = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                speech_report = {}
        info = {
            "relative_path": f"output/{produced.name}",
            "sha256": sha256_file(produced),
            "bytes": produced.stat().st_size,
            "delivered": True,
            "task_type": task,
            "generation": "local_gguf" if task == "copywriting" else "local_tool",
            "model_host": "local_file" if task == "copywriting" else "local_weights",
            "arbitrary_copy": task == "copywriting",
            "ai_generated": task == "copywriting",
            "listened": False,
            "acceptance_pass": False,
        }
        if speech_report.get("wer") is not None:
            info["wer"] = speech_report["wer"]
            info["cer"] = speech_report["cer"]
            info["heard_by_asr"] = speech_report["heard_by_asr"]
        return {"state": "succeeded", "artifact": info, "error": None}


def process_one(store, runner):
    row = store.claim_next()
    if row is None:
        return False
    ctl = Control(store, row)
    try:
        result = runner.run(row, ctl)
        finish(store, row["id"], result["state"], result.get("error"), result.get("artifact"))
        ctl.log(f"finished {result['state']}")
    except Cancelled:
        finish(store, row["id"], "cancelled",
               {"code": "cancelled", "category": "cancel", "message": "cancelled while running", "retryable": False})
        ctl.log("cancelled")
    except Expired:
        finish(store, row["id"], "expired",
               {"code": "timeout", "category": "limit", "message": "the job exceeded timeout_s", "retryable": True})
        ctl.log("expired")
    except JobFailure as exc:
        finish(store, row["id"], "failed",
               {"code": exc.code, "category": exc.category, "message": exc.message, "retryable": exc.retryable})
        ctl.log(f"failed {exc.code}: {exc.message}")
    except Exception as exc:
        ctl.log(traceback.format_exc(limit=8))
        finish(store, row["id"], "failed",
               {"code": "worker_error", "category": "render", "message": exc.__class__.__name__, "retryable": True})
    finally:
        ctl.close()
    return True


def _upload_kind(data):
    if len(data) < 12:
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    if data[4:8] == b"ftyp":
        return "mp4"
    return None


class JobHandler(BaseHTTPRequestHandler):
    server_version = "cinecode-job/0"

    def log_message(self, fmt, *args):
        return

    def _caller(self):
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else ""
        caller = self.server.store.identify(token)
        if not caller:
            self._send(401, {"error": {"code": "unauthorized", "category": "auth",
                                       "message": "Bearer token required", "retryable": False}})
        return caller

    def _send(self, status, payload=None, body=None, content_type="application/json; charset=utf-8"):
        data = body if body is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 16384:
            self._send(400, {"error": {"code": "body_too_large", "category": "request",
                                       "message": "body limit is 16 KiB", "retryable": False}})
            return None
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self._send(400, {"error": {"code": "invalid_json", "category": "request",
                                       "message": "body is not JSON", "retryable": False}})
            return None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/v1/health":
            self._send(200, {"ok": True, "bind": "127.0.0.1", "boot_persistent": False})
            return
        caller = self._caller()
        if not caller:
            return
        store = self.server.store
        if path == "/v1/capabilities":
            self._send(200, {"capabilities": current_capabilities(), "bind": "127.0.0.1", "multi_tenant": False, "bots": True})
            return
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["v1", "jobs"] and parts[3] == "logs":
            visible = store.get(parts[2], caller)
            if visible == "forbidden":
                self._send(403, {"error": {"code": "forbidden", "category": "auth",
                                           "message": "this job belongs to another bot", "retryable": False}})
                return
            text = store.log_text(parts[2]) if visible else None
            if text is None:
                self._send(404, {"error": {"code": "not_found", "category": "request", "message": "no such job", "retryable": False}})
                return
            self._send(200, body=text.encode("utf-8"), content_type="text/plain; charset=utf-8")
            return
        if len(parts) == 4 and parts[:2] == ["v1", "jobs"] and parts[3] == "artifact":
            visible = store.get(parts[2], caller)
            if visible == "forbidden":
                self._send(403, {"error": {"code": "forbidden", "category": "auth",
                                           "message": "this job belongs to another bot", "retryable": False}})
                return
            if visible and not store.derived_allowed(visible, caller):
                self._send(403, {"error": {"code": "forbidden", "category": "auth",
                                           "message": "upload is not available to this caller", "retryable": False}})
                return
            target = store.artifact_file(parts[2]) if visible else None
            if target is None:
                self._send(404, {"error": {"code": "not_ready", "category": "request",
                                           "message": "no registered artifact", "retryable": True}})
                return
            data = target.read_bytes()
            kind = {
                ".mp4": "video/mp4", ".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".wav": "audio/wav", ".json": "application/json",
            }.get(target.suffix, "application/octet-stream")
            self._send(200, body=data, content_type=kind)
            return
        if len(parts) == 3 and parts[:2] == ["v1", "jobs"]:
            row = store.get(parts[2], caller)
            if row == "forbidden":
                self._send(403, {"error": {"code": "forbidden", "category": "auth",
                                           "message": "this job belongs to another bot", "retryable": False}})
                return
            if row is None:
                self._send(404, {"error": {"code": "not_found", "category": "request", "message": "no such job", "retryable": False}})
                return
            payload = store.public(row)
            if row["cancel_requested"] and row["state"] == "rendering":
                payload["state"] = "cancel_requested"
            self._send(200, payload)
            return
        self._send(404, {"error": {"code": "not_found", "category": "request", "message": "no such route", "retryable": False}})

    def do_POST(self):
        caller = self._caller()
        if not caller:
            return
        path = self.path.split("?", 1)[0]
        store = self.server.store
        parts = path.strip("/").split("/")
        if path == "/v1/uploads":
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 12 * 1024 * 1024:
                self._send(400, {"error": {"code": "body_too_large", "category": "request",
                                           "message": "upload must be 1 byte to 12 MiB", "retryable": False}})
                return
            data = self.rfile.read(length)
            kind = _upload_kind(data)
            if kind is None:
                self._send(400, {"error": {"code": "unsupported_media", "category": "request",
                                           "message": "upload must be wav, mp3, or mp4", "retryable": False}})
                return
            uid = store.save_upload(data, kind, caller["bot_id"])
            self._send(201, {"upload_id": uid, "bytes": len(data), "kind": kind})
            return
        if path == "/v1/jobs":
            body = self._read_json()
            if body is None:
                return
            result = validate(body)
            if isinstance(result[0], int):
                self._send(result[0], result[1])
                return
            kind, norm, message = result
            upload_id = norm.get("upload_id") if isinstance(norm, dict) else None
            if upload_id and store.upload_for_owner(upload_id, caller["bot_id"]) is None:
                self._send(403, {"error": {"code": "forbidden", "category": "auth",
                                           "message": "upload is not available to this caller", "retryable": False}})
                return
            if kind == "blocked":
                status, payload = store.submit(norm, message, caller["bot_id"])
            else:
                status, payload = store.submit(norm, "", caller["bot_id"])
            self._send(status, payload)
            return
        if len(parts) == 4 and parts[:2] == ["v1", "jobs"] and parts[3] == "cancel":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(min(length, 16384))
            status, payload = store.cancel(parts[2], caller)
            self._send(status, payload)
            return
        self._send(404, {"error": {"code": "not_found", "category": "request", "message": "no such route", "retryable": False}})


def make_server(store, host, port):
    if host != "127.0.0.1":
        raise SystemExit("refusing to bind anything except 127.0.0.1")
    httpd = ThreadingHTTPServer((host, port), JobHandler)
    bound = httpd.socket.getsockname()
    if bound[0] != "127.0.0.1":
        httpd.server_close()
        raise SystemExit("socket is not loopback")
    httpd.store = store
    httpd.token = store.token()
    return httpd


def serve(store, runner, host, port):
    httpd = make_server(store, host, port)
    bound = httpd.socket.getsockname()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            if not process_one(store, runner):
                stop.wait(0.2)

    worker = threading.Thread(target=loop, name="cinecode-job-worker", daemon=True)
    worker.start()
    print(f"listening http://127.0.0.1:{bound[1]}  token file {store.root / 'auth.token'}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        stop.set()
        httpd.server_close()


def submit_file(store, path):
    body = json.loads(Path(path).read_text(encoding="utf-8"))
    result = validate(body)
    if isinstance(result[0], int):
        print(json.dumps(result[1], ensure_ascii=False, indent=2))
        return result[0]
    kind, norm, message = result
    upload_id = norm.get("upload_id") if isinstance(norm, dict) else None
    if upload_id and store.upload_for_owner(upload_id, "operator") is None:
        print(json.dumps({"error": {"code": "forbidden", "message": "upload is not available to this caller"}}, ensure_ascii=False))
        return 403
    status, payload = store.submit(norm, message if kind == "blocked" else "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status in (200, 202) else status


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="job store directory, outside the kit and outside ~/.cinecode")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve").add_argument("--port", type=int, default=8765)
    submit = sub.add_parser("submit")
    submit.add_argument("--file", required=True)
    sub.add_parser("run").add_argument("--once", action="store_true")
    sub.add_parser("resume")
    status = sub.add_parser("status")
    status.add_argument("job_id")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("job_id")
    caps = sub.add_parser("capabilities")
    bots = sub.add_parser("bots")
    bots.add_argument("action", choices=["add"])
    bots.add_argument("bot_id")
    args = parser.parse_args(argv)
    store = Store(args.root)
    if args.cmd == "bots":
        try:
            token = store.add_bot(args.bot_id)
        except (JobFailure, sqlite3.IntegrityError) as exc:
            print(json.dumps({"error": getattr(exc, "code", "duplicate_bot")}))
            return 1
        print(token)
        return 0
    if args.cmd == "capabilities":
        print(json.dumps({"capabilities": current_capabilities()}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "submit":
        return submit_file(store, args.file)
    if args.cmd == "status":
        row = store.get(args.job_id)
        if row is None:
            print(json.dumps({"error": {"code": "not_found", "message": "no such job"}}))
            return 1
        print(json.dumps(store.public(row), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "cancel":
        status_code, payload = store.cancel(args.job_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if status_code == 200 else 1
    if args.cmd == "resume":
        print(json.dumps({"requeued": store.resume_orphans()}, ensure_ascii=False))
        return 0
    runner = DispatchRunner()
    if args.cmd == "run":
        store.resume_orphans()
        while process_one(store, runner):
            if args.once:
                break
        return 0
    if args.cmd == "serve":
        store.resume_orphans()
        serve(store, runner, "127.0.0.1", args.port)
        return 0
    return 2


if __name__ == "__main__":
    if os.name == "nt" and not sys.flags.utf8_mode:   # Windows reads, writes and prints in a legacy code page
        sys.exit(subprocess.call([sys.executable] + sys.argv, env=dict(os.environ, PYTHONUTF8="1")))
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        getattr(_stream, "reconfigure", lambda **_k: None)(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
