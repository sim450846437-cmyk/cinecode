# -*- coding: utf-8 -*-
"""dfg —— DreamForge Gauges：AI 出片链路的四把「量具」。

这个包不含任何模型、卡池、提示词资产或业务规则。它只回答四个问题：

1. **我的命令真能跑吗**（`preflight`）—— 把「脚本注册了哪些 flag」和「我构造的命令行」
   逐项对账。这类错静态读代码看不出来，一点火就是 `unrecognized arguments` 炸整集。
2. **我在用的 LLM 通道还活着吗**（`llm_health`）—— 从调用账本 + 体检报告双源判活，
   让"兜底"不再撞死通道。零网络、零 GPU。
3. **导演按我写的提示词走了吗**（`adherence`）—— 把「有没有照做」变成可复核的数字，
   而不是"感觉跑偏了"。
4. **这两张图是同一个人吗 / 跨视角漂了多少**（`consistency`）—— 角色一致性的度量。

设计上的共同选择：**只度量，不做事**。不生成、不修复、不自动重跑。
量具的价值在于「让判断有据」，而不是替人做决定。
"""

__version__ = "0.1.0"

from .adherence import coverage, key_terms, report_line, text_of_storyboard
from .llm_health import dead_list, is_alive, pick_alive, statuses, summary
from .preflight import check_cmd, script_flags, script_subcommands

__all__ = [
    "key_terms", "coverage", "text_of_storyboard", "report_line",
    "statuses", "is_alive", "pick_alive", "dead_list", "summary",
    "script_flags", "script_subcommands", "check_cmd",
]
