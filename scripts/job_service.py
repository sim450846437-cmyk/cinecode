#!/usr/bin/env python3
"""Localhost queue for one preauthorized cinecode motion template.

The adapter submits a job, runs that job, and returns status plus an MP4.
It binds to 127.0.0.1 only. It does not add a model, a face swap, a background
replacement, a talking-head editor, or a copywriting API. Arbitrary copy is
stored as data and, when it is not the template lock, the job is blocked
without rendering.

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
import json
import os
import re
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
TEMPLATES = KIT / "service" / "templates"
FILM_MARK = "// ============================== FILM =============================="
HELPERS_MARK = "// ============================== HELPERS (picture) =============================="
JOB_ID_RE = re.compile(r"^job_[0-9a-f]{16}$")
IDEM_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*\S+")
ENV_DROP = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AWS_", "GITHUB", "GH_")

ALLOWED_TEMPLATES = {"home_clean_tips_v1"}
UNSUPPORTED = {
    "face_swap": "No face-replacement model or tool is in this kit. A drawn character is not a face swap.",
    "background_replace": "No background-replacement model. Drawing a background in code does not replace a plate.",
    "word_accurate_talking_head_edit": (
        "footage_cut.py can trim from a word transcript the caller already measured. "
        "Whisper is not bundled, and cuts that change meaning stay an approval. This adapter does not run that path."
    ),
    "copywriting": "Script writing in the skill is an interactive agent step. This process has no model host.",
    "one_click_replace": "No one-click replace tool. replacement_target is rejected on motion_video.",
}
CAPABILITIES = [
    {
        "id": "motion_video",
        "status": "preauthorized_template_only",
        "template_id": "home_clean_tips_v1",
        "detail": (
            "Renders the checked-in Quick-mode draft through tools/make.py. "
            "This is not arbitrary-copy generation. profile full is blocked: "
            "make.py final waits for an independent viewer and a user OK this adapter will not forge."
        ),
    },
    {"id": "face_swap", "status": "unavailable", "detail": UNSUPPORTED["face_swap"]},
    {"id": "background_replace", "status": "unavailable", "detail": UNSUPPORTED["background_replace"]},
    {"id": "word_accurate_talking_head_edit", "status": "needs_external_backend", "detail": UNSUPPORTED["word_accurate_talking_head_edit"]},
    {"id": "copywriting", "status": "unavailable", "detail": UNSUPPORTED["copywriting"]},
    {"id": "one_click_replace", "status": "unavailable", "detail": UNSUPPORTED["one_click_replace"]},
]


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


def validate(body):
    if not isinstance(body, dict):
        return error_body("invalid_json", "the body must be a JSON object", "request")
    unknown = sorted(set(body) - {
        "task_type", "template_id", "asset_ids", "brief", "script", "replacement_target",
        "output", "timeout_s", "policy_id", "idempotency_key", "budget",
    })
    if unknown:
        return error_body("unknown_field", "unknown fields: " + ", ".join(unknown), "request")
    task = body.get("task_type")
    if not isinstance(task, str):
        return error_body("invalid_field", "task_type must be a string", "request")
    if task in UNSUPPORTED:
        return error_body("unsupported_capability", UNSUPPORTED[task], "capability", http=422)
    if task != "motion_video":
        return error_body("unsupported_capability", "task_type is not supported", "capability", http=422)
    template_id = body.get("template_id")
    if template_id not in ALLOWED_TEMPLATES:
        return error_body("unknown_template", "motion_video requires template_id home_clean_tips_v1", "request")
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
        norm = _normalized(body, brief, timeout_s, idem, output, blocked="upstream_final_gate")
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
    if output["language"] != manifest["language"]:
        norm = _normalized(body, brief, timeout_s, idem, output, blocked="language_mismatch")
        return "blocked", norm, "This template's on-screen words are fixed zh-CN. Translating them would be a model step this adapter does not have."
    script = body.get("script", None)
    if script is not None:
        if not isinstance(script, dict) or set(script) != {"text", "mode"}:
            return error_body("invalid_field", "script must be {text, mode} or omitted", "request")
        if script.get("mode") != "locked" or not isinstance(script.get("text"), str):
            return error_body("invalid_field", "script.mode must be locked and script.text must be a string", "request")
        if script["text"].replace("\r\n", "\n").strip() != manifest["locked_script"]:
            norm = _normalized(body, brief, timeout_s, idem, output, blocked="script_not_template_lock")
            return "blocked", norm, (
                "The script is not this template's locked lines. There is no model host to rewrite the picture, "
                "and the adapter will not treat template playback as automatic copy generation. Nothing is rendered."
            )
    norm = _normalized(body, brief, timeout_s, idem, output, blocked=None)
    return "ok", norm, ""


def _normalized(body, brief, timeout_s, idem, output, blocked):
    script = body.get("script", None)
    if isinstance(script, dict):
        script = {"mode": script.get("mode"), "text": script.get("text")}
    return {
        "task_type": "motion_video",
        "template_id": body.get("template_id"),
        "asset_ids": [],
        "brief": brief,
        "script": script,
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
        self.conn.commit()

    def token(self):
        path = self.root / "auth.token"
        if not path.exists():
            path.write_text(os.urandom(24).hex() + "\n", encoding="utf-8")
            os.chmod(path, 0o600)
        return path.read_text(encoding="utf-8").strip()

    def submit(self, norm, blocked_message=""):
        key = norm.get("idempotency_key")
        body_hash = digest(canonical({k: v for k, v in norm.items() if k != "blocked_code"} | {"blocked_code": norm.get("blocked_code")}))
        stamp = now()
        with self.lock:
            if key:
                row = self.conn.execute("SELECT * FROM jobs WHERE idempotency_key = ?", (key,)).fetchone()
                if row is not None:
                    if row["request_hash"] != body_hash:
                        return 409, {"error": {"code": "idempotency_conflict", "category": "request",
                                               "message": "this idempotency_key was already used for a different request",
                                               "retryable": False}}
                    return 200, self.public(row)
            job_id = "job_" + os.urandom(8).hex()
            work = self.root / "work" / job_id
            work.mkdir(parents=True, exist_ok=False)
            state = "blocked" if norm.get("blocked_code") else "queued"
            err = None
            if state == "blocked":
                err = json.dumps({"code": norm["blocked_code"], "category": "gate",
                                  "message": blocked_message, "retryable": False}, ensure_ascii=False)
            self.conn.execute(
                """INSERT INTO jobs (id, idempotency_key, request_hash, request_json, state, stage,
                   error_json, created_at, updated_at, finished_at, timeout_s, log_rel)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, key, body_hash, canonical(norm), state, "blocked" if state == "blocked" else "queued",
                 err, stamp, stamp, stamp if state == "blocked" else None, norm["timeout_s"], f"work/{job_id}/job.log"),
            )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return 202, self.public(row)

    def get(self, job_id):
        if not JOB_ID_RE.fullmatch(job_id or ""):
            return None
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
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
        return {
            "job_id": row["id"],
            "state": row["state"],
            "task_type": req.get("task_type"),
            "template_id": req.get("template_id"),
            "generation": "deterministic_template" if req.get("template_id") in ALLOWED_TEMPLATES else None,
            "model_host": "unavailable",
            "progress": None if row["state"] in ("queued", "blocked") else {"stage": stage, "percent": None},
            "artifact": artifact,
            "error": err,
            "cancel_requested": bool(row["cancel_requested"]),
            "timeout_s": row["timeout_s"],
            "peak_rss_kb": row["peak_rss_kb"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "log": {"reference": f"/v1/jobs/{row['id']}/logs", "redacted": True},
        }

    def cancel(self, job_id):
        row = self.get(job_id)
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
    film_html.write_text(text[:start + len(FILM_MARK)] + "\n" + section.strip() + "\n\n" + text[end:], encoding="utf-8")
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
        if len(brief) >= 12 and brief in page:
            raise JobFailure("isolation", "request text leaked into film.html", "security", False)
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

    def run(self, row, ctl):
        request = json.loads(row["request_json"])
        env = isolated_env(ctl.work_dir / "cinecode-home")
        film, manifest = prepare_project(ctl.work_dir, request, env, ctl)
        ctl.check()
        delivered = sorted(film.glob("*-draft.mp4"))
        if not delivered:
            code = ctl.run(draft_argv(film, manifest.get("workers") or 1), film, env, "render")
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
            "generation": "deterministic_template",
            "model_host": "unavailable",
            "arbitrary_copy": False,
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


class JobHandler(BaseHTTPRequestHandler):
    server_version = "cinecode-job/0"

    def log_message(self, fmt, *args):
        return

    def _authorized(self):
        header = self.headers.get("Authorization", "")
        token = getattr(self.server, "token", "")
        ok = header.startswith("Bearer ") and hmac.compare_digest(header[7:].strip(), token)
        if not ok:
            self._send(401, {"error": {"code": "unauthorized", "category": "auth",
                                       "message": "Bearer token required", "retryable": False}})
        return ok

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
        if not self._authorized():
            return
        path = self.path.split("?", 1)[0]
        store = self.server.store
        if path == "/v1/capabilities":
            self._send(200, {"capabilities": CAPABILITIES, "bind": "127.0.0.1", "multi_tenant": False})
            return
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["v1", "jobs"] and parts[3] == "logs":
            text = store.log_text(parts[2])
            if text is None:
                self._send(404, {"error": {"code": "not_found", "category": "request", "message": "no such job", "retryable": False}})
                return
            self._send(200, body=text.encode("utf-8"), content_type="text/plain; charset=utf-8")
            return
        if len(parts) == 4 and parts[:2] == ["v1", "jobs"] and parts[3] == "artifact":
            target = store.artifact_file(parts[2])
            if target is None:
                self._send(404, {"error": {"code": "not_ready", "category": "request",
                                           "message": "no registered artifact", "retryable": True}})
                return
            data = target.read_bytes()
            self._send(200, body=data, content_type="video/mp4")
            return
        if len(parts) == 3 and parts[:2] == ["v1", "jobs"]:
            row = store.get(parts[2])
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
        if not self._authorized():
            return
        path = self.path.split("?", 1)[0]
        store = self.server.store
        parts = path.strip("/").split("/")
        if path == "/v1/jobs":
            body = self._read_json()
            if body is None:
                return
            result = validate(body)
            if isinstance(result[0], int):
                self._send(result[0], result[1])
                return
            kind, norm, message = result
            if kind == "blocked":
                status, payload = store.submit(norm, message)
            else:
                status, payload = store.submit(norm, "")
            self._send(status, payload)
            return
        if len(parts) == 4 and parts[:2] == ["v1", "jobs"] and parts[3] == "cancel":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(min(length, 16384))
            status, payload = store.cancel(parts[2])
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
    args = parser.parse_args(argv)
    store = Store(args.root)
    if args.cmd == "capabilities":
        print(json.dumps({"capabilities": CAPABILITIES}, ensure_ascii=False, indent=2))
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
    runner = CinecodeDraftRunner()
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
