# -*- coding: utf-8 -*-
"""示例阶段脚本 —— 只为演示 `dfg check` 的能力，不做任何真事。

它长得像一个真实的流水线阶段：注册了若干 flag，真正运行时才消费它们。
`dfg check` 会用 ast 读出下面这些 `add_argument`，再和你构造的命令行对账，
所以这个文件不需要被执行。（把 `--reroll` 删掉再跑一次 `dfg check`，
就能看到它抓住「命令里有、脚本不认」的那类事故。）
"""
import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="demo stage：对齐用，不产出")
    ap.add_argument("--series", default="demo", help="系列名")
    ap.add_argument("--force", action="store_true", help="强制重渲")
    ap.add_argument("--reroll", type=int, default=0, help="锁脸 reroll 次数")
    ap.add_argument("--out", default="output", help="产物目录")
    a = ap.parse_args(argv)
    print(f"[demo] series={a.series} force={a.force} reroll={a.reroll} out={a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
