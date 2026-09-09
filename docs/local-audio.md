# Local recording and player-attributed transcripts

The first implementation is an explicit CLI workflow, not an automatic cloud job. Capture works
offline. Whisper.cpp and pyannote Community-1 run locally; no paid inference or audio uploads to
model providers. Uploading to Panther is a separate, authorized operation. The web app browses
uploaded files; it does not yet offer transcript editing or playback synchronized with speakers.

## Storage and identity

- Preserve captured audio as lossless FLAC at the input sample rate and channel count, in ordered
  ten-minute parts. The recording manifest records exact checksums, lengths, format, and offsets.
- Capture encodes 24-bit integer PCM. This is not a bit-perfect archive of hypothetical floating
  point or 32-bit source input. The initial USB microphone test is ordinary integer PCM speech.
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

Install FFmpeg, FLAC, and whisper.cpp using Homebrew. Supply a real local Whisper model to
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
panther recording start --game GAME_ID --session SESSION_ID --device 'EXACT MICROPHONE NAME' --seconds 180
panther recording transcribe RECORDING_DIR --model /private/path/ggml-small.bin --sole-player PLAYER_ID
panther recording upload RECORDING_DIR --transcript TRANSCRIPT_DIR
```

`--sole-player` is the user's declaration, not speaker recognition. Only use it if that person is
the only speaker throughout. Read the transcript and listen to the original before calling it
accurate. Recording device enumeration and public-audio smoke tests do not validate real microphone
capture or game-night attribution. Capture logs remain private; check for dropped input or errors.
`recording recover` validates intact parts after an interruption. It does not repair a corrupt final
part or establish that no sound was missed. No source file is automatically deleted.

`recording import FILE.wav --game GAME_ID --session SESSION_ID` imports existing audio without
deleting it. A saved `panther game show GAME_ID` response can be passed as `--roster` for offline
transcription. Otherwise the command obtains the current roster through Panther authentication.

## Several speakers

Ask everyone for recording consent. At the beginning, each person speaks alone for roughly 20–30
seconds, introducing their player name and saying a few normal sentences. Pause between people.
Use their normal table voice and seating. These introductions help map anonymous clusters to
people; they are not permanent voiceprints or a guarantee of future recognition.

```sh
panther recording transcribe RECORDING_DIR --model /private/path/ggml-small.bin
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
JSON/Markdown versions. Transcript metadata points to the source manifest. Local raw engine logs,
speaker runs, import provenance, and intermediate outputs remain available locally; upload them
separately when explicitly needed. A single oversized imported file is rejected, not silently split
or transcoded to bypass the upload limit. Captured ten-minute parts normally stay well below it.
