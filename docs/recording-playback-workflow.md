# Completed recording set → continuous listening copy

Chunks are a recovery/storage detail, not interruptions in browser playback. Audio uses one
MP3 listening file and one seekable timeline. Part buttons seek within that file. Lossless
FLAC chunks remain unchanged for transcription and future processing; the listening copy is lossy.

## Completion contract

Each new chunk carries `extra.chunkSetId` and `extra.recordingId`, equal to its recording asset ID.
The final immutable Recording manifest declares ordered filenames, sizes, SHA-256 and timeline.
`recording upload` or finalized `recording sync` uploads the sources, then explicitly calls
`POST /recording-sets/complete` with `status: COMPLETE`, game ID, recording key and manifest hash.
No assembly happens inside upload/sync. No timer, S3 upload event or intermediate checkpoint
infers completeness. Failed uploads leave the set uncommitted; retry keeps local originals.

The API verifies every referenced object exists with its exact checksum and size before writing
a version-1 `RecordingChunkSet`. Its membership tags legacy objects without modifying them. Set
membership is immutable; processing status and lease fields are separate from `setStatus: COMPLETE`.
`captureStatus: interrupted` can be a complete **uploaded** recovered set; this does not assert
every word was captured. Capture reports and original warnings are retained. Changed inputs require
a new immutable recording identity, never rewriting a committed set.

The content-addressed job ID includes the recording key, manifest checksum and workflow version.
Repeating completion returns the same job, including after a lost response. The table's stream is
a durable outbox: only the completed-set insertion starts a named Standard Step Functions execution.
Duplicate deliveries don't create duplicate executions. Completion callbacks also use the outbox;
callback tokens stay in AWS, never in public API results or laptop logs.

## Workflow and cost

The separate playback state machine queues `AssembleAndVerifyOnLaptop` and waits for its callback.
The owner laptop claims work with Panther authentication, a ten-minute lease and one-minute
heartbeats. It downloads/checksum-verifies the pinned cloud inputs, decodes every FLAC in order,
streams the samples into **one persistent encoder**, verifies sample counts and output format/duration,
and publishes MP3 plus typed `RecordingPlayback` provenance through Panther. The broker checks hashes
and exact lineage before accepting DONE. Refresh Audio to discover the new listening copy; browsing
starts no work. Missing playback shows a preparation notice, never a gapped chunk-playlist fallback.

The output preserves original sample rate: supported rates are 32,000, 44,100 and 48,000 Hz,
with mono 128 kbps or stereo 192 kbps MP3 and MP3 seek/duration indexing. Mismatched formats, changed
sources and incorrect sample counts fail visibly. No resampling, speech synthesis, silence padding,
denoising or transcript changes occur. Assembly cannot recover missing captured audio.

Provenance includes source manifest/parts, exact `sourceKeys`, sample count, decoded PCM hash, part
offsets, codec, size, output hash and capture-warning text. The MP3's compact `sourceKeys` points to
that JSON, which retains the full input list. Both files use immutable
`playback-v1-MANIFEST_HASH_PREFIX` names under the existing recording asset identity.

CDK manages a retained on-demand DynamoDB table, short-lived brokers and Standard Step Functions
in `us-west-2`. No EC2/NAT, hosted runner/encoding, AI or paid inference. Waiting doesn't poll in AWS.
The local worker polls once a minute when enabled, incurring small request costs—not literal zero.
A sleeping/offline laptop delays assembly, not chunk backup.

## Commands and owner worker

```sh
panther recording upload RECORDING_DIR --no-editorial
panther recording sync RECORDING_DIR
panther recording playback jobs
panther recording playback jobs --job-id JOB_ID
panther recording playback worker --work-dir /private/path/playback-jobs --once
```

Upload/sync complete the set automatically after uploads. For existing uploaded sources, use
`recording playback complete-set --game GAME --recording-key KEY --manifest-sha256 HEX`.
The server independently verifies the declaration. `playback-preview RECORDING_DIR` is local-only
diagnostics and deliberately has no publication option.

Install from clean, merged `main` matching fetched `origin/main`:

```sh
.venv/bin/python ops/playback-worker/install.py --repo "$PWD" --start
```

This snapshots trusted source and a non-editable CLI in the private Panther playback-worker directory.
LaunchAgent `place.panther.playback-worker` runs one job every minute while logged in/awake.
Native ffmpeg/ffprobe and Panther sign-in are required. It never opens a microphone, needs AWS
credentials or reads a recording test script. Logs/downloads/outputs stay outside Git. Omitting
`--start` installs without activation. Inspect with `launchctl print
gui/$(id -u)/place.panther.playback-worker`; stop with `launchctl bootout
gui/$(id -u)/place.panther.playback-worker`. Upgrades refuse to overwrite an existing service;
preserve the old plist/release and explicitly stop it before installing reviewed new code.

## Failure boundaries

Initial limits: 1,000 parts, 200 KB Recording manifest, 300 KB completed-set record and Panther's
existing 1 GiB per uploaded file. Limits stop with originals retained, never silently truncate.
No mixed-format joining or multipart upload is added. The laptop processes one job at a time.

Expired leases can be reclaimed. Verified local files are reused; remote uploads reconcile exact
hashes. Three abandoned attempts fail the job. A lost lease blocks the old worker's completion.
Immutable outputs can remain after interrupted publication; they are never overwritten. Corrupt
derivatives or an output left without its local manifest require inspection, not automatic deletion.
Waiting expires after 30 days. DynamoDB stream records have a 24-hour delivery window; persistent
outbox failures require operator recovery. Failed jobs stay inspectable, not silently restarted
under new identities. Originals remain downloadable when playback is not yet ready.

## Verification

Tests cover completeness, missing/changed chunks, duplicate commits/delivery, authentication,
leases, output lineage and sample-preserving assembly. Self-hosted Docker browser tests decode
a synthetic continuous MP3 fixture, cross a part boundary without changing the media URL, seek,
recover expired links and stop on navigation. The committed MP3 is a generated 1.2-second 440 Hz
tone, not game audio.

The initial AAC candidate failed actual Chromium playback in the isolated runner. MP3 was selected
instead and tested without substituting a different codec fixture. Chromium documents MP3 support
separately from Chrome-only AAC: [codec support](https://www.chromium.org/audio-video/).
