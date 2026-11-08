#!/usr/bin/env python3
"""Word times for an uploaded recording, then a pause trim.

ffmpeg decodes the file. faster-whisper (MIT weights) supplies the word
times. espeak-ng is not used. Meaning flags are listed and not applied.
This process does not listen, and it does not decide that a voice is human.
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
FONT = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"


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
    parser.add_argument("--audio", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--audio-source", choices=("synthetic", "declared_recording", "unknown"), default="unknown")
    parser.add_argument("--reference", default="")
    parser.add_argument("--language", choices=("en", "zh"), default="")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source = Path(args.audio)
    if not source.is_file():
        print(json.dumps({"error": "audio_missing"}))
        return 3
    if shutil.which("ffmpeg") is None:
        print(json.dumps({"error": "ffmpeg_missing"}))
        return 3
    speech = out / "before.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-ac", "1", "-ar", "16000", str(speech)])
    if importlib.util.find_spec("faster_whisper") is None:
        print(json.dumps({"error": "asr_runtime_missing"}))
        return 3
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(speech), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    from faster_whisper import WhisperModel
    model_name = os.environ.get("CINECODE_ASR_MODEL", "base")
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=1)
    segments, info = model.transcribe(
        audio, language=args.language or None, word_timestamps=True, vad_filter=True,
        condition_on_previous_text=False)
    words = []
    for seg in segments:
        for w in seg.words or []:
            token = (w.word or "").strip()
            if token and w.end > w.start:
                words.append({"word": token, "start": round(w.start, 3), "end": round(w.end, 3)})
    # Join with spaces. Stripping each token removes Whisper's boundary, and a spaceless string scores WER 1.
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
        "speech": "uploaded file decoded by ffmpeg; espeak-ng is not used",
        "asr": f"faster-whisper {model_name}, MIT, word_timestamps, cpu int8, one thread",
        "asr_weights": "https://huggingface.co/Systran/faster-whisper-base",
        "audio_source": args.audio_source,
        "synthetic_status": synthetic_status(args.audio_source),
        "human_speech_verified": False,
        "heard_by_asr": " ".join(w["word"] for w in words),
        "word_count": len(words),
        "source_duration": cut["source_duration"],
        "edited_duration": cut["edited_duration"],
        "keep": cut["keep"],
        "applied_meaning_flags": cut["applied"],
        "reference": args.reference,
        "wer": None,
        "cer": None,
        "quality_warning": False,
        "acceptance_pass": False,
        "listening": False,
    }
    if args.reference.strip():
        report["wer"] = round(wer(args.reference, report["heard_by_asr"]), 4)
        report["cer"] = round(cer(args.reference, report["heard_by_asr"]), 4)
        report["quality_warning"] = report["wer"] > 0.5 or report["cer"] > 0.4
    elif letter_ratio(report["heard_by_asr"]) < 0.4:
        report["quality_warning"] = True
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("heard_by_asr", "wer", "cer", "quality_warning", "source_duration", "edited_duration", "applied_meaning_flags")}, ensure_ascii=False))
    return 4 if report["quality_warning"] else 0


def _norm_text(text):
    return "".join(ch.lower() for ch in text if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"))


def _words(text):
    return [tok for tok in "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in text).split() if tok]


def _edit(a, b):
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins, delete, sub = prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def wer(ref, hyp):
    left, right = _words(ref), _words(hyp)
    return _edit(left, right) / max(len(left), 1)


def cer(ref, hyp):
    left, right = _norm_text(ref), _norm_text(hyp)
    return _edit(list(left), list(right)) / max(len(left), 1)


def synthetic_status(source):
    return {
        "synthetic": "declared_synthetic",
        "declared_recording": "declared_not_synthetic",
        "unknown": "unknown",
    }[source]


def letter_ratio(text):
    if not text:
        return 0.0
    good = sum(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text)
    return good / len(text)


if __name__ == "__main__":
    if sys.platform == "win32" and not sys.flags.utf8_mode:  # Windows reads, writes and prints in a legacy code page
        sys.exit(subprocess.call([sys.executable] + sys.argv, env=dict(os.environ, PYTHONUTF8="1")))
    sys.exit(main(sys.argv[1:]))
