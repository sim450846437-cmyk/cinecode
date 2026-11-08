#!/usr/bin/env python3
"""Build a short spoken take with espeak-ng, measure each word, and trim pauses.

Word times are the measured durations of the individual synthesized wavs that
were concatenated. ffmpeg silencedetect is the VAD cross-check. This is not a
claimed listening session and not Whisper. If espeak-ng is absent, the command
exits 3 and prints speech_tool_missing.

Meaning-changing flags from footage_cut.py are written and not applied.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
FONT = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"


def run(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        sys.exit((proc.stderr or proc.stdout)[-2000:])
    return proc


def duration(path):
    proc = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(proc.stdout.strip())


def synth_word(text, path):
    espeak = shutil.which("espeak-ng")
    if not espeak:
        print(json.dumps({"error": "speech_tool_missing", "need": "espeak-ng"}))
        sys.exit(3)
    run([espeak, "-v", "en", "-s", "150", "-w", str(path), text])
    return duration(path)


def concat(pieces, dest):
    """pieces: wav paths and silence seconds."""
    list_path = dest.with_suffix(".concat.txt")
    lines = []
    silence_i = 0
    for piece in pieces:
        if isinstance(piece, float):
            silence = dest.parent / f"silence-{silence_i}.wav"
            silence_i += 1
            run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                 "-t", f"{piece:.3f}", "-c:a", "pcm_s16le", str(silence)])
            lines.append(f"file '{silence.resolve().as_posix()}'")
        else:
            lines.append(f"file '{Path(piece).resolve().as_posix()}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(list_path),
         "-c:a", "pcm_s16le", str(dest)])


def srt(words, path):
    def stamp(t):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    rows = []
    for i, w in enumerate(words, 1):
        rows.append(f"{i}\n{stamp(w['start'])} --> {stamp(w['end'])}\n{w['word']}\n")
    path.write_text("\n".join(rows), encoding="utf-8")


def picture(audio, words, dest, label):
    draw = []
    font = FONT.replace(":", "\\:")
    for w in words:
        text = w["word"].replace(":", "\\:").replace("'", "")
        draw.append(
            f"drawtext=fontfile='{font}':text='{text}':fontsize=36:fontcolor=0x2a211c:"
            f"x=(w-text_w)/2:y=h*0.42:enable='between(t,{w['start']:.3f},{w['end']:.3f})'"
        )
    vf = ",".join(draw) if draw else "null"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0xf3eadf:s=540x960:r=24",
         "-i", str(audio), "-t", f"{duration(audio):.3f}", "-vf", vf, "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest)])


def silencedetect(path):
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "silencedetect=n=-35dB:d=0.5",
                           "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return [line.strip() for line in proc.stderr.splitlines() if "silence_" in line]


def edit(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not shutil.which("espeak-ng"):
        print(json.dumps({"error": "speech_tool_missing", "need": "espeak-ng"}))
        return 3
    # Two takes of the same sentence, a long pause between them, and a doubled word.
    plan = [("Wipe", 0.08), ("wipe", 0.08), ("the", 0.08), ("counter.", 0.9),
            ("Wipe", 0.08), ("the", 0.08), ("counter.", 0.0)]
    words, pieces, cursor = [], [], 0.0
    for i, (text, gap) in enumerate(plan):
        wav = out / f"word-{i}.wav"
        dur = synth_word(text, wav)
        words.append({"word": text, "start": round(cursor, 3), "end": round(cursor + dur, 3)})
        pieces.append(wav)
        cursor += dur
        if gap:
            pieces.append(gap)
            cursor += gap
    speech = out / "before.wav"
    concat(pieces, speech)
    measured = duration(speech)
    (out / "words.json").write_text(json.dumps({"words": words}, indent=1), encoding="utf-8")
    picture(speech, words, out / "before.mp4", "before")
    vad = silencedetect(speech)
    run([sys.executable, str(KIT / "scripts" / "footage_cut.py"), "cut", str(out / "words.json"),
         "--out", str(out / "edit"), "--source", str(out / "before.mp4"), "--duration", f"{measured:.3f}"])
    graph = out / "edit" / "filter.txt"
    after = out / "after.mp4"
    # ffmpeg 6 reads -filter_complex_script. ffmpeg 7 also accepts it.
    run(["ffmpeg", "-y", "-v", "error", "-i", str(out / "before.mp4"), "-filter_complex_script", str(graph),
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", str(after)])
    retimed = json.loads((out / "edit" / "words-retimed.json").read_text(encoding="utf-8"))
    srt(words, out / "before.srt")
    srt(retimed, out / "after.srt")
    cut = json.loads((out / "edit" / "cut-list.json").read_text(encoding="utf-8"))
    report = {
        "engine": "espeak-ng",
        "licence": "GPL-3.0-or-later",
        "timestamps": "measured duration of each synthesized word wav, then concatenation",
        "vad": vad,
        "flags": (out / "edit" / "flags.md").read_text(encoding="utf-8"),
        "source_duration": cut["source_duration"],
        "edited_duration": cut["edited_duration"],
        "keep": cut["keep"],
        "applied_meaning_flags": cut["applied"],
        "word_count_before": len(words),
        "word_count_after": len(retimed),
        "listening": "not heard; durations and silence were measured",
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not (cut["edited_duration"] < cut["source_duration"] - 0.2):
        sys.exit("pause trim did not shorten the take")
    if "silence_start" not in "\n".join(vad):
        sys.exit("VAD found no silence in the long pause")
    print(json.dumps({k: report[k] for k in ("source_duration", "edited_duration", "word_count_before", "word_count_after", "applied_meaning_flags")}))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    return edit(args.out)


if __name__ == "__main__":
    if sys.platform == "win32" and not sys.flags.utf8_mode:   # Windows reads, writes and prints in a legacy code page
        sys.exit(subprocess.call([sys.executable] + sys.argv, env=dict(__import__("os").environ, PYTHONUTF8="1")))
    sys.exit(main(sys.argv[1:]))
