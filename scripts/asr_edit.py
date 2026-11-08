#!/usr/bin/env python3
"""Continuous Chinese speech, then Whisper word times, then a pause trim.

espeak-ng speaks the whole sentence in one call. Timestamps come from
faster-whisper (MIT weights), not from the synthesizer's per-word files.
Meaning-changing flags are listed and not applied.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
FONT = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
SENTENCE = "请把台面擦干净。然后再把水渍擦掉。"
SPOKEN = 'qing3 ba3 tai2 mian4 ca1 gan1 jing4. <break time="1000ms"/> ran2 hou4 zai4 ba3 shui3 zi4 ca1 diao4.'


def run(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        sys.exit((proc.stderr or proc.stdout)[-2000:])
    return proc


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).stdout.strip())


def srt(words, path):
    def stamp(t):
        ms = int(round(max(0, t) * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    path.write_text("\n".join(
        f"{i}\n{stamp(w['start'])} --> {stamp(max(w['end'], w['start'] + 0.05))}\n{w['word']}\n"
        for i, w in enumerate(words, 1)
    ), encoding="utf-8")


def picture(audio, words, dest):
    font = FONT.replace(":", "\\:")
    draws = []
    for w in words[:12]:
        text = w["word"].replace(":", "\\:").replace("'", "").replace("%", "")
        if not text:
            continue
        draws.append(
            "drawtext=fontfile='%s':text='%s':fontsize=42:fontcolor=0x2a211c:"
            "x=(w-text_w)/2:y=h*0.4:enable='between(t,%.3f,%.3f)'" % (font, text, w["start"], max(w["end"], w["start"] + 0.05))
        )
    vf = ",".join(draws) if draws else "null"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0xf3eadf:s=540x960:r=24",
         "-i", str(audio), "-t", f"{duration(audio):.3f}", "-vf", vf, "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest)])


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not shutil.which("espeak-ng"):
        print(json.dumps({"error": "speech_tool_missing"}))
        return 3
    speech = out / "before.wav"
    # One continuous utterance. The break is inside the speech, not a per-word concat.
    run(["espeak-ng", "-m", "-v", "cmn-latn-pinyin", "-s", "118", "-w", str(speech), SPOKEN])
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(speech), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    from faster_whisper import WhisperModel
    model_name = os.environ.get("CINECODE_ASR_MODEL", "base")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        audio, language="zh", word_timestamps=True, vad_filter=True,
        initial_prompt=SENTENCE, condition_on_previous_text=False)
    words = []
    for seg in segments:
        for w in seg.words or []:
            token = (w.word or "").strip()
            if token and w.end > w.start:
                words.append({"word": token, "start": round(w.start, 3), "end": round(w.end, 3)})
    (out / "words.json").write_text(json.dumps({"words": words, "language": info.language}, ensure_ascii=False, indent=1), encoding="utf-8")
    if len(words) < 2:
        print(json.dumps({"error": "asr_empty", "words": words}, ensure_ascii=False))
        return 1
    picture(speech, words, out / "before.mp4")
    dur = duration(speech)
    run([sys.executable, str(KIT / "scripts" / "footage_cut.py"), "cut", str(out / "words.json"),
         "--out", str(out / "edit"), "--source", str(out / "before.mp4"), "--duration", f"{dur:.3f}"])
    run(["ffmpeg", "-y", "-v", "error", "-i", str(out / "before.mp4"),
         "-filter_complex_script", str(out / "edit" / "filter.txt"),
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-movflags", "+faststart", str(out / "after.mp4")])
    retimed = json.loads((out / "edit" / "words-retimed.json").read_text(encoding="utf-8"))
    srt(words, out / "before.srt")
    srt(retimed, out / "after.srt")
    cut = json.loads((out / "edit" / "cut-list.json").read_text(encoding="utf-8"))
    report = {
        "speech": "espeak-ng cmn-latn-pinyin, one continuous call, SSML break, not per-word wavs",
        "spoken_pinyin": SPOKEN,
        "asr": f"faster-whisper {model_name}, MIT, word_timestamps, cpu int8",
        "intended": SENTENCE,
        "heard_by_asr": "".join(w["word"] for w in words),
        "word_count": len(words),
        "source_duration": cut["source_duration"],
        "edited_duration": cut["edited_duration"],
        "keep": cut["keep"],
        "applied_meaning_flags": cut["applied"],
        "listening": False,
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("heard_by_asr", "source_duration", "edited_duration", "word_count", "applied_meaning_flags")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if sys.platform == "win32" and not sys.flags.utf8_mode:  # Windows reads, writes and prints in a legacy code page
        sys.exit(subprocess.call([sys.executable] + sys.argv, env=dict(os.environ, PYTHONUTF8="1")))
    sys.exit(main(sys.argv[1:]))
