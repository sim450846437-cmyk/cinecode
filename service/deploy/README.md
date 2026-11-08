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

One measured host had about 3.2 GB available and no swap before a copy job. `probe-env` prints `MemAvailable` and swap on the machine you are on. The copy loader refuses to start when available memory is below twice the GGUF file size, so a 2 GB model is not assumed to fit in 3.2 GB. Heavy work is serial: one job at a time, llama.cpp uses one thread, and the draft render uses one worker. Do not run a second model beside it.

## Speech upload contract

The job field is `upload_id`. It is the `upload_id` string from `POST /v1/uploads`. A speech job without that field is stored as `blocked` with `audio_required`. The example body is `service/examples/speech_job.json`. Replace the placeholder id. Do not guess another field name.

```bash
TOKEN=$(cat /path/to/job-store/auth.token)
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: audio/wav" \
  --data-binary @recording.wav http://127.0.0.1:8765/v1/uploads
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"task_type":"word_accurate_talking_head_edit","policy_id":"preauthorized_motion_v1","timeout_s":180,"upload_id":"<upload_id>","speech_language":"zh","reference_text":"请把台面擦干净。然后再把水渍擦掉。","idempotency_key":"speech-upload-01"}' \
  http://127.0.0.1:8765/v1/jobs
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/v1/jobs/<job_id>
curl -sS -H "Authorization: Bearer $TOKEN" -o after.mp4 http://127.0.0.1:8765/v1/jobs/<job_id>/artifact
```

`home_clean_tips_v1` only draws cleaning text. `stationery_tidy_v1` only draws stationery text. When `script.mode` is `locked`, those locked lines are the picture text and must match the template. The brief is metadata and is not required to match. When `script.mode` is `generate`, the brief is the input and must match. On-screen lines are measured and wrapped. A generate success reports top-level `model_host` `local_file`. A missing model stays `unavailable`.

`audio_source` on a speech job is `synthetic`, `declared_recording`, or omitted. Omitted is stored as `unknown`. The service does not turn an upload into a human-voice claim.

Optional installs are pinned in `requirements-local.txt`. System package `libegl1` is required before MediaPipe will load. Weights are not in the archive. Fetch them yourself and check the hashes:

- llama.cpp `llama-cli` build 12195 for this CPU. A build verified here has SHA256 `d6cc36e5fdc2eedd6e052dc7eb1e29d21065331e37e31f57ab2ca4720635dba2`. Set `CINECODE_LLAMA_CLI`.
- Qwen2.5-0.5B-Instruct Q4_K_M, Apache-2.0, https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF file `qwen2.5-0.5b-instruct-q4_k_m.gguf`, SHA256 `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`. This is the size that fits the 3.2 GB measurement. Set `CINECODE_COPY_MODEL`.
- The 1.5B and 3B official GGUF names are on the same allowlist, Apache-2.0, from the matching Qwen Hugging Face repos. The 3B Q4_K_M file verified here is SHA256 `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`. Leave it unset on a 3.2 GB host.
- Face landmarker, Apache-2.0, https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task SHA256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`. Set `CINECODE_FACE_MODEL`.
- Selfie segmenter, Apache-2.0, https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite SHA256 `191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290a4e4038226658b`. Set `CINECODE_SEG_MODEL`.
- faster-whisper base weights, MIT, https://huggingface.co/Systran/faster-whisper-base snapshot `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`, `model.bin` SHA256 `d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9`. The speech job does not need espeak-ng. Upload wav, mp3, or mp4 first.

Synthetic portraits and synthetic speech samples are in the review zip, with their licence notes. Point `CINECODE_FACE_A` and `CINECODE_FACE_B` at those portrait files. They are not real people. The speech samples are synthetic test audio, not a human-speech acceptance.

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
