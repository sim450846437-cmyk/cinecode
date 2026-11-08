# Local job adapter

This is a localhost queue for one preauthorized Quick-mode motion template, plus optional local tools. Motion video typesets locked text. Copy, photo face swap, person segmentation, and continuous-speech ASR run only when the operator has fetched the named files. Those weights are not in this repository.

The render path is the kit's own. The adapter creates a film folder with `scripts/init_film.py --quick`, overlays the checked-in film section, and runs that folder's `tools/make.py draft`. `make.py` calls `capture.mjs`, `master_audio.py`, and `qc.py`. A request never becomes shell text and is never written into `film.html`.

## What a caller can ask for

| id | status | what this adapter does |
|---|---|---|
| `motion_video` | user text, typeset | Renders `home_clean_tips_v1` at the draft size, 540×960, 18 s, 24 fps. Locked text is typeset. `script.mode generate` on this task stays blocked: typesetting is not AI writing. |
| `copywriting` | local GGUF when configured | llama.cpp plus Apache-2.0 Qwen2.5-0.5B-Instruct. Set `CINECODE_LLAMA_CLI` and `CINECODE_COPY_MODEL`. Otherwise the job is `blocked`. |
| `face_swap` | photo landmarks when configured | MediaPipe Face Landmarker and a triangle warp of two photographs. Set `CINECODE_FACE_MODEL`, `CINECODE_FACE_A`, `CINECODE_FACE_B`. A drawn face is not a result. |
| `background_replace` | person mask when configured | MediaPipe selfie segmenter on a short pan of a photograph. Not chromakey. Set `CINECODE_SEG_MODEL` and `CINECODE_FACE_A`. |
| `word_accurate_talking_head_edit` | Whisper word times | One Mandarin espeak-ng utterance, then faster-whisper word times, then a pause trim. Needs `espeak-ng` and `faster-whisper`. Meaning flags are not applied. |
| `one_click_replace` | unavailable | `replacement_target` must be null. |

`profile full` (1080×1920 through `make.py final`) is `blocked`. Final waits for an independent viewer and a user OK. This adapter does not forge those gates. A passing draft is the official half-size Quick draft, mastered by `make.py`, not a signed-off final.

CPU fallback is the kit's own: headless Chrome still renders when the GPU probe is software. It is slow. The template sets two capture workers.

## Contract

Bind is `127.0.0.1` only. One shared bearer token lives in `<root>/auth.token` (mode 0600). This is a single operator on one machine, not multi-tenant auth.

```bash
python3 scripts/job_service.py --root /path/to/job-store serve --port 8765
```

Keep the store outside the kit and outside `~/.cinecode`. The render child does not inherit credential-shaped environment variables, parent `LD_LIBRARY_PATH` / `LD_PRELOAD`, or `GIT_CONFIG_*` injections. Cinecode's home files for that child point at the job directory. The upstream guard is not treated as a sandbox.

`service/examples/motion_video.json` is a valid body. `POST /v1/jobs` returns 202, or 200 when the same idempotency key repeats the same body. The same key with a different body is 409. Unsupported task types are 422 and are not queued. Locked text is typeset. `script.mode generate` on the motion task, a missing local model file, or `profile full` is stored as `blocked` and is not rendered.

`GET /v1/jobs/{id}` returns the state. `POST /v1/jobs/{id}/cancel` is idempotent: a queued job becomes `cancelled`; a running job records the request and becomes `cancelled` after the worker stops; a finished job stays finished. `GET /v1/jobs/{id}/artifact` returns the registered MP4 only, from inside that job's directory. `GET /v1/jobs/{id}/logs` is a redacted tail.

States: `queued`, `rendering`, `validating`, `succeeded`, `blocked`, `failed`, `cancel_requested`, `cancelled`, `expired`. Progress has a stage name and `percent: null`. A render that `make.py` holds back stays `blocked` with `quality_gate` even if an MP4 was registered for inspection.

Timeout is `timeout_s` (1 to 1200) for the whole job. On resume, a dead worker is queued again and the remaining time is kept. `capture.mjs --video` does not resume a partial MP4; a resume that already has the delivered `*-draft.mp4` skips `make.py`, otherwise the deterministic template render starts over. That is not a replay of a paid model call. There is no paid call on this path.

## Still required for a long-running cross-bot service

A loopback trial does not deploy the adapter anywhere else. Weights are fetched on the host and are not packed. `profile full` still waits for an independent viewer and a user OK. Nothing here is a publish step.
