#!/usr/bin/env python3
"""Optional synthetic Mandarin fixture. The speech job does not call this.

One espeak-ng pinyin utterance with a pause inside it. The wav is synthetic
test audio, not a human recording, and this process does not listen to it.
Exit 3 when espeak-ng is absent. Production ASR must not require this program.
"""
import argparse
import json
import shutil
import subprocess
import sys

from pypinyin import Style, lazy_pinyin


def to_pinyin(text):
    pieces = []
    buf = []
    for ch in text:
        if ch in "。！？；":
            if buf:
                pieces.append(" ".join(lazy_pinyin("".join(buf), style=Style.TONE3, neutral_tone_with_five=True)))
                buf = []
            pieces.append('<break time="700ms"/>')
        else:
            buf.append(ch)
    if buf:
        pieces.append(" ".join(lazy_pinyin("".join(buf), style=Style.TONE3, neutral_tone_with_five=True)))
    return " ".join(pieces)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if shutil.which("espeak-ng") is None:
        print(json.dumps({"error": "speech_tool_missing", "needed_for": "synthetic_fixture_only"}))
        return 3
    spoken = to_pinyin(args.text)
    proc = subprocess.run(
        ["espeak-ng", "-m", "-v", "cmn-latn-pinyin", "-s", "118", "-w", args.out, spoken],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-1000:])
        return proc.returncode or 1
    print(json.dumps({
        "wav": args.out,
        "synthetic_test": True,
        "human_speech": False,
        "listened": False,
        "pinyin": spoken,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if sys.platform == "win32" and not sys.flags.utf8_mode:  # Windows reads, writes and prints in a legacy code page
        sys.exit(subprocess.call([sys.executable] + sys.argv, env=dict(os.environ, PYTHONUTF8="1")))
    sys.exit(main(sys.argv[1:]))
