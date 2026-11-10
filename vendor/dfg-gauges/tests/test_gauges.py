# -*- coding: utf-8 -*-
"""dfg 的 pytest 测试（也可直接 `python tests/test_gauges.py`）。

只测**不需要模型**的部分：adherence / preflight / llm_health / consistency 的数学。
一致性检测器的真跑需要 torch + 权重，不进 CI。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows 控制台默认 cp1252 / cp936，最后那行中文汇总会 UnicodeEncodeError：
#   UnicodeEncodeError: 'charmap' codec can't encode characters in position 8-10
# 结果是 32 个用例全跑完、全 PASS，进程却在打印汇总时崩掉 → CI 三个 Windows
# job 全红，看起来像测试挂了，其实是报告打不出来。errors="replace" 保证
# 哪怕终端字库缺失也只丢字符，不会让整轮结果变成 1。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):                    # pytest capture / 重定向流
        pass

# 缺依赖时必须**显式跳过**，不能假装通过 —— 「静默 PASS」比红灯更危险：
# 用户看到 28/28 会以为一致性后端被测过了，其实一行没跑。
_SKIPPED: list = []


def skip(reason: str) -> str:
    _SKIPPED.append(reason)
    return "skip"


def _require(mods, what):
    """这些包不全在，就跳过（返回 skip 标记），否则返回 None。"""
    for m in mods:
        try:
            __import__(m)
        except Exception:                                   # noqa: BLE001
            return skip(f"缺 {m}，{what}用例跳过")
    return None


from dfg.adherence import coverage, key_terms, report_line, text_of_storyboard  # noqa: E402
from dfg.llm_health import dead_list, is_alive, pick_alive, statuses, summary  # noqa: E402
from dfg.preflight import check_cmd, script_flags, script_subcommands  # noqa: E402


# ============================================================ adherence
def test_quoted_name_wins():
    """引号里的专名优先级最高 —— 它是最硬的约束。"""
    assert "林小满" in key_terms('深夜便利店，女主叫「林小满」')


def test_long_sentence_is_cut():
    """整句长要素几乎不可能原样命中，必须切成短语（否则全是假警报）。"""
    terms = key_terms("深夜便利店里的独白")
    assert "深夜便利店" in terms
    assert all(len(t) <= 12 for t in terms)


def test_lead_verbs_stripped():
    """`有枚青铜戒指` → `青铜戒指`（不剥前缀就永远命中不了正文）。"""
    assert "青铜戒指" in key_terms("她手上有枚青铜戒指")


def test_empty_prompt_not_applicable():
    """没有提示词 = 不适用。绝不能判成"跑偏"（那是误伤）。"""
    r = coverage("", "任何文本")
    assert r["terms"] == 0 and r["ratio"] is None and r["ok"] is True


def test_full_hit_is_ok():
    r = coverage("雨天 油纸伞", "雨天她撑着一把油纸伞")
    assert r["ratio"] == 1.0 and r["ok"]


def test_miss_lists_what_is_missing():
    """落后要说得出来是哪几条，否则没法改。"""
    r = coverage("雨天 油纸伞 朱红立柱", "她撑着一把油纸伞")
    assert not r["ok"]
    assert "朱红立柱" in r["miss_terms"]


def test_no_semantic_matching():
    """刻意不做语义相似：雨天 ≠ 雨里。宁可漏判，也不要不可复核的"像"。"""
    assert not coverage("雨天", "她站在雨里")["ok"]


def test_storyboard_fields_collected():
    data = {"title": "夜访", "scenes": [
        {"visual": "霓虹灯下的巷口", "action": ["她回头", "风吹起衣角"]},
        {"subtitle": "别过来"},
    ]}
    txt = text_of_storyboard(data)
    assert "夜访" in txt and "霓虹灯" in txt and "风吹起衣角" in txt and "别过来" in txt


def test_report_line_readable():
    line = report_line({"terms": 3, "hit": 3, "ratio": 1.0, "miss_terms": [], "ok": True})
    assert "3/3" in line and "落地" in line
    assert report_line({"terms": 0}) == ""


# ============================================================ preflight
def _fake_script(tmp: Path) -> Path:
    p = tmp / "fake.py"
    p.write_text(
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--force', action='store_true')\n"
        "p.add_argument('-n', '--num', type=int, default=0)\n"
        "sub = p.add_subparsers()\n"
        "sub.add_parser('run')\n"
        "sub.add_parser('post')\n", encoding="utf-8")
    return p


def test_flags_discovered(tmp_path):
    s = _fake_script(tmp_path)
    flags = script_flags(s)
    assert {"--force", "--num", "-n"} <= flags


def test_subcommands_discovered(tmp_path):
    assert {"run", "post"} <= script_subcommands(_fake_script(tmp_path))


def test_check_cmd_pass(tmp_path):
    s = _fake_script(tmp_path)
    assert check_cmd([sys.executable, str(s), "--force", "-n", "3"]).ok


def test_check_cmd_catches_unknown(tmp_path):
    """核心价值：不存在的 flag 在点火前就被抓出来。"""
    s = _fake_script(tmp_path)
    r = check_cmd([sys.executable, str(s), "--force", "--nope"])
    assert not r.ok and "--nope" in r.unknown


def test_check_cmd_equals_form(tmp_path):
    assert check_cmd([sys.executable, str(_fake_script(tmp_path)), "--num=5"]).ok


def test_check_cmd_missing_script(tmp_path):
    r = check_cmd([sys.executable, str(tmp_path / "nope.py")])
    assert not r.ok


def test_check_cmd_no_flags_is_note_not_fail(tmp_path):
    """扫不到 add_argument 时是"无法对账"，不能算通过也不能算失败。"""
    p = tmp_path / "dyn.py"
    p.write_text("print(1)\n", encoding="utf-8")
    r = check_cmd([sys.executable, str(p), "--whatever"])
    assert r.ok and r.note


# ============================================================ llm_health
def _ledger(tmp: Path, rows) -> Path:
    p = tmp / "l.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def test_alive_after_success(tmp_path):
    st = statuses(ledger=_ledger(tmp_path, [{"provider": "a", "ok": True}]))
    assert st["a"] == "alive"


def test_dead_after_streak(tmp_path):
    rows = [{"provider": "b", "ok": False}] * 3
    assert statuses(ledger=_ledger(tmp_path, rows))["b"] == "dead"


def test_unknown_not_killed(tmp_path):
    """新通道没跑过 = unknown，必须按活放行，否则永远轮不到它。"""
    st = statuses(ledger=_ledger(tmp_path, [{"provider": "c", "ok": False}]))
    assert st["c"] == "unknown" and is_alive("c", st)


def test_pick_alive_skips_dead(tmp_path):
    rows = ([{"provider": "dead", "ok": False}] * 4
            + [{"provider": "good", "ok": True}])
    st = statuses(ledger=_ledger(tmp_path, rows))
    assert pick_alive(["dead", "good"], st) == ["good"]
    assert pick_alive(["dead", "good"], st, limit=1) == ["good"]
    assert dead_list(st) == ["dead"]


def test_report_takes_precedence(tmp_path):
    rep = tmp_path / "h.json"
    rep.write_text(json.dumps({"x": "dead"}), encoding="utf-8")
    led = _ledger(tmp_path, [{"provider": "x", "ok": True}])
    st = statuses(ledger=led, report=rep)
    assert st["x"] == "dead"          # 体检报告比账本更"权威"


def test_summary_shape(tmp_path):
    rows = [{"provider": "a", "ok": True}] + [{"provider": "b", "ok": False}] * 3
    s = summary(statuses(ledger=_ledger(tmp_path, rows)))
    assert s["alive"] == 1 and s["dead"] == 1 and s["dead_list"] == ["b"]


def test_missing_ledger_is_not_fatal(tmp_path):
    """没有账本不该崩 —— 部署早期本来就没有调用记录。"""
    assert statuses(ledger=tmp_path / "nope.jsonl") == {}


# ============================================================ consistency 数学
def test_cosine_basics():
    """余弦是纯 Python 的：核心依赖为空时也必须能算对。"""
    from dfg.consistency import cosine
    assert abs(cosine([1, 0], [1, 0]) - 1) < 1e-6
    assert abs(cosine([1, 0], [0, 1])) < 1e-6
    assert abs(cosine([3, 0], [7, 0]) - 1) < 1e-6      # 不看模长
    assert cosine([0, 0], [1, 1]) == 0.0               # 零向量不炸、不返回 NaN


def test_score_matrix_needs_numpy():
    """矩阵版是批量诊断用的，允许依赖 numpy —— 缺了要显式跳过。"""
    if _require(["numpy"], "score_matrix"):
        return "skip"
    import numpy as np
    from dfg.consistency import score_matrix
    m = score_matrix(np.array([[1.0, 0.0], [0.0, 1.0]]))
    assert abs(m[0][0] - 1) < 1e-6 and abs(m[0][1]) < 1e-6


def test_missing_backend_raises_not_zero():
    """缺依赖必须明确报错 —— 静默返回 0 分比没有分更危险。"""
    from dfg.consistency import BackendMissing, pick_backend
    try:
        pick_backend("definitely_not_a_backend")
    except BackendMissing:
        return
    raise AssertionError("未知后端应当抛 BackendMissing")


# ------------------------------------------------------------ comfy 后端（用假模块守护）
def _fake_comfy():
    """造一个假的 comfy：返回与真 ComfyUI 同形状的 Output 包装。

    真 Output 的 `__getitem__` 是 `getattr(self, key)`，传 int 直接 TypeError
    —— 2026-11-01 的 bug 正是 `feats[0]` 撞上这个。假模块必须复现该行为，
    否则守护不住。
    """
    import types

    torch = __import__("torch")

    class _Output:
        def __init__(self, emb):
            self.image_embeds = emb

        def __getitem__(self, key):
            return getattr(self, key)          # 传 int 会 TypeError，与真实现一致

    class _Model:
        def encode_image(self, t):
            calls["encode"] += 1
            return _Output(torch.ones(1, 8))

    calls = {"load": 0, "encode": 0}

    def load(_path):
        calls["load"] += 1
        return _Model()

    class CPUState:
        CPU = 1
        GPU = 0

    cv = types.ModuleType("comfy.clip_vision")
    cv.load = load
    mm = types.ModuleType("comfy.model_management")
    mm.CPUState = CPUState
    mm.cpu_state = 0
    mm.soft_empty_cache = lambda: None
    pkg = types.ModuleType("comfy")
    pkg.clip_vision = cv
    pkg.model_management = mm

    sys.modules.update({"comfy": pkg, "comfy.clip_vision": cv,
                        "comfy.model_management": mm})
    return calls, mm, CPUState


def _png(path, color=(120, 130, 140)):
    from PIL import Image
    Image.new("RGB", (64, 64), color).save(path)
    return path


def test_find_clip_vision_by_env(tmp_path):
    """手上已有 CLIP-ViT-H-14 就别让人再下一份 3.9G。

    报错文案里承诺「放到 ComfyUI/models/clip_vision/ 下会自动找」——
    这条测试保证它不是一句空话。
    """
    import os
    from dfg.consistency import find_clip_vision

    d = tmp_path / "models" / "clip_vision"
    d.mkdir(parents=True)
    f = d / "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
    f.write_bytes(b"stub")

    old = os.environ.get("COMFYUI_PATH")
    os.environ["COMFYUI_PATH"] = str(tmp_path)
    try:
        got = find_clip_vision()
    finally:
        if old is None:
            os.environ.pop("COMFYUI_PATH", None)
        else:
            os.environ["COMFYUI_PATH"] = old
    assert got, "COMFYUI_PATH 指向的目录里有权重，却没找到"
    assert Path(got).name == f.name


def test_floor_auto_is_per_view():
    """`--floor auto` 必须按视角分级 —— 一刀切在全身上会误判四分之一。

    实测（419 张真实卡）：统一 0.70 时全身 24.8% 被判漂移、背影 16.5%；
    换成按视角分级后只有 3.8% 真报警。默认行为必须保持不变（老调用方依赖它）。
    """
    from dfg.consistency import FLOOR_BY_VIEW, _floor_for

    assert _floor_for("full.png", "auto", "comfy", 0.70) == FLOOR_BY_VIEW["full"]
    assert _floor_for("back.png", "auto", "comfy", 0.70) == FLOOR_BY_VIEW["back"]
    assert _floor_for("side.png", "auto", "comfy", 0.70) == 0.70
    assert _floor_for("whatever.png", "auto", "comfy", 0.70) == 0.70   # 认不出 → 回落
    # 老行为：不传 floor / 传数字，一律统一线
    assert _floor_for("full.png", None, "comfy", 0.70) == 0.70
    assert _floor_for("full.png", 0.6, "comfy", 0.70) == 0.6
    # 自己给 dict
    assert _floor_for("full.png", {"full": 0.4}, "comfy", 0.70) == 0.4
    assert _floor_for("side.png", {"full": 0.4}, "comfy", 0.70) == 0.70


def test_floor_by_view_is_looser_for_far_views():
    """分级线必须真的更宽松 —— 否则等于没分级（全身天然分低是物理事实）。"""
    from dfg.consistency import FLOOR_BY_VIEW
    assert FLOOR_BY_VIEW["full"] < FLOOR_BY_VIEW["three_quarter"]
    assert FLOOR_BY_VIEW["back"] < FLOOR_BY_VIEW["side"]


def test_comfy_reads_image_embeds_not_index(tmp_path):
    """comfy 后端必须取 `out["image_embeds"]` 而不是 `out[0]`。

    真 ComfyUI 的 Output 只支持字符串键；写成 `feats[0]` 会 TypeError。
    这条测试用假模块复现真行为，防止再退回。
    """
    _gap = _require(("torch", "numpy", "PIL"), "comfy 后端")
    if _gap:
        return _gap
    from dfg import consistency
    old_cache = dict(consistency._COMFY_CACHE)
    consistency._COMFY_CACHE.clear()
    saved = {k: sys.modules.get(k) for k in ("comfy", "comfy.clip_vision",
                                             "comfy.model_management")}
    try:
        _fake_comfy()
        img = _png(tmp_path / "a.png")
        embs = consistency._embed_comfy([img], device="cpu", clip_path="fake.safetensors")
        assert embs.shape[0] == 1, "应当返回 1 行向量"
    finally:
        consistency._COMFY_CACHE.clear()
        consistency._COMFY_CACHE.update(old_cache)
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_comfy_model_loaded_once_for_many_images(tmp_path):
    """3.9G 权重整进程只该加载一次 —— 否则批量测几百张卡就是在反复读盘。"""
    _gap = _require(("torch", "numpy", "PIL"), "comfy 后端")
    if _gap:
        return _gap
    from dfg import consistency
    consistency._COMFY_CACHE.clear()
    saved = {k: sys.modules.get(k) for k in ("comfy", "comfy.clip_vision",
                                             "comfy.model_management")}
    try:
        calls, _mm, _state = _fake_comfy()
        imgs = [_png(tmp_path / f"{i}.png", (i * 10, 100, 120)) for i in range(4)]
        consistency._embed_comfy(imgs, clip_path="fake.safetensors")
        consistency._embed_comfy(imgs, clip_path="fake.safetensors")
        assert calls["load"] == 1, f"模型被加载了 {calls['load']} 次，应为 1"
        assert calls["encode"] == 8, f"编码 {calls['encode']} 次，应为 8"
    finally:
        consistency._COMFY_CACHE.clear()
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_comfy_cpu_device_forces_cpu_state(tmp_path):
    """`device="cpu"` 必须真生效：GPU 被出图占满时，量具不该去抢显存。"""
    _gap = _require(("torch", "numpy", "PIL"), "comfy 后端")
    if _gap:
        return _gap
    from dfg import consistency
    consistency._COMFY_CACHE.clear()
    saved = {k: sys.modules.get(k) for k in ("comfy", "comfy.clip_vision",
                                             "comfy.model_management")}
    try:
        _calls, mm, state = _fake_comfy()
        consistency._embed_comfy([_png(tmp_path / "c.png")], device="cpu",
                                 clip_path="fake.safetensors")
        assert mm.cpu_state == state.CPU, "device='cpu' 没有真的把 comfy 切到 CPU"
    finally:
        consistency._COMFY_CACHE.clear()
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ============================================================ 直接跑
if __name__ == "__main__":
    import tempfile
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    skipped = 0
    fails = []
    for fn in fns:
        try:
            if fn.__code__.co_argcount == 0:
                res = fn()
            else:
                with tempfile.TemporaryDirectory() as td:
                    res = fn(Path(td))
            if res == "skip":
                skipped += 1
                print(f"  [SKIP] {fn.__name__}：{_SKIPPED[-1] if _SKIPPED else ''}")
                continue
            ok += 1
            print(f"  [PASS] {fn.__name__}")
        except Exception as e:                              # noqa: BLE001
            fails.append(fn.__name__)
            print(f"  [FAIL] {fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
    tail = f"{ok}/{len(fns)} 通过"
    if skipped:
        tail += f"，{skipped} 跳过（缺依赖，未真正验证）"
    if fails:
        tail += f"，失败 {fails}"
    print("\n" + tail)
    sys.exit(1 if fails else 0)
