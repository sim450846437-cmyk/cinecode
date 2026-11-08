# Local job adapter

This is a localhost queue for one preauthorized Quick-mode motion template, plus optional local tools. Motion video typesets locked text. Copy, photo face swap, person segmentation, and continuous-speech ASR run only when the operator has fetched the named files. Those weights are not in this repository.

The render path is the kit's own. The adapter creates a film folder with `scripts/init_film.py --quick`, overlays the checked-in film section, and runs that folder's `tools/make.py draft`. `make.py` calls `capture.mjs`, `master_audio.py`, and `qc.py`. A request never becomes shell text and is never written into `film.html`.

## What a caller can ask for

| id | status | what this adapter does |
|---|---|---|
| `motion_video` | themed template | `home_clean_tips_v1` is counter cleaning. `stationery_tidy_v1` is putting stationery away. A brief for the other theme is `blocked`. The pictures do not follow arbitrary copy. `script.mode generate` uses the local GGUF only when that file is configured. |
| `copywriting` | local GGUF when configured | llama.cpp plus an allowlisted Apache-2.0 Qwen GGUF. The hazard screen is not a complete safety proof. 0.5B prose is limited. |
| `face_swap` | candidate_unverified | Full head plus hair is not implemented. Old stills and 3-frame files are not a rerunnable video. INSwapper is inner-face only and is not cleared here. Wan2.2-Animate-14B is not downloaded or run. |
| `background_replace` | moving footage only | Needs `CINECODE_MOTION_VIDEO` plus the selfie segmenter. A pan of a still is not this task. |
| `word_accurate_talking_head_edit` | uploaded audio | Bind the upload with the JSON field `upload_id`. See the curl block below. Omitting it is `blocked` / `audio_required`. |
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

`GET /v1/jobs/{id}` returns the state. On a generate job that used the local GGUF, top-level `model_host` is `local_file` and `generation` is `local_gguf_then_typeset`, the same values as `artifact`. A job blocked because no model file is configured keeps `model_host` `unavailable`. `POST /v1/jobs/{id}/cancel` is idempotent. `GET /v1/jobs/{id}/artifact` returns the registered file. `GET /v1/jobs/{id}/logs` is a redacted tail.

Speech is upload, then a job whose body field is `upload_id`. The upload record stores the caller's bot id. Submit, the worker, a requeued run, and the derived download all require that same owner. A missing id, a foreign id, and an older record with no owner are the same 403, and no job is created. A random id is not permission. The operator token can read jobs; it cannot submit or download from another bot's upload. `audio_source` is `synthetic`, `declared_recording`, or omitted. Omitted is stored as `unknown`. The speech report field `synthetic_status` is `declared_synthetic`, `declared_not_synthetic`, or `unknown`. `human_speech_verified` stays false: a declaration is not a check that the voice is human. The placeholder in `service/examples/speech_job.json` is the shape, not a recording.

When `script.mode` is `locked`, the locked text is what the template draws and it must match that template. The brief is metadata: it is stored and not typeset, and it does not have to repeat the theme. A stationery brief with a cleaning lock on `home_clean_tips_v1` is accepted because the drawn lines are the cleaning lock. A stationery lock on that template is `template_topic_mismatch`. A locked line the picture cannot act, such as 更换, 边条, or 安装 on the cleaning template, is `template_cannot_show` and is not rendered. When `script.mode` is `generate`, the brief is the generation input and must match the template. A brief that asks to pour a cleaner back or to mix bleach is rejected before the model runs, and no MP4 is written. `constraints` may set `forbid_substances` and `allow_only` using the names 清洁剂, 白醋, 酒精, 漂白, 氨, 清水. The brief phrases 不用, 不使用, 不要用, 禁止用, and 仅用清水 become that same policy. Forbidding 清洁剂 also forbids the substitutes 白醋 and 酒精. A line that mentions a forbidden substance is blocked, including a line that only quotes the ban. An unknown negation or an unknown substance name is `constraint_needs_review` and is not treated as safe. The list is not a general safety proof. One generation is parsed into sentences; there is no second sample and no handwritten substitute. The gate file keeps `raw_stdout` apart from parsed `lines`. `drafts` is the parsed list, not the model text. A JSON array is accepted only when that raw text parses. `prose_quality_pass` stays false. On-screen lines advance with the scene and do not jump back. The stationery picture draws 铅笔, 橡皮, and 尺子. A line with none of the template's `can_show` words, or with 圆规, 剪刀, 更换, 边条, or 安装, is `template_cannot_show` and is not rendered.

```bash
TOKEN=$(cat /path/to/job-store/auth.token)
# 1. Upload the bytes. Content-Type is audio/wav, audio/mpeg, or video/mp4.
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: audio/wav" \
  --data-binary @recording.wav http://127.0.0.1:8765/v1/uploads
# 201 {"upload_id":"<16 hex chars>","bytes":365076,"kind":"wav"}
# 2. Submit. upload_id is required. Without it the job is blocked, code audio_required.
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"task_type":"word_accurate_talking_head_edit","policy_id":"preauthorized_motion_v1","timeout_s":180,"upload_id":"<upload_id from step 1>","speech_language":"zh","reference_text":"请把台面擦干净。然后再把水渍擦掉。","idempotency_key":"speech-upload-01"}' \
  http://127.0.0.1:8765/v1/jobs
# 3. Query
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/v1/jobs/<job_id>
# 4. Download
curl -sS -H "Authorization: Bearer $TOKEN" -o after.mp4 http://127.0.0.1:8765/v1/jobs/<job_id>/artifact
```

A high WER or CER against `reference_text` is `blocked` with `asr_quality_warning`. The file can still be downloaded. Meaning-changing cuts are not applied. This service does not listen to the audio.

States: `queued`, `rendering`, `validating`, `succeeded`, `blocked`, `failed`, `cancel_requested`, `cancelled`, `expired`. Progress has a stage name and `percent: null`. A render that `make.py` holds back stays `blocked` with `quality_gate` even if an MP4 was registered for inspection.

Timeout is `timeout_s` (1 to 1200) for the whole job. On resume, a dead worker is queued again and the remaining time is kept. `capture.mjs --video` does not resume a partial MP4; a resume that already has the delivered `*-draft.mp4` skips `make.py`, otherwise the deterministic template render starts over. That is not a replay of a paid model call. There is no paid call on this path.

## Still required for a long-running cross-bot service

A loopback trial does not deploy the adapter anywhere else. Weights are fetched on the host and are not packed. `profile full` still waits for an independent viewer and a user OK. Nothing here is a publish step.
