# -*- coding: utf-8 -*-
"""LLM 通道判活：让"兜底"别对着死通道撞。

## 问题

多家 LLM 提供商时，总有一两家长时间不可用（模型下线、额度耗尽、key 失效）。
如果兜底逻辑写死了一家，每次失败都要先白撞一次死通道——多等一轮超时，
账本里还多一条噪声，且**看不出兜底到底有没有生效**。

## 做法

双源，零网络：

1. **体检报告**（可选）：`{"qwen": "alive", "moonshot": "dead"}`，新鲜度在 TTL 内优先采用；
2. **调用账本**：JSONL，每行一次调用，读尾部 N 条自己算。

判活口径（故意保守）：

| 情况 | 结论 | 理由 |
|---|---|---|
| 最近一次成功 | `alive` | 能通就用 |
| 连续失败 ≥ `dead_streak` | `dead` | 稳定失败 = 真死 |
| 样本不足 | `unknown` | **新通道不误杀**，按活放行 |

## 用法

    >>> from dfg.llm_health import statuses, pick_alive
    >>> st = statuses("output/llm_call_log.jsonl")
    >>> pick_alive(["moonshot", "qwen"], st)      # 死通道自动跳过
    'qwen'
"""
from __future__ import annotations

import json
import time
from pathlib import Path

DEFAULT_TAIL = 400          # 账本只回看最近这么多条
DEFAULT_STREAK = 3          # 连续失败几次算死
DEFAULT_TTL_H = 24          # 体检报告多久内算新鲜


def _read_ledger(ledger, tail: int = DEFAULT_TAIL) -> dict:
    """读账本尾部 → `{provider: {"ok": n, "fail": n, "last_ok": bool}}`。"""
    out = {}
    if not ledger:
        return out
    p = Path(str(ledger))
    if not p.is_file():
        return out
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()[-tail:]
    except Exception:                                       # noqa: BLE001
        return out
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:                                   # noqa: BLE001
            continue
        name = d.get("provider") or d.get("display") or ""
        if not name:
            continue
        rec = out.setdefault(name, {"ok": 0, "fail": 0, "last_ok": False})
        if d.get("ok"):
            rec["ok"] += 1
            rec["last_ok"] = True
        else:
            rec["fail"] += 1
            rec["last_ok"] = False
    return out


def _read_report(report, ttl_h: float = DEFAULT_TTL_H):
    """读体检报告 → `({provider: status}, 年龄小时数)`。缺失/过期返回 `({}, inf)`。"""
    if not report:
        return {}, float("inf")
    p = Path(str(report))
    if not p.is_file():
        return {}, float("inf")
    try:
        age_h = (time.time() - p.stat().st_mtime) / 3600.0
        if age_h > ttl_h:
            return {}, age_h
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return {}, float("inf")
    if isinstance(data, dict):
        data = data.get("providers") or data.get("status") or data
    if not isinstance(data, dict):
        return {}, float("inf")
    return {str(k): str(v) for k, v in data.items()}, age_h


def statuses(ledger=None, report=None, tail: int = DEFAULT_TAIL,
             streak: int = DEFAULT_STREAK, ttl_h: float = DEFAULT_TTL_H) -> dict:
    """`{provider: "alive" | "dead" | "unknown"}`。

    体检报告（新鲜）优先，其次看账本。两边都没有的 provider 不出现在结果里
    —— 调用方用 `is_alive()` 取默认值（unknown 按活放行）。
    """
    out = {}
    rep, _age = _read_report(report, ttl_h)
    for name, val in rep.items():
        val = str(val).lower()
        if val in ("alive", "ok", "up", "true", "1"):
            out[name] = "alive"
        elif val in ("dead", "down", "fail", "false", "0"):
            out[name] = "dead"
        else:
            out[name] = "unknown"

    for name, rec in _read_ledger(ledger, tail).items():
        if name in out and out[name] != "unknown":
            continue
        if rec["last_ok"]:
            out[name] = "alive"
        elif rec["fail"] >= streak and rec["ok"] == 0:
            out[name] = "dead"
        elif rec["fail"] >= streak and not rec["last_ok"]:
            out[name] = "dead"
        else:
            out[name] = "unknown"
    return out


def is_alive(name: str, st: dict = None) -> bool:
    """某家现在能不能用。**没样本 = 按活放行**（新通道不该因为没跑过就被判死）。"""
    st = st or {}
    return st.get(str(name), "unknown") != "dead"


def pick_alive(names, st: dict = None, limit: int = 0) -> list:
    """按给定顺序过滤掉死通道；`limit>0` 时最多取前 N 家。"""
    st = st or {}
    out = [n for n in (names or []) if is_alive(n, st)]
    return out[:limit] if limit else out


def dead_list(st: dict = None) -> list:
    """所有判死的通道（诊断/体检用）。"""
    return sorted(k for k, v in (st or {}).items() if v == "dead")


def summary(st: dict = None) -> dict:
    """`{"alive": n, "dead": n, "unknown": n, "dead": [...]}`。"""
    st = st or {}
    return {
        "alive": sum(1 for v in st.values() if v == "alive"),
        "dead": sum(1 for v in st.values() if v == "dead"),
        "unknown": sum(1 for v in st.values() if v == "unknown"),
        "dead_list": dead_list(st),
    }
