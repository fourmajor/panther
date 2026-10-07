# Procedural session companions

Every completed session should have two editions: a procedural film and a model-generated
film. They share the ordered scene/storyboard source, not each other's rendered pixels.
Neither replaces the original recording, novel, storyboard or previous movie editions.
The model branch still waits for owner approval of its exact storyboard and retains the
$10 session ceiling, no paid retries, no automatic credit purchases or model fallbacks.

The procedural branch runs on the owner's awake laptop. Fresh subscription-backed Codex
turns translate source direction into a bounded JSON geometry/animation description.
Only Panther's trusted renderer executes: no asset-supplied code, downloaded add-ons,
image textures, video models, speech generation or voice cloning. Blender builds and
fresh-opens editable scenes, renders actual animation, and FFmpeg assembles all shots.
An original mathematical PCM score is not dialogue or professional narrated performance.
The edition's explicit miniature-diorama style does not change the game's visual-style
setting or assert photorealistic character likeness.

## Render an existing movie's companion

Download the exact immutable `VideoProductionResult` through authenticated Panther reads.
Its embedded manifest determines the shared ordered scenes, selected shot durations,
direction and cast. The input file's checksum and length must match `--source-key`.

```sh
panther videos render-procedural PRIVATE_PRODUCTION.json \
  --source-key games/GAME/assets/PRODUCTION/original/production.json \
  --work-dir PRIVATE_DIRECTORY --publish
```

No generic still-pan slideshow or incomplete scene subset is a completed procedural film.
The source/compiler contract rejects foreign cast, duplicate IDs, unsupported scripts,
out-of-range transforms, reordered keys and missing/unowned packet shots. Source hashes
identify retained render revisions; earlier failed candidates remain untouched. Each
rendered shot receives an independent frame-sampled visual review. Failed/uncertain
reviews block publication and preserve evidence rather than silently retrying indefinitely.
Technical decode, length/checksum and browser HTTP range checks are separate gates.
Successful outputs use ordinary immutable asset storage/version records and exact Inputs.
The detailed renderer outputs 1920×1080 at 24 fps, using procedural material surfaces,
connected miniature actors, explicit hair/hat/weapon features and local lighting. More
geometry or pixels is not a substitute for faithful action and composition. Inspect
representative start/middle/end frames before a full detail render and preserve each
refinement's inputs/evidence. Per-shot receipts record actual render/encoding/technical
verification wall time; direction and visual review are excluded and reported separately.
Do not report a benchmark extrapolation as measured full-film completion time.

## Automatic owned-compute worker

```sh
panther videos procedural-worker --work-dir PRIVATE_DIRECTORY --completed-after UTC_UNIX_TIMESTAMP --once
```

The durable queue is completed, canonical session generation packets with a completed
video-preflight stage. Discovery uses bounded per-game API pages, never an S3 scan or
recording quiet period. No branch runs on an incomplete recording. A missing laptop,
subscription login or Blender delays processing; it does not invent successful footage.
The explicit job-creation activation boundary prevents unexpectedly rendering historical
experiments; the installer pins its installation time. Backfill desired historical films
explicitly with `render-procedural`. Prompt-only projects are not completed sessions.
Published and blocked source revisions are not replayed. Subscription deferrals retain
checkpoints. The worker cannot submit model videos or approve a storyboard.

After local checks and a reviewed merged PR, install the separate pinned worker:

```sh
.venv/bin/python ops/editorial-worker/install.py --repo "$PWD" --worker procedural --start
```

Its LaunchAgent is `place.panther.procedural-worker`, waking every five minutes while
the laptop is awake. Logs, compiler responses, frames, editable Blender scenes, reviews,
private inputs and publication receipts stay outside Git. No hosted compute is added.
The installed release is a reviewed commit, not a changing source checkout. Stop it with
`launchctl bootout gui/$(id -u)/place.panther.procedural-worker` before an explicit upgrade.

The current implementation covers cloud canonical editorial session packets and explicit
completed movie manifests. It does not enqueue paid generation after approval or migrate
the separate local-development episode-render queue. Model-film planning remains the
existing session/editorial branch; automatic paid execution is not implemented by this worker.
