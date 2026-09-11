# Local recording and player-attributed transcripts

After upload, the [completed chunk-set workflow](recording-playback-workflow.md) produces one
continuous browser listening file on the owner's laptop. Chunk uploads alone never trigger it.
Lossless FLAC originals remain the inputs for transcription, not the lossy listening copy.

Recording and recognition use the CLI. Capture works
offline. Whisper.cpp and pyannote Community-1 run locally; no paid inference or audio uploads to
model providers. Audio backup uses `--sync` during capture or `recording sync` afterward.
Transcription now publishes the completed raw transcript and triggers the
[editorial workflows](editorial-workflows.md) by default; use `--local-only` to defer publication.
The web app browses
uploaded files; it does not yet offer transcript editing or playback synchronized with speakers.

## Storage and identity

- Preserve captured audio as lossless FLAC at the input sample rate and channel count, in ordered
  30-second parts by default. The recording manifest records exact checksums, lengths, format,
  and offsets from decoded sample counts, not potentially incomplete FLAC duration headers.
- Capture uses native PortAudio/Core Audio, not FFmpeg's AVFoundation input. A preallocated,
  bounded native queue separates the real-time microphone callback from disk I/O; Python and
  lossless encoding never run on that callback. Overflow, underflow, timestamp discontinuity,
  queue exhaustion, device stalls and write failures stop with an explicit error, retaining
  the sound already captured. Nothing pads missing sound or silently switches microphones.
- Capture encodes 24-bit integer PCM. This is not a bit-perfect archive of hypothetical floating
  point or 32-bit source input. The initial USB microphone test is ordinary integer PCM speech.
  Active capture writes PCM WAV chunks under `capture-pcm/`; each closed chunk is independently
  encoded to FLAC with `flac --verify` before checkpointing/upload. This avoids shared FLAC-encoder
  STREAMINFO/checksum problems across segments. Local PCM intermediates are retained, so allow
  disk space for both PCM and FLAC; only verified FLAC is uploaded as the archival audio.
- Imported integer PCM WAV is encoded with `flac --verify`; the supplied file is never deleted.
  WAV can still matter for special metadata, floating point recordings, and interoperability.
  Do not pretend a lossy recording becomes lossless by converting its format.
- Game, Player, Character, and GameMembership are distinct types. Session IDs associate recordings
  and assets; a separate session-management API is not implemented yet.
- Transcripts identify players. Character voice and table chatter are later annotations; neither
  changes the player's identity nor removes utterances. Generated transcripts remain unreviewed.
- Recording, speaker runs, and transcript revisions are immutable local artifacts. A new run keeps
  the old one and records source hashes and model provenance. Actual files, rosters, and maps stay
  outside Git, normally under `~/Library/Application Support/Panther/recordings`.

## Setup on the owner's Mac

Install PortAudio, pkg-config, FFmpeg, FLAC, and whisper.cpp using Homebrew, plus Apple's command-line
developer tools (for `clang`). Panther compiles its bundled C recorder once into a source-hash-named
private cache under `~/Library/Application Support/Panther/audio-capture`. Device discovery and
capture both use exact Core Audio input names; ambiguous/missing names fail without a default fallback.
Compilation does not open the microphone. No Python audio package or cloud service is required.
Supply a real local Whisper model to
`--model`; test-weight placeholders are not transcription models. The small multilingual model
is a starting point, not a guarantee of accuracy for fictional names or overlapping speech.

Community-1 requires one-time acceptance of the publisher's Hugging Face conditions at
<https://huggingface.co/pyannote/speaker-diarization-community-1>. Create a read-only token in
Hugging Face settings. Do not send it to an agent in chat or put it in command arguments.

```sh
python3.13 -m venv "$HOME/Library/Application Support/Panther/audio-runtime"
"$HOME/Library/Application Support/Panther/audio-runtime/bin/python" -m pip install -r ops/audio/requirements.txt
"$HOME/Library/Application Support/Panther/audio-runtime/bin/python" ops/audio/download-speaker-model.py
```

The last command uses hidden terminal input, downloads model files outside Git, and does not save
the token. Subsequent speaker processing loads the local model in Hugging Face offline mode with
pyannote and Hugging Face telemetry disabled. Models are executable-trust dependencies: download
only the reviewed publisher's model. CPU processing is currently used and may be slow. Whole-session
clustering keeps speaker labels consistent across recording parts, but requires RAM proportional
to recording length (plus model working memory). A three-hour 16 kHz float waveform is about 660 MiB.

## Solo test

Discover the exact microphone name with `panther recording devices`. Get agreement from the person
being recorded before starting. Keep the laptop awake and plugged in. Capture is a foreground
process; keep its terminal open. Ctrl+C finalizes the recording.

```sh
panther recording start --game GAME_ID --session SESSION_ID --device 'EXACT MICROPHONE NAME' --sync
panther recording transcribe RECORDING_DIR --model /private/path/ggml-small.bin --sole-player PLAYER_ID --blind
panther recording audit RECORDING_DIR
```

`--sole-player` is the user's declaration, not speaker recognition. Only use it if that person is
the only speaker throughout. Read the transcript and listen to the original before calling it
accurate. Recording device enumeration and public-audio smoke tests do not validate real microphone
capture or game-night attribution. Capture logs remain private; check for dropped input or errors.
The old TONOR test reproduced missing input buffers in FFmpeg's macOS capture path; the native
replacement avoids that path. See the [capture investigation](audio-capture-investigation.md).
An audit warning is not repaired audio. New capture health reports retain callback continuity,
sample counts, queue high-water mark and explicit error codes; they accompany final cloud backups.
`recording recover` validates intact parts after an interruption, preserving a corrupt final part
outside the recovered manifest with an explicit report. It does not repair that tail or establish
that no sound was missed. Corruption of an already-checkpointed part is a hard error. No source
file is automatically deleted. A controller-pipe watchdog closes the native recorder if its controller dies;
capture/recovery locks also remain held by the writer until it exits.

## Crash resilience and background sync

Audio streams to the local filesystem continuously. `--chunk-seconds` accepts 10–600 seconds,
default 30. Closed PCM chunks are independently FLAC-encoded, decoded/validated, flushed with
`fsync` (plus macOS `F_FULLFSYNC`),
and described by atomically published immutable JSON checkpoints. A growing filename or stable
file size is not treated as proof of completion: only closed entries in the capture journal qualify.
Native active WAV headers are updated as samples arrive, and files are durably flushed roughly
once a second and at chunk boundaries. The native callback never waits for those writes. Its queue
holds 128 buffers (up to 8,192 frames each; approximately 3 MiB per channel). A full queue is an error,
not permission to discard unreported sound. A forced kill can still leave an incomplete tail.

`--sync` starts a separate local uploader, checking about every 30 seconds. It uploads only
completed audio and checkpoints through Panther's existing authenticated, checksum-protected,
no-overwrite API. A slow connection, expired login, or upload failure does not block capture.
Retries continue while recording. Durable upload receipts avoid repeating confirmed uploads;
uncertain attempts are reconciled with the remote object before a retry. Only an explicit final
manifest means the full recoverable recording has been synced. Intermediate checkpoints are not
a claim that the session is complete.

After recording, an in-progress upload can finish independently. Failed uploads remain queued
locally; there is no always-on daemon or automatic retry after the uploader exits. Resume with:

```sh
panther recording sync RECORDING_DIR
```

This also recovers intact stopped captures if necessary. It never deletes local audio. Inspect
`sync-status.json` for the last result (`complete: true`, no error), or rerun the command and require
success. Do not equate “recording saved” with “cloud backup complete.” Without `--sync`, capture
stays local. No AWS administrative login, additional cloud service, or always-on compute is needed.

A crash can still lose the active chunk (roughly 30 seconds by default, plus buffering); cloud
backup can lag by an additional polling interval and upload time, or indefinitely while offline.
Power loss, storage failure, disk-full conditions, and a sleeping laptop preclude a zero-loss
guarantee. Keep the laptop awake and plugged in, and check available disk space before a long session.

## Blind transcription tests

Build the reviewed CPU-only image once on the local Docker engine:

```sh
bash ops/audio/build-transcriber.sh
```

Use `recording transcribe ... --blind` for a held-out reading test. It joins the verified FLAC parts
into an audio-only 16 kHz working WAV, removing imported metadata, then runs the pinned local
Whisper image by its immutable image ID with networking disabled and a read-only root filesystem.
Only that WAV, the model file, and a new empty output directory are mounted. The recording folder,
roster, reference script, chat history, host home directory, Docker socket, and credentials are not
mounted or supplied as model prompts. Roster names label the output on the host after recognition;
they do not prime the speech model. `blind-inputs.json` records the input/model hashes and isolation
mode. There is no native or cloud fallback if the isolated run fails.

Keep reading scripts outside the recording folder and out of uploads/Git. Freeze the raw model
output and versioned transcript before opening the script for comparison. Agents must not use
remembered script wording to write or correct that first transcript. A controlled comparison after
creation is allowed, but any corrected transcript must be a separate version. This prevents test
answer leakage into the recognizer; Docker is not a security boundary against the laptop owner
or a compromised Docker daemon. The blind mode uses local CPU compute and may be slower than
native Metal. Normal transcription without `--blind` still uses native Whisper and is not an
isolated holdout test.

Whisper implementation/build reference: <https://github.com/ggml-org/whisper.cpp/tree/v1.8.3>.

`recording import FILE.wav --game GAME_ID --session SESSION_ID` imports existing audio without
deleting it. A saved `panther game show GAME_ID` response can be passed as `--roster` for offline
transcription. Otherwise the command obtains the current roster through Panther authentication.

## Live transcript preview

While recording runs in its existing terminal, open a **second terminal**:

```sh
panther recording live RECORDING_DIR
```

This attaches without opening another microphone or restarting capture. It reads only completed,
checksum-verified FLAC checkpoints, never the active WAV or uncheckpointed files. The default
starts with the latest completed chunk so a long session does not impose an initial backlog.
Use `--from-start` to create a separate preview that catches up from the beginning. `--once`
processes at most one newly available chunk for diagnostics; subsequent invocations resume.
To join current audio while retaining an older preview's backlog, choose a new
`--preview-name NAME`. Reuse that name to resume it. This never skips or alters source audio.

It defaults to the existing local weights at `~/.cache/whisper.cpp/ggml-small.bin`; specify
`--model /private/path/WEIGHTS.bin` when installed elsewhere. It never downloads models, uses a paid
service or sends audio to an inference provider. Web publishing uses Panther login, not AWS login;
`--local-only` disables all network publishing, and `--once` is always local-only. Decoding and local Whisper run at
reduced priority, with two CPU threads, GPU disabled and bounded subprocess timeouts. A slow preview
queues work and reports lag; it cannot signal, stop, recover or finalize the independent recorder.
Resource contention is still possible on a busy laptop; stop the preview if capture health degrades.
The preview refuses new inference when less than 1 GiB disk space remains. This is a buffer, not a
guarantee against a full disk—recording itself continues to consume space.

Text is **provisional, not a raw or corrected transcript**, with unknown speakers and original
recording-relative timestamps. Chunk boundaries can split sentences and recognition may hallucinate,
especially in noise/silence. No speech recognized does not prove that the microphone heard nothing.
Whisper can overshoot a chunk's end. For this preview only, end-time overruns of at most two seconds
are clipped to the source boundary and marked `~` (approximate timing); larger/invalid timestamps
stop the preview. Exact original recognizer output is retained, and final-transcript validation is unchanged.
There is no roster prompting, character substitution, speaker guessing, automatic editorial trigger,
or asset upload. After capture, run the ordinary whole-recording transcription and player attribution;
do not use the preview as factual context or as a substitute for a held-out `--blind` transcript.

Each preview saves immutable recognizer output and per-chunk JSON with exact audio/model hashes,
source references, local-inference metadata and provisional/excluded-context status. Partial failed
attempts are retained. A separately rebuildable `preview.txt` presents the growing text, while
`status.json` reports pending work/errors. Both live under the recording's private `live-preview/`
directory; none of these files are picked up by the existing uploader or final transcriber.
Model/settings changes produce a separate preview version. An interruption can be resumed using
the same command without replacing completed chunks. Ctrl+C in the preview terminal stops only
the preview; **Ctrl+C in the recording terminal stops recording**. No always-on worker is installed.

Open **Transcripts** (or Audio) for the selected game in Panther to view the feed. The game toolbar
has a blinking red recording badge linking to Transcripts. Reduced-motion users get a steady dot;
the text label conveys the same state. Keep both the capture terminal and live worker running.
Typical latency is one completed chunk (normally 30 seconds), recognition time and publishing/browser
polling (each up to 20 seconds); it is not a fixed latency promise. Speakers remain unassigned.

An independent thread publishes at most sixty recent speech segments and capture presence every
20 seconds using authenticated `POST /recordings/live`. Network/auth failures do not block recognition
or capture; the terminal warns and retries. Use `panther login` in another terminal if needed.
The red badge requires a fresh heartbeat and recent capture-journal progress, not merely an open
process. Stalled capture is labeled separately; after 75 seconds without a heartbeat the web view
shows **signal lost**, never implies recording stopped safely. Closing the preview also loses presence
even if capture continues. A heartbeat does not establish good microphone quality or successful backup.

The authenticated GET endpoint is polled only by visible signed-in pages. It returns a bounded recent
window (up to ten recording feeds) for the selected game, using the existing shared-group authorization
model. Only `stu` and `other_stu` can publish; a different authenticated user cannot overwrite another
publisher's recording. Older updates cannot replace newer ones. The feed is an explicitly ephemeral
read-time projection: DynamoDB TTL removes it after seven days, and reads hide expired items even before
physical deletion. Complete original audio and immutable local recognizer/chunk results are retained.
There is no S3 asset, editorial trigger, transcript overwrite or asset-storage migration for this new
projection. CDK defines its on-demand table, narrowly scoped Lambda permissions and JWT API routes;
no provisioned compute, subscription inference charge or always-on server is introduced.

## Several speakers

Ask everyone for recording consent. At the beginning, each person speaks alone for roughly 20–30
seconds, introducing their player name and saying a few normal sentences. Pause between people.
Use their normal table voice and seating. These introductions help map anonymous clusters to
people; they are not permanent voiceprints or a guarantee of future recognition.

```sh
panther recording transcribe RECORDING_DIR --model /private/path/ggml-small.bin --local-only
panther recording diarize RECORDING_DIR --speakers NUMBER_ACTUALLY_PRESENT
panther recording attribute TRANSCRIPT_DIR --diarization SPEAKER_RUN/diarization.json --mapping /private/path/speaker-map.json
panther recording upload RECORDING_DIR --transcript ATTRIBUTED_TRANSCRIPT_DIR
```

Listen to the introduction intervals in `diarization.json` and confirm the map. A private map looks
like `{"SPEAKER_00": "confirmed-player-id"}`. Never infer the mapping from label order, character
dialogue, or a prior run. Labels can change on every run; multiple clusters may map to one player.
Partial maps are accepted and unmapped voices stay unassigned.

This first aligner assigns a whole Whisper segment only if one detected speaker covers at least
80% of it and no other detected speaker intersects it. Mixed, overlapping, or poorly covered
segments remain unassigned; all text stays intact. This is deliberately conservative, not a claim
of reliable automatic attribution. Model mistakes can still assign the wrong voice. Word-level
alignment, speaker corrections, and measured game-night evaluation are future improvements.
Neither exclusive diarization nor knowing the speaker count resolves simultaneous spoken words.

Uploads reuse Panther's authentication, checksums, 1 GiB per-object limit, and no-overwrite rules.
The recording's asset folder contains FLAC parts, `recording.json`, and uniquely named transcript
JSON/Markdown versions. Background sync also retains the capture header and per-part checkpoints
under that same recording asset. Transcript metadata points to the source manifest. Local raw engine logs,
speaker runs, import provenance, and intermediate outputs remain available locally; upload them
separately when explicitly needed. A single oversized imported file is rejected, not silently split
or transcoded to bypass the upload limit. Captured short parts normally stay well below it.
