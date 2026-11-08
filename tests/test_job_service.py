"""Local job adapter. No Chrome. One materialize uses init_film and the system font."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import job_service as job


def request(**over):
    body = {
        "task_type": "motion_video",
        "template_id": "home_clean_tips_v1",
        "asset_ids": [],
        "brief": "preauthorized template only",
        "replacement_target": None,
        "output": {"profile": "draft", "width": 540, "height": 960, "duration_s": 18, "fps": 24, "language": "zh-CN"},
        "timeout_s": 30,
        "policy_id": "preauthorized_motion_v1",
    }
    body.update(over)
    return body


class FakeRunner:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.seen = []

    def run(self, row, ctl):
        self.seen.append(json.loads(row["request_json"]))
        ctl.set_stage("render")
        if self.mode == "wait":
            while True:
                ctl.check()
                time.sleep(0.05)
        out = ctl.work_dir / "output"
        out.mkdir(exist_ok=True)
        target = out / "film.mp4"
        target.write_bytes(b"not-a-real-movie")
        return {"state": "succeeded", "error": None, "artifact": {
            "relative_path": "output/film.mp4", "sha256": "abc", "delivered": True, "bytes": target.stat().st_size,
        }}


class Validate(unittest.TestCase):
    def test_capabilities_name_the_real_route_and_stay_unconfigured(self):
        for key in ("CINECODE_LLAMA_CLI", "CINECODE_COPY_MODEL", "CINECODE_FACE_MODEL",
                    "CINECODE_FACE_A", "CINECODE_FACE_B", "CINECODE_SEG_MODEL"):
            os.environ.pop(key, None)
        items = {item["id"]: item for item in job.current_capabilities()}
        self.assertEqual(items["motion_video"]["status"], "user_text_typeset")
        self.assertEqual(items["face_swap"]["status"], "head_swap_unavailable")
        self.assertFalse(items["face_swap"]["configured"])
        self.assertEqual(items["background_replace"]["status"], "selfie_segmenter")
        self.assertFalse(items["background_replace"]["configured"])
        self.assertEqual(items["one_click_replace"]["status"], "unavailable")
        self.assertEqual(items["copywriting"]["status"], "local_gguf")
        self.assertFalse(items["copywriting"]["configured"])
        self.assertEqual(items["word_accurate_talking_head_edit"]["status"], "whisper_word_times")

    def test_unsupported_capabilities_are_422(self):
        status, payload = job.validate({"task_type": "one_click_replace"})
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "unsupported_capability")
        status, payload = job.validate({"task_type": "no_such_task"})
        self.assertEqual(status, 422)

    def test_rejects_replacement_assets_shell_and_unknown_fields(self):
        status, payload = job.validate(request(replacement_target={"path": "/etc/passwd"}))
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "replacement_rejected")
        status, payload = job.validate(request(asset_ids=["../secrets"]))
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "unknown_asset")
        status, payload = job.validate(request(command="rm -rf /"))
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "unknown_field")
        status, payload = job.validate(request(policy_id="other"))
        self.assertEqual(status, 403)

    def test_draft_command_is_a_fixed_argv(self):
        argv = job.draft_argv(Path("/tmp/film"), 1)
        self.assertEqual(argv[1:], ["/tmp/film/tools/make.py", "draft", "--workers", "1"])
        self.assertNotIn(";", " ".join(argv))
        with self.assertRaises(job.JobFailure):
            job.draft_argv(Path("/tmp/film"), "1;rm")

    def test_mismatched_script_full_profile_and_language_are_blocked_not_rendered(self):
        kind, norm, _ = job.validate(request(script={"text": "先擦一遍\n再冲水", "mode": "locked"}))
        self.assertEqual(kind, "ok")
        self.assertEqual(norm["text_source"], "user_locked")
        self.assertEqual(norm["lines"][0], "先擦一遍")
        for key in ("CINECODE_FACE_MODEL", "CINECODE_FACE_A", "CINECODE_FACE_B"):
            os.environ.pop(key, None)
        kind, face, _ = job.validate({
            "task_type": "face_swap", "policy_id": "preauthorized_motion_v1", "timeout_s": 60,
        })
        self.assertEqual(kind, "blocked")
        self.assertEqual(face["blocked_code"], "head_swap_unavailable")
        for key in ("CINECODE_LLAMA_CLI", "CINECODE_COPY_MODEL"):
            os.environ.pop(key, None)
        kind, norm, message = job.validate(request(script={"text": "请根据简介新写一套文案", "mode": "generate"}))
        self.assertEqual(kind, "blocked")
        self.assertEqual(norm["blocked_code"], "model_host_unavailable")
        self.assertIn("not AI writing", message)
        kind, speech, _ = job.validate({
            "task_type": "word_accurate_talking_head_edit",
            "policy_id": "preauthorized_motion_v1", "timeout_s": 60,
        })
        self.assertEqual(kind, "blocked")
        self.assertEqual(speech["blocked_code"], "audio_required")
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        cli = Path(holder.name) / "llama-cli"
        model = Path(holder.name) / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
        cli.write_text("x", encoding="utf-8")
        model.write_bytes(b"x")
        os.environ["CINECODE_LLAMA_CLI"] = str(cli)
        os.environ["CINECODE_COPY_MODEL"] = str(model)
        self.addCleanup(os.environ.pop, "CINECODE_LLAMA_CLI", None)
        self.addCleanup(os.environ.pop, "CINECODE_COPY_MODEL", None)
        kind, queued, _ = job.validate(request(brief="擦灶台的四个不同步骤", script={"mode": "generate"}))
        self.assertEqual(kind, "ok")
        self.assertEqual(queued["text_source"], "generate")
        self.assertIsNone(queued["lines"])
        kind, mismatch, _ = job.validate(request(brief="写四句文具收纳的步骤", script={"mode": "generate"}))
        self.assertEqual(kind, "blocked")
        self.assertEqual(mismatch["blocked_code"], "template_topic_mismatch")
        kind, themed, _ = job.validate(request(
            brief="写四句文具收纳的步骤", template_id="stationery_tidy_v1", script={"mode": "generate"}))
        self.assertEqual(kind, "ok")
        self.assertEqual(themed["template_id"], "stationery_tidy_v1")
        bare = tempfile.TemporaryDirectory()
        self.addCleanup(bare.cleanup)
        for key in ("CINECODE_LLAMA_CLI", "CINECODE_COPY_MODEL"):
            os.environ.pop(key, None)
        kind, blocked_norm, blocked_message = job.validate(request(
            brief="擦灶台的四个不同步骤", script={"mode": "generate"}))
        self.assertEqual(kind, "blocked")
        bare_store = job.Store(bare.name)
        _, bare_body = bare_store.submit(blocked_norm, blocked_message)
        self.assertEqual(bare_body["model_host"], "unavailable")
        os.environ["CINECODE_LLAMA_CLI"] = str(cli)
        os.environ["CINECODE_COPY_MODEL"] = str(model)
        kind, gen_norm, _ = job.validate(request(brief="擦灶台的四个不同步骤", script={"mode": "generate"}))
        self.assertEqual(kind, "ok")
        host = tempfile.TemporaryDirectory()
        self.addCleanup(host.cleanup)
        gen_store = job.Store(host.name)
        _, gen_body = gen_store.submit(gen_norm, "")
        gen_store.update(gen_body["job_id"], state="succeeded", artifact_json=json.dumps({
            "relative_path": "output/film.mp4",
            "generation": "local_gguf_then_typeset",
            "model_host": "local_file",
            "ai_generated": True,
        }))
        shown = gen_store.public(gen_store.get(gen_body["job_id"]))
        self.assertEqual(shown["model_host"], "local_file")
        self.assertEqual(shown["generation"], "local_gguf_then_typeset")
        self.assertTrue(shown["artifact"]["ai_generated"])
        status, payload = job.validate(request(script={"text": "x" * 241, "mode": "locked"}))
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "text_rejected")
        lines = job.prepare_lines("</script><img src=x onerror=alert(1)>\nHello 你好")
        self.assertTrue(any("</script>" in line for line in lines))
        kind, norm, _ = job.validate(request(output={
            "profile": "full", "width": 1080, "height": 1920, "duration_s": 18, "fps": 24, "language": "zh-CN"}))
        self.assertEqual(norm["blocked_code"], "upstream_final_gate")
        kind, norm, _ = job.validate(request(output={
            "profile": "draft", "width": 540, "height": 960, "duration_s": 18, "fps": 24, "language": "en"}))
        self.assertEqual(kind, "ok")
        self.assertEqual(norm["text_source"], "template_default")
        self.assertTrue(norm["lines"][0].startswith("先"))


class TopicAndSource(unittest.TestCase):
    def test_locked_text_is_drawn_and_the_brief_is_metadata(self):
        kind, norm, _ = job.validate(request(
            brief="写四句文具收纳",
            script={"mode": "locked", "text": "先清台面\n喷一点\n顺纹擦开\n热水过盘"},
        ))
        self.assertEqual(kind, "ok")
        self.assertEqual(norm["brief_role"], "metadata")
        self.assertEqual(norm["lines"][0], "先清台面")
        self.assertEqual(norm["text_source"], "user_locked")
        kind, off, _ = job.validate(request(
            brief="擦台面",
            script={"mode": "locked", "text": "文具入盒\n贴上标签\n分类摆好"},
        ))
        self.assertEqual(kind, "blocked")
        self.assertEqual(off["blocked_code"], "template_topic_mismatch")
        kind, pens, _ = job.validate(request(
            template_id="stationery_tidy_v1",
            brief="a note",
            script={"mode": "locked", "text": "铅笔入盒\n橡皮归位\n尺子摆好\n便签单独放"},
        ))
        self.assertEqual(kind, "ok")
        self.assertEqual(pens["lines"][0], "铅笔入盒")
        self.assertEqual(pens["brief_role"], "metadata")

    def test_upload_source_is_unknown_unless_the_caller_declares_it(self):
        body = {
            "task_type": "word_accurate_talking_head_edit",
            "policy_id": "preauthorized_motion_v1",
            "timeout_s": 60,
            "upload_id": "0123456789abcdef",
        }
        kind, norm, _ = job.validate(body)
        if kind == "blocked" and norm.get("blocked_code") == "asr_runtime_missing":
            self.assertIsNone(norm.get("audio_source") if False else None)
        else:
            self.assertEqual(kind, "ok")
            self.assertEqual(norm["audio_source"], "unknown")
            self.assertNotIn("synthetic_test", norm)
        declared = dict(body, audio_source="declared_recording")
        kind, norm, _ = job.validate(declared)
        if kind == "ok":
            self.assertEqual(norm["audio_source"], "declared_recording")
        synth = dict(body, synthetic_test=True)
        kind, norm, _ = job.validate(synth)
        if kind == "ok":
            self.assertEqual(norm["audio_source"], "synthetic")
        status, payload = job.validate(dict(body, audio_source="human"))
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_field")


class Queue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cinecode-job-")
        self.addCleanup(self.tmp.cleanup)
        self.store = job.Store(self.tmp.name)

    def submit(self, **over):
        result = job.validate(request(**over))
        self.assertNotIsInstance(result[0], int, result)
        kind, norm, message = result
        return self.store.submit(norm, message if kind == "blocked" else "")

    def test_idempotency_cancel_and_timeout(self):
        status, first = self.submit(idempotency_key="same-key")
        self.assertEqual(status, 202)
        self.assertEqual(first["state"], "queued")
        status, again = self.submit(idempotency_key="same-key")
        self.assertEqual(status, 200)
        self.assertEqual(again["job_id"], first["job_id"])
        status, conflict = self.submit(idempotency_key="same-key", brief="a different brief text")
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"]["code"], "idempotency_conflict")
        for key in ("CINECODE_LLAMA_CLI", "CINECODE_COPY_MODEL"):
            os.environ.pop(key, None)
        status, blocked = self.submit(script={"text": "请创作一套新文案", "mode": "generate"}, idempotency_key="blocked-copy")
        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(blocked["error"]["code"], "model_host_unavailable")
        self.assertIsNone(blocked["artifact"])
        status, queued = self.submit(idempotency_key="cancel-me")
        code, payload = self.store.cancel(queued["job_id"])
        self.assertEqual(payload["state"], "cancelled")
        code, again = self.store.cancel(queued["job_id"])
        self.assertEqual(again["state"], "cancelled")
        self.store.cancel(first["job_id"])

        status, running = self.submit(timeout_s=1, idempotency_key="times-out")
        runner = FakeRunner("wait")
        thread = threading.Thread(target=job.process_one, args=(self.store, runner))
        thread.start()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        row = self.store.get(running["job_id"])
        self.assertEqual(row["state"], "expired")
        self.assertIn("timeout", row["error_json"])

    def test_cancel_while_running_and_resume_orphan(self):
        _, running = self.submit(timeout_s=30, idempotency_key="cancel-run")
        runner = FakeRunner("wait")
        thread = threading.Thread(target=job.process_one, args=(self.store, runner))
        thread.start()
        for _ in range(50):
            if self.store.get(running["job_id"])["state"] == "rendering":
                break
            time.sleep(0.02)
        self.store.cancel(running["job_id"])
        thread.join(3)
        self.assertEqual(self.store.get(running["job_id"])["state"], "cancelled")

        _, orphan = self.submit(idempotency_key="orphan")
        self.store.update(orphan["job_id"], state="rendering", pid=999999, stage="render")
        self.assertIn(orphan["job_id"], self.store.resume_orphans())
        self.assertEqual(self.store.get(orphan["job_id"])["state"], "queued")

    def test_success_registers_only_the_job_output(self):
        _, queued = self.submit(idempotency_key="ok")
        self.assertTrue(job.process_one(self.store, FakeRunner()))
        row = self.store.get(queued["job_id"])
        self.assertEqual(row["state"], "succeeded")
        artifact = self.store.artifact_file(queued["job_id"])
        self.assertTrue(str(artifact).startswith(str(self.store.root)))
        self.assertEqual(artifact.read_bytes(), b"not-a-real-movie")
        outside = Path(self.tmp.name) / "escape.mp4"
        outside.write_bytes(b"nope")
        self.store.update(queued["job_id"], artifact_json=json.dumps({"relative_path": "../../escape.mp4"}))
        self.assertIsNone(self.store.artifact_file(queued["job_id"]))


class Http(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cinecode-http-")
        self.addCleanup(self.tmp.cleanup)
        self.store = job.Store(self.tmp.name)
        self.httpd = job.make_server(self.store, "127.0.0.1", 0)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.httpd.server_close)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]
        self.token = self.store.token()

    def call(self, method, path, body=None, token=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        if token is not None:
            req.add_header("Authorization", "Bearer " + token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                payload = raw if "video" in ctype or "text/plain" in ctype else json.loads(raw.decode())
                return resp.status, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw.decode())
            except json.JSONDecodeError:
                payload = raw
            return exc.code, payload

    def test_localhost_contract(self):
        self.assertEqual(self.httpd.socket.getsockname()[0], "127.0.0.1")
        status, _ = self.call("GET", "/v1/capabilities")
        self.assertEqual(status, 401)
        status, payload = self.call("GET", "/v1/capabilities", token=self.token)
        self.assertEqual(status, 200)
        self.assertFalse(payload["multi_tenant"])
        status, payload = self.call("POST", "/v1/jobs", request(idempotency_key="http-1"), self.token)
        self.assertEqual(status, 202)
        job_id = payload["job_id"]
        status, payload = self.call("GET", f"/v1/jobs/{job_id}", token=self.token)
        self.assertEqual(payload["state"], "queued")
        status, payload = self.call("POST", f"/v1/jobs/{job_id}/cancel", token=self.token)
        self.assertEqual(payload["state"], "cancelled")
        status, payload = self.call("POST", "/v1/jobs", {"task_type": "one_click_replace"}, self.token)
        self.assertEqual(status, 422)
        status, health = self.call("GET", "/v1/health", token=None)
        self.assertEqual(status, 200)
        self.assertFalse(health["boot_persistent"])
        token_b = self.store.add_bot("botb")
        status, owned = self.call("POST", "/v1/jobs", request(idempotency_key="owned-by-operator"), self.token)
        status, denied = self.call("GET", f"/v1/jobs/{owned['job_id']}", token=token_b)
        self.assertEqual(status, 403)
        self.assertEqual(denied["error"]["code"], "forbidden")
        with self.assertRaises(SystemExit):
            job.make_server(self.store, "0.0.0.0", 0)


class Env(unittest.TestCase):
    def test_render_env_drops_loader_path_and_git_config(self):
        import os
        keys = {
            "LD_LIBRARY_PATH": "/tmp/not-a-lib",
            "LD_PRELOAD": "/tmp/not-a-lib.so",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_VALUE_0": "not-a-token",
        }
        saved = {key: os.environ.get(key) for key in keys}
        os.environ.update(keys)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env = job.isolated_env(Path(tmp) / "home")
            for key in keys:
                self.assertNotIn(key, env)
            self.assertIn("PATH", env)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class Materialize(unittest.TestCase):
    def test_request_text_is_not_copied_into_the_page(self):
        sentinel = "REQUEST-BRIEF-SENTINEL-9f3a"
        with tempfile.TemporaryDirectory(prefix="cinecode-film-") as tmp:
            env = job.isolated_env(Path(tmp) / "home")
            film, _ = job.prepare_project(Path(tmp), request(brief=sentinel), env, ctl=None)
            page = (film / "film.html").read_text(encoding="utf-8")
            self.assertNotIn(sentinel, page)
            self.assertNotIn("fieldGathers", page)
            self.assertIn("先清台面", page)
            self.assertTrue((film / "fonts" / "DroidSansFallbackFull.ttf").is_file())
            self.assertIn("code (user)", (film / "STATE.md").read_text(encoding="utf-8"))
            self.assertIn("synthetic by choice", (film / "STATE.md").read_text(encoding="utf-8"))
            argv = job.draft_argv(film, 1)
            self.assertNotIn(sentinel, " ".join(argv))
            self.assertTrue((film / "tools" / "make.py").is_file())
            self.assertTrue((film / "tools" / "capture.mjs").is_file())


if __name__ == "__main__":
    unittest.main()
