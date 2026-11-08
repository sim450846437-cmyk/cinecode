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

Python 3.9 or newer (3.13 on the intended host), Node 22 or newer, ffmpeg, ffprobe, and Chrome or Chromium. The draft template also expects the Apache-2.0 font file `DroidSansFallbackFull.ttf` at `/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf` (Debian package `fonts-droid-fallback`). The speech job needs `espeak-ng` (GPL-3.0-or-later). No pip packages and no model weights are required for the motion draft. Face swap of a photograph stays blocked because no landmark weights are included.

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
