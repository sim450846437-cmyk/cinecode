# -*- coding: utf-8 -*-
"""命令行 ↔ argparse 对账：在点火**之前**发现「这个 flag 根本不存在」。

## 问题

流水线把命令**构造**在一处、把参数**注册**在另一处。两边漂了，静态读代码看不出来：
`subprocess` 照跑，脚本 `argparse` 直接 `unrecognized arguments: --force` 退出，
整集白跑。这类事故的代价随批量规模线性放大（跑到第 7 集才发现）。

## 做法

用 `ast` 静态解析目标脚本，收集它**注册过的** flag；再把待跑命令拆开，
逐个 `--xxx` 比对。零执行、零 import —— 不启动被检查的程序，不给它副作用。

## 用法

    >>> from dfg import script_flags, check_cmd
    >>> flags = script_flags("scripts/render.py")
    >>> r = check_cmd(["python", "scripts/render.py", "--force", "--reroll", "2"], flags)
    >>> r.ok, r.unknown
    (True, [])

`check_cmd` 只回答"这几个 flag 认不认"，不做业务校验（那是被测程序自己的事）。
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


def script_flags(path) -> set:
    """扫出脚本里 `add_argument(...)` 注册过的所有 flag。

    同时认短选项（`-f`）与长选项（`--force`）；子命令（`add_subparsers`）
    由 `script_subcommands()` 单独取。解析失败返回空集（调用方据此降级为告警）。
    """
    p = Path(str(path or ""))
    if not p.is_file():
        return set()
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:                                       # noqa: BLE001
        return set()
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "attr", None) or getattr(fn, "id", None)
        if name != "add_argument":
            continue
        for a in node.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                    and a.value.startswith("-"):
                out.add(a.value)
        for kw in node.keywords:
            if kw.arg in ("dest", "help") and isinstance(kw.value, ast.Constant):
                continue
    return out


def script_subcommands(path) -> set:
    """扫出 `add_parser("name")` 注册过的子命令名。"""
    p = Path(str(path or ""))
    if not p.is_file():
        return set()
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:                                       # noqa: BLE001
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if getattr(node.func, "attr", None) == "add_parser" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    out.add(a.value)
    return out


@dataclass
class CmdCheck:
    """一条命令的对账结果。"""
    ok: bool = True
    script: str = ""
    unknown: list = field(default_factory=list)     # 脚本没注册的 flag
    known: list = field(default_factory=list)       # 对上的 flag
    note: str = ""                                  # 无法对账时的原因

    def line(self) -> str:
        if self.note:
            return f"[skip] {self.script}：{self.note}"
        if self.unknown:
            return f"[FAIL] {self.script} 不认 {self.unknown}"
        return f"[PASS] {self.script}（{len(self.known)} 个 flag 对上）"


def check_cmd(cmd, flags=None) -> CmdCheck:
    """对账一条命令。

    `cmd` 形如 `["python", "scripts/x.py", "--force", "--reroll", "2"]`；
    脚本路径取 `cmd[1]`（可只传脚本路径）。`flags` 可预扫好传进来省 IO。

    规则：
      * `--flag=value` 形式只取 `=` 前部分比对；
      * 裸值（`2`、文件名）不参与 flag 对账；
      * 脚本里一个 flag 都没扫到 ⇒ 归为"无法对账"（note），不算通过也不算失败。
    """
    res = CmdCheck()
    if isinstance(cmd, (str, Path)):
        cmd = [str(cmd)]
    cmd = [str(x) for x in cmd]
    if len(cmd) < 1:
        res.ok = False
        res.note = "空命令"
        return res
    script = cmd[1] if len(cmd) > 1 else cmd[0]
    res.script = Path(script).name
    if not Path(script).is_file():
        res.ok = False
        res.note = f"脚本不存在：{script}"
        return res

    if flags is None:
        flags = script_flags(script)
    if not flags:
        res.note = "脚本里没扫到 add_argument（动态构造？跳对账）"
        return res

    for tok in cmd[2:]:
        if not tok.startswith("--"):
            continue
        key = tok.split("=", 1)[0]
        if key in flags:
            res.known.append(key)
        else:
            res.unknown.append(key)
    res.ok = not res.unknown
    return res


def check_commands(cmds) -> list:
    """批量对账：`[(label, cmd), ...]` → `[(label, CmdCheck), ...]`。"""
    return [(label, check_cmd(cmd)) for label, cmd in cmds]
