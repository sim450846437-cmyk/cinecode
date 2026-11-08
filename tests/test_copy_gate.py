"""Screens for the local copy model. No llama process and no film."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asr_edit
import copy_local


class Gate(unittest.TestCase):
    def test_pour_back_is_rejected_and_a_negated_line_is_not(self):
        self.assertIn("pour_back", copy_local.hazard_codes(["清洁剂用后记得倒回容器里，避免浪费。"]))
        self.assertEqual(copy_local.hazard_codes(["不要把清洁液倒回原瓶。"]), [])
        self.assertIn("mix_agents", copy_local.hazard_codes(["把漂白水和洁厕灵混用。"]))
        self.assertEqual(copy_local.hazard_codes(["把同类文具混合摆放。", "铅笔进盒。", "橡皮进袋。", "尺子归位。"]), [])

    def test_repeated_lines_are_rejected(self):
        lines = ["把铅笔放进笔筒。", "把橡皮放进笔筒。", "把尺子放进笔筒。", "把本子放进笔筒。"]
        self.assertIn("repeated_phrase", copy_local.repetition_codes(lines))
        self.assertIn("duplicate_line", copy_local.repetition_codes(["收进盒子。"] * 4))
        stutter = ["选择合适的容器，如文具盒、文具盒、文具盒等。", "把橡皮单独放好。", "把尺子竖着放。", "把便签放在最上层。"]
        self.assertIn("repeated_phrase", copy_local.repetition_codes(stutter))

    def test_distinct_steps_pass_the_repetition_screen(self):
        lines = ["先收走台面杂物。", "用干净抹布蘸水。", "顺着纹路擦一遍。", "擦干后敞开放置。"]
        self.assertEqual(copy_local.repetition_codes(lines), [])
        self.assertEqual(copy_local.hazard_codes(lines), [])
        stationery = ["铅笔放进笔盒。", "橡皮单独装袋。", "尺子竖着摆好。", "便签放在上层。"]
        self.assertNotIn("repeated_phrase", copy_local.repetition_codes(stationery))
        self.assertNotIn("mix_agents", copy_local.hazard_codes(stationery))

    def test_word_error_is_zero_only_for_the_same_words(self):
        self.assertEqual(asr_edit.wer("He hoped there would be stew.", "he hoped there would be stew"), 0.0)
        self.assertGreater(asr_edit.wer("He hoped there would be stew.", "completely different words here"), 0.5)
        self.assertEqual(asr_edit.cer("台面", "台面"), 0.0)
