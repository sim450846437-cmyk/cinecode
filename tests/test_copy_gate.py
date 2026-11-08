"""Screens for the local copy model. No llama process and no film."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import asr_edit
import copy_local


class Gate(unittest.TestCase):
    def test_pour_back_is_rejected_and_a_negated_line_is_not(self):
        self.assertEqual(copy_local.input_constraints("把用过的清洁液倒回原来的瓶子")[0]["code"], "pour_back")
        self.assertIn("forbidden_substance:白醋", copy_local.output_constraints("整理台面，不用清洁剂", ["用白醋擦一遍。"]))
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
        pasted = "build: x\n先把台面擦干净。喷一点水。顺着纹路擦开。把水渍擦干。"
        parsed = copy_local.parse_lines(pasted, "写四句清洁步骤")
        self.assertEqual(len(parsed), 4)
        self.assertTrue(parsed[0].startswith("先把台面"))

    def test_lines_copied_from_the_brief_are_an_echo(self):
        brief = "写四句：铅笔入笔筒、橡皮进盒、尺子排整齐、文具收好。"
        echo = ["铅笔入笔筒", "橡皮进盒", "尺子排整齐", "文具收好。"]
        own = ["先把铅笔竖进筒里。", "橡皮单独放进小盒。", "四把尺子并成一排。", "合上盒盖再看一眼。"]
        self.assertTrue(copy_local.prompt_echo(brief, echo))
        self.assertFalse(copy_local.prompt_echo(brief, own))


class ParseTrace(unittest.TestCase):
    def test_saved_clean_text_stays_two_actions_and_is_not_the_raw_field(self):
        raw = "移开杂物，用湿布擦台面。"
        report = copy_local.explain_parse(raw, "写四句简短台面清洁步骤")
        self.assertEqual(report["raw_stdout"], raw)
        self.assertEqual(report["lines"], ["移开杂物", "用湿布擦台面。"])
        self.assertTrue(report["drafts_are_parsed"])
        self.assertIn("too_few_lines", copy_local.repetition_codes(report["lines"]))
        self.assertFalse(any(step.get("reason") == "no_cjk" for step in report["parse_trace"]))

    def test_saved_stationery_clauses_split_without_inventing_text(self):
        raw = "铅笔入笔筒，橡皮进盒子。\n尺子排整齐，文具收好。"
        report = copy_local.explain_parse(raw, "写四句简短文具收纳步骤")
        self.assertEqual(report["lines"], ["铅笔入笔筒", "橡皮进盒子。", "尺子排整齐", "文具收好。"])
        self.assertEqual(report["raw_stdout"], raw)
        self.assertNotIn("too_few_lines", copy_local.repetition_codes(report["lines"]))

    def test_json_is_used_only_when_the_raw_text_parses(self):
        raw = 'note ["移开杂物", "用湿布擦台面", "擦干水渍", "收好抹布"]'
        report = copy_local.explain_parse(raw, "清洁")
        self.assertEqual(report["json_status"], "json_verified")
        self.assertEqual(len(report["lines"]), 4)
        self.assertEqual(report["raw_stdout"], raw)
        broken = copy_local.explain_parse("prefix [not json]", "清洁")
        self.assertEqual(broken["json_status"], "json_invalid")
        self.assertNotEqual(broken["lines"], ["移开杂物", "用湿布擦台面", "擦干水渍", "收好抹布"])

    def test_numbered_lines_synonyms_and_a_cut_off_tail(self):
        numbered = "1、移开杂物\n2、用湿布擦台面\n3、擦干水渍\n4、收好抹布"
        self.assertEqual(len(copy_local.parse_lines(numbered, "清洁")), 4)
        synonym = "用湿布把台面抹干净。\n把水印吸掉。\n抹布挂起来。\n杂物放回原处。"
        kept = copy_local.parse_lines(synonym, "写四句：擦台面、收抹布、擦水渍、移杂物")
        self.assertEqual(len(kept), 4)
        self.assertIn("湿布", kept[0])
        status = copy_local.explain_parse("文具收好，整洁有序。", "收纳")
        self.assertEqual(status["lines"], ["文具收好，整洁有序。"])
        self.assertTrue(any(step.get("reason") == "kept_together" for step in status["parse_trace"]))
        cut = copy_local.explain_parse("移开杂物。用湿布擦", "清洁")
        self.assertEqual(cut["lines"], ["移开杂物。"])
        self.assertEqual(cut["truncated_tail"], "用湿布擦")
        self.assertTrue(cut["truncated"])
        self.assertIn("too_few_lines", copy_local.repetition_codes(cut["lines"]))
        stationery = ["铅笔放进笔盒。", "橡皮单独装袋。", "尺子竖着摆好。", "便签放在上层。"]
        self.assertNotIn("repeated_phrase", copy_local.repetition_codes(stationery))
        self.assertNotIn("mix_agents", copy_local.hazard_codes(stationery))

    def test_word_error_is_zero_only_for_the_same_words(self):
        self.assertEqual(asr_edit.wer("He hoped there would be stew.", "he hoped there would be stew"), 0.0)
        self.assertLess(asr_edit.wer(
            "A COLD LUCID INDIFFERENCE REIGNED IN HIS SOUL",
            "A cold lucid indifference reigned in his soul."), 0.01)
        self.assertGreater(asr_edit.wer("He hoped there would be stew.", "completely different words here"), 0.5)
        self.assertEqual(asr_edit.cer("台面", "台面"), 0.0)
        self.assertEqual(asr_edit.synthetic_status("declared_recording"), "declared_not_synthetic")
        self.assertEqual(asr_edit.synthetic_status("unknown"), "unknown")
        ref = "而 对 楼市 成交 抑制 作用 最 大 的 限 购"
        heard = "而 对 面 螺 式 成 焦 一直 作 用 最 大的 线 构"
        self.assertAlmostEqual(asr_edit.cer(ref, heard), 8 / 15, places=4)
        self.assertGreater(asr_edit.wer(ref, heard), 0.5)
        self.assertNotEqual(asr_edit._norm_text(ref), asr_edit._norm_text(heard))


class SubstancePolicy(unittest.TestCase):
    """Limited list. Equivalent wording shares one policy. Unknown wording is not treated as safe."""

    def forbid(self, brief, constraints=None):
        policy = copy_local.build_policy(brief, constraints)
        self.assertEqual(policy["status"], "clear", policy["unparsed"])
        return tuple(policy["forbid_substances"])

    def test_equivalent_negations_share_the_cleaner_closure(self):
        expected = ("清洁剂", "白醋", "酒精")
        for brief in (
            "整理台面，不用清洁剂",
            "整理台面，不使用清洁剂",
            "整理台面，不要用清洁剂",
            "整理台面，禁止用清洁剂",
        ):
            self.assertEqual(self.forbid(brief), expected, brief)
        water = self.forbid("整理台面，仅用清水")
        self.assertIn("清洁剂", water)
        self.assertIn("白醋", water)
        self.assertIn("酒精", water)
        self.assertNotIn("清水", water)
        explicit = self.forbid("整理一下", {"forbid_substances": ["清洁剂"], "allow_only": []})
        self.assertEqual(explicit, expected)

    def test_quoted_ban_and_substitute_wording_still_block(self):
        brief = "不使用清洁剂"
        quoted = ["不要用白醋。", "热水擦干。", "收起抹布。", "看一眼台面。"]
        evasion = ["用热水加白醋擦拭台面。", "喷一点医用酒精。", "加一勺食用醋。", "擦干水渍。"]
        self.assertIn("forbidden_substance:白醋", copy_local.output_constraints(brief, quoted))
        self.assertIn("forbidden_substance:白醋", copy_local.output_constraints(brief, evasion))
        self.assertIn("forbidden_substance:酒精", copy_local.output_constraints(brief, evasion))
        policy, hits = copy_local.apply_policy(brief, evasion)
        self.assertEqual(policy["brief"], brief)
        self.assertTrue(policy["parsed_rules"])
        self.assertTrue(hits)

    def test_ordinary_briefs_are_not_treated_as_bans(self):
        for brief in ("把不用的铅笔收进笔筒", "不要用力折断铅笔", "文具分类摆好"):
            policy = copy_local.build_policy(brief)
            self.assertEqual(policy["status"], "clear")
            self.assertEqual(policy["forbid_substances"], [], brief)
        lines = ["铅笔放进笔盒。", "橡皮单独装袋。", "尺子竖着摆好。", "便签放在上层。"]
        self.assertEqual(copy_local.output_constraints("文具分类摆好", lines), [])
        amino = copy_local.find_substances("补充氨基酸。", ["氨"])
        self.assertEqual(amino, [])

    def test_unknown_negation_is_review_not_safe(self):
        for brief in ("切勿用漂白水", "不使用某种喷雾"):
            policy = copy_local.build_policy(brief)
            self.assertEqual(policy["status"], "needs_review", brief)
            self.assertTrue(policy["unparsed"])
        named = copy_local.build_policy("只擦台面", {"forbid_substances": ["苏打"]})
        self.assertEqual(named["status"], "needs_review")
        self.assertIn("not a general safety proof", named["coverage"])
