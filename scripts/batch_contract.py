#!/usr/bin/env python3
"""File-backed batch contract for a later production run.

A unit test of this module is not a rendered batch, not an independent QC pass,
and not a daily rate. Nothing here calls a model, spends money, or marks a film passed.
Acceptance stays pending until a person records an independent check.
The handoff draft's thresholds are not a pass. Audio is not checked here.
"""
import hashlib
import json
import time
from pathlib import Path

REQUIRED = (
    "task_id", "idempotency_key", "script_version", "script_sha256",
    "source_sha256", "licence_scope", "platform_target", "capability",
    "backend_version", "threshold_version", "output_name", "handoff_to",
)
# Proposed in the handoff, and not enabled until an interface protocol exists.
TRANSIENT_AUTO_RETRIES = 0
RETRYABLE = {"transient"}
NO_RETRY = {"quality", "licence", "safety", "capability", "input"}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _body_hash(item):
    raw = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ContractError(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(detail)


class BatchStore:
    def __init__(self, path, max_auto_retries=TRANSIENT_AUTO_RETRIES):
        self.path = Path(path)
        self.max_auto_retries = max_auto_retries
        self.data = {
            "acceptance": "pending",
            "qualified_list": [],
            "daily_rate": None,
            "paid": False,
            "audio_checked": False,
            "unit_simulation": True,
            "tasks": {},
            "attempts": [],
        }
        if self.path.is_file():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            self._resume_running()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def _resume_running(self):
        for task in self.data["tasks"].values():
            if task["status"] == "running":
                task["status"] = "queued"
                task["resumed_at"] = _now()

    def submit(self, item):
        missing = [key for key in REQUIRED if not item.get(key)]
        if missing:
            raise ContractError("blocked", "missing " + ",".join(missing))
        if item.get("budget_paid") not in (0, "0", None):
            raise ContractError("blocked", "paid work is not accepted")
        if not item.get("licence_scope") or item["licence_scope"] in ("unknown", "unclear"):
            raise ContractError("blocked", "licence scope is not clear")
        key = item["idempotency_key"]
        digest = _body_hash({k: item[k] for k in REQUIRED})
        existing = self.data["tasks"].get(key)
        if existing:
            if existing["body_sha256"] != digest:
                raise ContractError("conflict", "idempotency key already names another body")
            return existing
        task = {
            "task_id": item["task_id"],
            "idempotency_key": key,
            "body_sha256": digest,
            "mode": item.get("mode") or "locked",
            "status": "queued",
            "acceptance": "pending",
            "attempts": 0,
            "auto_retries": 0,
            "output_sha256": None,
            "detail": "",
            "created_at": _now(),
        }
        self.data["tasks"][key] = task
        self.save()
        return task

    def run_next(self, worker):
        task = next((t for t in self.data["tasks"].values() if t["status"] == "queued"), None)
        if task is None:
            return None
        task["status"] = "running"
        task["attempts"] += 1
        started = _now()
        self.save()
        try:
            result = worker(task)
        except Exception as exc:
            result = {"kind": "transient", "detail": type(exc).__name__}
        self._apply(task, result or {}, started)
        self.save()
        return task

    def _apply(self, task, result, started):
        kind = result.get("kind") or "input"
        detail = result.get("detail") or ""
        attempt = {
            "attempt_id": f"{task['task_id']}-{task['attempts']}",
            "task_id": task["task_id"],
            "idempotency_key": task["idempotency_key"],
            "kind": kind,
            "detail": detail,
            "output_sha256": result.get("output_sha256"),
            "started_at": started,
            "ended_at": _now(),
            "paid": False,
        }
        self.data["attempts"].append(attempt)
        task["detail"] = detail
        task["output_sha256"] = result.get("output_sha256")
        if kind == "rendered":
            task["status"] = "pending"
            task["acceptance"] = "pending"
            return
        if kind in NO_RETRY:
            task["status"] = "blocked" if kind in ("licence", "safety", "capability", "input") else "failed"
            return
        if kind in RETRYABLE and task["auto_retries"] < self.max_auto_retries:
            task["auto_retries"] += 1
            task["status"] = "queued"
            return
        task["status"] = "failed"

    def manifest(self):
        counts = {}
        for task in self.data["tasks"].values():
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        return {
            "tasks": len(self.data["tasks"]),
            "counts": counts,
            "attempts": len(self.data["attempts"]),
            "acceptance": "pending",
            "qualified_list": [],
            "daily_rate": None,
            "audio_checked": False,
            "paid": False,
            "note": "Unit simulation. Not an independent pass and not a daily rate.",
        }
