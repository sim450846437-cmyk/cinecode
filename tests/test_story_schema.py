"""Structure and import protocol. No model process."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import shot_protocol
import story_schema


def story():
    return {
        "plot": "周宁在夜班车站遇见阿禾。",
        "characters": [
            {"id": "周宁", "name": "周宁", "description": "三十岁短发，灰色外套。"},
            {"id": "阿禾", "name": "阿禾", "description": "二十五岁长发，深蓝围巾。"},
        ],
        "scenes": [{"id": "夜班车站", "description": "空荡站台，一盏黄灯。"}],
        "shots": [
            {
                "index": i, "scene_id": "夜班车站", "character_ids": ["周宁", "阿禾"],
                "scale": "中景", "action": "动作" + str(i), "dialogue": "周宁说一句。",
                "start_s": (i - 1) * 4,
                "resources": {"image": "not_generated", "video": "not_generated", "audio": "not_generated"},
            }
            for i in range(1, 5)
        ],
    }


class Schema(unittest.TestCase):
    def test_a_two_line_brief_does_not_demand_four_shots(self):
        brief = "夜班车站，虚构成年周宁与阿禾，末班车还没走/谢谢我赶上了"
        count, basis = story_schema.min_shots_for(brief)
        self.assertEqual((count, basis), (1, "brief_has_no_shot_count"))
        board = story()
        board["shots"] = board["shots"][:2]
        board["shots"][1]["start_s"] = 4
        self.assertEqual(story_schema.validate_story(board, min_shots=count), [])
        self.assertIn("shots_need_4", story_schema.validate_story(board, min_shots=4))
        joined = story()
        joined["shots"] = joined["shots"][:2]
        joined["shots"][1]["start_s"] = 4
        for shot in joined["shots"]:
            shot["character_ids"] = "周宁,阿禾"
        self.assertIn("character_refs_missing", story_schema.validate_story(joined, min_shots=1))
        notes = story_schema.normalize_story(joined)
        self.assertEqual(notes, ["split_character_ids", "split_character_ids"])
        self.assertEqual(story_schema.validate_story(joined, min_shots=1), [])
        named, why = story_schema.min_shots_for("请写四镜。")
        self.assertEqual((named, why), (4, "brief_named_count"))

    def test_a_complete_board_passes_and_a_backwards_clock_does_not(self):
        self.assertEqual(story_schema.validate_story(story()), [])
        broken = story()
        broken["shots"][2]["start_s"] = 0
        broken["shots"][2]["character_ids"] = ["路人"]
        errors = story_schema.validate_story(broken)
        self.assertIn("timeline_backwards", errors)
        self.assertIn("character_ref:路人", errors)

    def test_import_refuses_not_generated_and_writes_no_film(self):
        board = story()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            out = Path(tmp) / "out.mp4"
            path.write_text(json.dumps(board), encoding="utf-8")
            report = shot_protocol.assemble(path, out)
            self.assertEqual(report["error"], "media_not_imported")
            self.assertFalse(out.exists())
            self.assertEqual(len(report["missing"]), 4)
            wrapped = Path(tmp) / "wrapped.json"
            wrapped.write_text(json.dumps({"story": board, "qualified": False}), encoding="utf-8")
            wrapped_out = Path(tmp) / "wrapped.mp4"
            wrapped_report = shot_protocol.assemble(wrapped, wrapped_out)
            self.assertEqual(wrapped_report["error"], "media_not_imported")
            self.assertFalse(wrapped_out.exists())
            dup = dict(board)
            dup["shots"] = [dict(board["shots"][0]), dict(board["shots"][0])]
            dup["shots"][0]["resources"] = {"image": "not_generated", "video": str(path), "audio": "not_generated"}
            dup["shots"][1]["resources"] = {"image": "not_generated", "video": str(path), "audio": "not_generated"}
            dup_path = Path(tmp) / "dup.json"
            dup_path.write_text(json.dumps(dup), encoding="utf-8")
            dup_out = Path(tmp) / "dup.mp4"
            dup_report = shot_protocol.assemble(dup_path, dup_out)
            self.assertEqual(dup_report["error"], "duplicate_source")
            self.assertFalse(dup_out.exists())


if __name__ == "__main__":
    unittest.main()
