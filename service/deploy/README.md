# cinecode job handoff

This directory is the operator guide for the localhost job process. It is a package for a persistent host. The machine that built the archive is not that host, and a test run of this archive is not a 24-hour service.

## Intended host, not a measurement from the pack

These figures were supplied as the deployment target. `deploy/bin/probe-env` prints what the machine you are on actually has. Do not treat a match here as something the pack already verified on that host.

- Debian 13, x86_64
- Python 3.13.5, Node 24.22.1, FFmpeg 7.1.5, Chrome 156
- about 63 GB free
- PID 1 is tini
- `systemctl` is offline
- pm2 and supervisord were not verified there

## What has to already be on PATH

Python 3.9 or newer (3.13 on the intended host), Node 22 or newer, ffmpeg, ffprobe, and Chrome or Chromium. The draft template also expects the Apache-2.0 font file `DroidSansFallbackFull.ttf` at `/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf` (Debian package `fonts-droid-fallback`). The motion draft needs no pip package and no model weight.

Optional local routes, all fetched by the operator and none of them packed in the archive:

- Copy: an official llama.cpp `llama-cli` plus `Qwen2.5-0.5B-Instruct` Q4_K_M GGUF (Apache-2.0) from https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF . Set `CINECODE_LLAMA_CLI` and `CINECODE_COPY_MODEL`.
- Faces: MediaPipe Face Landmarker `face_landmarker.task` (Apache-2.0) from https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task . Set `CINECODE_FACE_MODEL`, plus two photographs in `CINECODE_FACE_A` and `CINECODE_FACE_B`. Use synthetic or otherwise licensed faces. InsightFace inswapper is not used.
- Background: MediaPipe selfie segmenter (Apache-2.0) from https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite . Set `CINECODE_SEG_MODEL`. Python packages: `mediapipe`, `opencv-python-headless`, `numpy`. `libegl1` is required by the MediaPipe binary.
- Speech: `espeak-ng` (GPL-3.0-or-later) and `faster-whisper` (MIT weights, downloaded on first use). The utterance is one Mandarin pinyin call, then word timestamps. A missing file leaves the job blocked.

Nothing in this package needs Docker or root. Do not copy it over an existing install. Unpack it into an empty directory.

## Start, stop, health

`job-supervise` stays in the foreground and starts `job_service.py` bound to `127.0.0.1` only. If that child exits and the stop file is absent, the supervisor starts it again after one second. That covers a crash while the supervisor is alive.

```sh
./service/deploy/job-supervise --root /var/lib/cinecode-jobs --port 8765
./service/deploy/job-health 8765
./service/deploy/job-stop --root /var/lib/cinecode-jobs
./service/deploy/probe-env
```

On a host whose PID 1 is tini, the durable command is `job-supervise` itself. tini will reap it; tini will not restart it after the process is gone unless whatever started the container starts that command again. `systemctl` is not used. A unit file is not installed. `nohup` of `job_service.py` alone does not restart a crashed process and does not come back after a reboot.

The next start calls resume: a job left in `rendering` whose pid is dead is queued again. A half-written `--video` file is not resumed frame by frame. A draft file that `make.py` already delivered is registered without another render. There is no paid call to replay.

## Bots

Tokens are created on the host and are not in this archive.

```sh
python3 scripts/job_service.py --root /var/lib/cinecode-jobs bots add bot-alpha
```

The token is printed once. Each bot sees only its own jobs. The operator token in `auth.token` sees every job. Two bots are not a multi-tenant product, and identity is only as durable as this root directory.

## Limits

One render runs at a time. Each bot may have two open jobs. A third is HTTP 429. `profile full` stays blocked: `make.py final` still waits for an independent viewer and a user OK, which this package does not forge.
