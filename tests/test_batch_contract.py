"""The batch contract in memory and on disk. These tests render nothing."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import batch_contract as batch


def item(**over):
    body = {
        "task_id": "stationery-1",
        "idempotency_key": "locked-stationery-v1",
        "script_version": "locked-4-lines",
        "script_sha256": "abc",
        "source_sha256": "geometry",
        "licence_scope": "original geometry, no person footage",
        "platform_target": "unspecified vertical 18s",
        "capability": "locked motion template",
        "backend_version": "make.py draft, no model",
        "threshold_version": "existing hook and action checks, not lowered",
        "output_name": "stationery-draft.mp4",
        "handoff_to": "independent qc",
        "budget_paid": 0,
        "mode": "locked",
    }
    body.update(over)
    return body


class Contract(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = batch.BatchStore(Path(self.dir.name) / "batch.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_a_missing_field_or_unclear_licence_or_a_fee_is_blocked(self):
        with self.assertRaises(batch.ContractError) as missing:
            self.store.submit(item(script_sha256=""))
        self.assertEqual(missing.exception.code, "blocked")
        with self.assertRaises(batch.ContractError) as licence:
            self.store.submit(item(licence_scope="unknown"))
        self.assertIn("licence", licence.exception.detail)
        with self.assertRaises(batch.ContractError) as paid:
            self.store.submit(item(budget_paid=1))
        self.assertEqual(paid.exception.code, "blocked")

    def test_the_same_key_returns_the_same_task_and_a_new_body_conflicts(self):
        first = self.store.submit(item())
        again = self.store.submit(item())
        self.assertEqual(first["task_id"], again["task_id"])
        self.assertEqual(len(self.store.data["tasks"]), 1)
        with self.assertRaises(batch.ContractError) as conflict:
            self.store.submit(item(script_sha256="different"))
        self.assertEqual(conflict.exception.code, "conflict")

    def test_a_render_stays_pending_and_a_quality_or_licence_failure_does_not_retry(self):
        self.store.submit(item())
        self.store.submit(item(task_id="bad-picture", idempotency_key="quality"))
        self.store.submit(item(task_id="no-right", idempotency_key="licence"))
        seen = []

        def worker(task):
            seen.append(task["idempotency_key"])
            if task["idempotency_key"] == "quality":
                return {"kind": "quality", "detail": "hook mean below the existing rule"}
            if task["idempotency_key"] == "licence":
                return {"kind": "licence", "detail": "release not verified"}
            return {"kind": "rendered", "detail": "picture file written", "output_sha256": "deadbeef"}

        for _ in range(5):
            if self.store.run_next(worker) is None:
                break
        tasks = self.store.data["tasks"]
        self.assertEqual(tasks["locked-stationery-v1"]["status"], "pending")
        self.assertEqual(tasks["locked-stationery-v1"]["acceptance"], "pending")
        self.assertEqual(tasks["quality"]["status"], "failed")
        self.assertEqual(tasks["quality"]["attempts"], 1)
        self.assertEqual(tasks["licence"]["status"], "blocked")
        self.assertEqual(tasks["licence"]["attempts"], 1)
        self.assertEqual(seen.count("quality"), 1)
        manifest = self.store.manifest()
        self.assertEqual(manifest["qualified_list"], [])
        self.assertIsNone(manifest["daily_rate"])
        self.assertFalse(manifest["audio_checked"])

    def test_transient_retries_only_when_the_limit_is_turned_on(self):
        self.store.submit(item(task_id="net", idempotency_key="net"))
        self.store.run_next(lambda task: {"kind": "transient", "detail": "connection reset"})
        self.assertEqual(self.store.data["tasks"]["net"]["status"], "failed")
        self.assertEqual(self.store.data["tasks"]["net"]["attempts"], 1)

        limited = batch.BatchStore(Path(self.dir.name) / "retry.json", max_auto_retries=2)
        limited.submit(item(task_id="net2", idempotency_key="net2"))
        for _ in range(5):
            if limited.run_next(lambda task: {"kind": "transient", "detail": "timeout"}) is None:
                break
        task = limited.data["tasks"]["net2"]
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["attempts"], 3)
        self.assertEqual(task["auto_retries"], 2)

    def test_a_running_task_is_queued_again_without_a_second_id(self):
        self.store.submit(item())
        self.store.data["tasks"]["locked-stationery-v1"]["status"] = "running"
        self.store.save()
        resumed = batch.BatchStore(self.store.path)
        task = resumed.data["tasks"]["locked-stationery-v1"]
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["task_id"], "stationery-1")
        self.assertEqual(len(resumed.data["tasks"]), 1)


if __name__ == "__main__":
    unittest.main()
