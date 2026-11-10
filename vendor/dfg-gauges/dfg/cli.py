# -*- coding: utf-8 -*-
"""dfg 命令行入口。

    dfg adherence --prompt "深夜便利店，女主叫「林小满」" --storyboard sb.json
    dfg health --ledger output/llm_call_log.jsonl --pick moonshot,qwen
    dfg check --script scripts/render.py --cmd "--force --reroll 2"
    dfg consistency --anchor cast/a/anchor.png --views cast/a/views --backend hf
    dfg selftest

设计：每个子命令只做一件事，退出码 0/1 表达"通过/有问题"，
可以放心塞进 CI 或 shell 的 `&&` 链。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _p(msg=""):
    print(msg)


# ============================================================ adherence
def cmd_adherence(a) -> int:
    from .adherence import coverage, coverage_of_storyboard, key_terms, report_line

    if a.storyboard:
        res = coverage_of_storyboard(a.prompt, a.storyboard, floor=a.floor)
    elif a.text:
        res = coverage(a.prompt, a.text, floor=a.floor)
    elif a.text_file:
        p = Path(a.text_file)
        if not p.is_file():
            _p(f"✖ 文本不存在：{p}")
            return 1
        res = coverage(a.prompt, p.read_text(encoding="utf-8", errors="ignore"), floor=a.floor)
    else:
        _p("需要 --storyboard / --text / --text-file 之一")
        return 1

    if a.json:
        _p(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        _p(f"要素：{key_terms(a.prompt)}" if a.verbose else "")
        line = report_line(res)
        _p(line or "（没有提示词，不适用）")
        if res.get("note"):
            _p(f"  注：{res['note']}")
    if not res.get("terms"):
        return 0                       # 没有提示词 = 不适用，不算失败
    return 0 if res.get("ok") else 1


# ============================================================ health
def cmd_health(a) -> int:
    from .llm_health import is_alive, pick_alive, statuses, summary

    st = statuses(ledger=a.ledger, report=a.report, tail=a.tail,
                  streak=a.streak, ttl_h=a.ttl)
    if a.json:
        _p(json.dumps({"statuses": st, "summary": summary(st)}, ensure_ascii=False, indent=2))
    else:
        s = summary(st)
        _p(f"活 {s['alive']} / 死 {s['dead']} / 未知 {s['unknown']}")
        for name in sorted(st):
            icon = {"alive": "✓", "dead": "✗", "unknown": "?"}[st[name]]
            _p(f"  {icon} {name:<18} {st[name]}")

    if a.pick:
        cands = [x.strip() for x in a.pick.split(",") if x.strip()]
        alive = pick_alive(cands, st, limit=a.limit)
        _p(f"\n兜底候选（跳过死通道）：{alive or '（全死，不阻断但会白撞）'}")
        if not alive:
            return 1
        if a.assert_:
            dead_in = [x for x in cands if not is_alive(x, st)]
            if dead_in:
                _p(f"✖ 断言失败：候选里含死通道 {dead_in}")
                return 1
    return 0


# ============================================================ check
def cmd_check(a) -> int:
    from .preflight import check_cmd, script_flags

    script = a.script
    extra = [x for x in (a.cmd or "").split() if x]
    cmd = [sys.executable, script, *extra]
    flags = script_flags(script)
    res = check_cmd(cmd, flags)
    if a.json:
        _p(json.dumps({"ok": res.ok, "script": res.script, "known": res.known,
                       "unknown": res.unknown, "note": res.note},
                      ensure_ascii=False, indent=2))
    else:
        _p(res.line())
        if res.unknown and a.verbose:
            _p(f"  脚本注册过的 flag（共 {len(flags)}）：{sorted(flags)}")
    return 0 if res.ok or res.note else 1


# ============================================================ consistency
def cmd_consistency(a) -> int:
    try:
        from .consistency import compare, verdict_line
    except Exception as e:                                  # noqa: BLE001
        _p(f"✖ 无法加载 consistency：{type(e).__name__}: {e}")
        return 1

    refs = []
    for v in (a.views or []):
        p = Path(v)
        if p.is_dir():
            # 跳过 `_` / `.` 开头的文件：重绘前留的 `_back_k2.png` 这类备份
            # 常和正式视角同目录，混进来会被当成「第 5 个视角」拉低 median。
            refs += sorted([x for x in p.iterdir()
                            if x.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                            and not x.name.startswith(("_", "."))])
        elif p.is_file():
            refs.append(p)
        else:
            _p(f"⚠ 跳过不存在的路径：{p}")
    if not refs:
        _p("需要 --views 指向目录或若干图片")
        return 1
    try:
        fl = a.floor
        if isinstance(fl, str) and fl.strip().lower() != "auto":
            fl = float(fl)                      # 允许 --floor 0.75 这种字符串输入
        rep = compare(a.anchor, refs, backend=a.backend, floor=fl,
                      device=a.device, clip_path=a.clip)
    except Exception as e:                                  # noqa: BLE001
        _p(f"✖ {type(e).__name__}: {e}")
        return 1
    if a.json:
        _p(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        _p(verdict_line(rep))
        floors = rep.get("floors") or {}
        for k, v in sorted(rep["scores"].items(), key=lambda kv: kv[1]):
            mark = "⚠" if v < floors.get(k, 0) else " "
            _p(f"  {mark} {k:<24} {v}  (线 {floors.get(k, rep.get('floor'))})")
        _p(f"\n注：{rep['disclaimer']}")
    return 0 if rep["verdict"] == "consistent" else 1


# ============================================================ selftest
def cmd_selftest(_a) -> int:
    """零外部依赖的自检：只验 adherence / preflight / llm_health 三件纯逻辑。"""
    import tempfile

    from .adherence import coverage, key_terms, report_line
    from .llm_health import is_alive, pick_alive, statuses
    from .preflight import check_cmd, script_flags

    n_ok, fails = 0, []
    n_skip = [0]

    def ck(cond, name, detail=""):
        nonlocal n_ok
        if cond:
            n_ok += 1
            _p(f"  [PASS] {name}")
        else:
            fails.append(name)
            _p(f"  [FAIL] {name}  {detail}")

    # adherence
    t = key_terms('深夜便利店里的独白，女主叫「林小满」，手上有枚青铜戒指')
    ck("林小满" in t, "拆出引号专名", str(t))
    ck("深夜便利店" in t, "按虚词切短语", str(t))
    ck(not any(len(x) > 12 for x in t), "要素长度受限（不制造整句假警报）", str(t))
    ck(key_terms("") == [], "空提示词 → 空要素")
    r = coverage("雨天 油纸伞", "雨天她撑着一把油纸伞")
    ck(r["ok"] and r["ratio"] == 1.0, "全命中判遵从", str(r))
    r0 = coverage("雨天", "她站在雨里")          # 原样匹配：不做同义替换
    ck(not r0["ok"], "不做语义相似（雨天 ≠ 雨里，宁可不判", str(r0))
    r2 = coverage("雨天 油纸伞 朱红立柱", "她撑着一把油纸伞")
    ck(not r2["ok"], "缺要素判不遵从", str(r2))
    ck("朱红立柱" in r2["miss_terms"], "缺哪条说得出来", str(r2["miss_terms"]))
    ck(coverage("", "任意")["ratio"] is None, "空提示词 = 不适用（ratio=None）")
    ck(report_line({"terms": 3, "hit": 3, "ratio": 1.0, "miss_terms": [], "ok": True})
       .endswith("要素全部落地"), "报告行可读")

    # preflight
    with tempfile.TemporaryDirectory() as td:
        s = Path(td) / "fake.py"
        s.write_text(
            "import argparse\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--force', action='store_true')\n"
            "p.add_argument('--reroll', type=int, default=0)\n"
            "sub = p.add_subparsers()\n"
            "sub.add_parser('run')\n", encoding="utf-8")
        fl = script_flags(s)
        ck({"--force", "--reroll"} <= fl, "扫出注册的 flag", str(fl))
        ck(check_cmd([sys.executable, str(s), "--force"]).ok, "对得上的命令判通过")
        bad = check_cmd([sys.executable, str(s), "--force", "--nope"])
        ck(not bad.ok and "--nope" in bad.unknown, "对不上的 flag 抓得住", str(bad.unknown))
        ck(check_cmd([sys.executable, str(s), "--reroll=2"]).ok, "--k=v 形式也认")
        ck(check_cmd([sys.executable, str(Path(td) / "nope.py")]).ok is False,
           "脚本不存在判失败")

    # llm_health
    with tempfile.TemporaryDirectory() as td:
        led = Path(td) / "l.jsonl"
        rows = ([{"provider": "good", "ok": True}] * 2
                + [{"provider": "bad", "ok": False}] * 4
                + [{"provider": "newbie", "ok": False}])
        led.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
        st = statuses(ledger=led)
        ck(st.get("good") == "alive", "成功过 ⇒ 活", str(st))
        ck(st.get("bad") == "dead", "连败 ≥3 ⇒ 死", str(st))
        ck(st.get("newbie") == "unknown", "样本不足 ⇒ 未知（不误杀）", str(st))
        ck(is_alive("newbie", st), "未知按活放行")
        ck(pick_alive(["bad", "good"], st) == ["good"], "兜底跳过死通道")

    # consistency 的数学部分（不加载模型：骨架要能在无 torch 环境自证）
    # cosine 是纯 Python 的，任何环境都必须真跑；只有矩阵版要用 numpy。
    from .consistency import cosine

    ck(abs(cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-6, "cosine 同向 = 1")
    ck(abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-6, "cosine 正交 = 0")
    ck(abs(cosine([2.0, 0.0], [5.0, 0.0]) - 1.0) < 1e-6, "cosine 不看模长（未归一也等于 1）")
    try:
        import numpy as np

        from .consistency import score_matrix

        m = score_matrix(np.array([[1.0, 0.0], [0.0, 1.0]]))
        ck(abs(m[0][0] - 1.0) < 1e-6 and abs(m[0][1]) < 1e-6, "score_matrix 对角=1、正交=0")
    except ImportError:
        n_skip[0] += 1
        _p("  [SKIP] score_matrix（未装 numpy；余弦部分已真跑）")
    except Exception as e:                                  # noqa: BLE001
        ck(False, "score_matrix 自检", f"{type(e).__name__}: {e}")

    # 跳过项必须进统计 —— 「20 通过 / 0 失败」看起来像全过，
    # 但实际少跑了 4 项。静默的覆盖率比红灯更危险。
    skip_tail = f" / {n_skip[0]} 跳过（缺依赖，未真验）" if n_skip[0] else ""
    _p(f"\n自检：{n_ok} 通过{skip_tail} / {len(fails)} 失败")
    return 1 if fails else 0


# ============================================================ main
def main(argv=None) -> int:
    # Windows 控制台默认 cp1252 / cp936：不加 errors="replace" 时，遇到终端字库
    # 里没有的字符会抛 UnicodeEncodeError，把「通过/失败」汇总整段吞掉。
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):                # 重定向流 / 无 reconfigure
            pass

    ap = argparse.ArgumentParser(prog="dfg", description="DreamForge Gauges：出片链路的量具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("adherence", help="提示词遵从度：写了就必须照做")
    p1.add_argument("--prompt", required=True)
    p1.add_argument("--storyboard", default="", help="分镜 JSON")
    p1.add_argument("--text", default="", help="直接给一段文本")
    p1.add_argument("--text-file", default="", help="从文件读文本")
    p1.add_argument("--floor", type=float, default=0.6)
    p1.add_argument("--json", action="store_true")
    p1.add_argument("-v", "--verbose", action="store_true")
    p1.set_defaults(fn=cmd_adherence)

    p2 = sub.add_parser("health", help="LLM 通道判活")
    p2.add_argument("--ledger", default="", help="调用账本 JSONL")
    p2.add_argument("--report", default="", help="体检报告 JSON（可选，24h 内优先）")
    p2.add_argument("--pick", default="", help="按此顺序挑活着的（逗号分隔）")
    p2.add_argument("--limit", type=int, default=0)
    p2.add_argument("--tail", type=int, default=400)
    p2.add_argument("--streak", type=int, default=3)
    p2.add_argument("--ttl", type=float, default=24.0)
    p2.add_argument("--assert", dest="assert_", action="store_true",
                    help="候选里含死通道则退出码 1（CI 用）")
    p2.add_argument("--json", action="store_true")
    p2.set_defaults(fn=cmd_health)

    p3 = sub.add_parser("check", help="命令行 ↔ argparse 对账")
    p3.add_argument("--script", required=True)
    p3.add_argument("--cmd", default="", help='要验证的参数，如 "--force --reroll 2"')
    p3.add_argument("--json", action="store_true")
    p3.add_argument("-v", "--verbose", action="store_true")
    p3.set_defaults(fn=cmd_check)

    p4 = sub.add_parser("consistency", help="角色一致性：同一个人吗 / 漂了多少")
    p4.add_argument("--anchor", required=True, help="锚图")
    p4.add_argument("--views", nargs="+", required=True, help="参考图目录或若干图片")
    p4.add_argument("--backend", default="auto", choices=["auto", "hf", "comfy", "arcface"])
    p4.add_argument("--floor", default=None,
                    help="强一致线：给数字，或 auto = 按视角分级（全身/背影更低，"
                         "测跨视角一致性建议用 auto）")
    p4.add_argument("--device", default="auto")
    p4.add_argument("--clip", default="", help="comfy 后端的 CLIP safetensors 路径")
    p4.add_argument("--json", action="store_true")
    p4.set_defaults(fn=cmd_consistency)

    p5 = sub.add_parser("selftest", help="零依赖自检")
    p5.set_defaults(fn=cmd_selftest)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
