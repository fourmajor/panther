# Browser room recording

Sessions offers **Record** to signed-in catalog members. Get agreement from everyone being recorded, then press **Record** and grant microphone access.
The session ID and a dated display name are generated automatically. Stop shows processing
progress directly below the controls; playback and the transcript appear there when ready.
A current browser on HTTPS (or localhost) needs Web Audio, AudioWorklet, Web Locks and IndexedDB.
Keep the tab open and the device awake. Browser capture cannot certify hardware continuity.

Capture is mono 32 kHz, signed 16-bit PCM in immutable WAV parts, normally 15 seconds each.
This preserves the PCM produced by this browser capture; it does not preserve the microphone's
native sample rate, channel count or floating-point precision. Each closed part is persisted
in IndexedDB before backup through the authenticated, create-only Panther upload API. A meter
indicates input level, not recording fidelity. Browser storage may be cleared or evicted;
uploaded originals are the durable archive. An abrupt close can lose the unfinished part.
After an interruption, return to Audio in the same browser and save retained recording.
Download retained parts for an additional backup; browsers may require permission for multiple downloads.
The recorder stops at 1,000 parts (about 4 hours 10 minutes).

Browser recording is a separate schema-1 `BrowserRecording` contract with WAV source parts,
exact checksums, sample counts, offsets and `captureWarnings`. Native schema-1 `Recording`
remains FLAC. Existing native recordings require no migration: their schema and bytes do not
change. Every new browser recording in every game uses the same validated contract and location
catalog; neither producer nor reader falls back to unindexed payloads.

Only explicit, authenticated completion of the capturing account's uploaded set starts
playback processing. The server verifies membership, declared manifest checksum and every part.
The separate laptop playback worker advertises protocol 2 and produces the continuous listening
copy. Protocol-1 workers skip browser sets; upgrade the laptop CLI before deploying browser capture.
Original WAV parts remain the transcription inputs, never the MP3 derivative.

## Browser upload deployment

The foundation stack's private asset bucket must allow cross-origin **PUT** from the exact
application origin, in addition to GET/HEAD. Recording backup sends a presigned PUT with
conditional-write, SHA-256 and signed metadata headers. Its OPTIONS preflight requires those
headers; allowing only GET/HEAD makes the browser report a generic network failure before
uploading any audio. CDK owns this CORS rule. It grants no anonymous write access: signed
requests, authentication, checksums and create-only storage conditions remain required.
The published bucket has no browser upload CORS rule. Deploy the foundation CORS change
alongside browser recording fixes; a frontend deployment alone cannot repair the preflight.
Retained browser originals remain available for a later successful save.

## Optional OpenAI transcription

Deploy with CDK context `browserTranscriptionSecretArn` pointing to an existing **us-west-2**
Secrets Manager secret containing the API key as a plain string or `{"OPENAI_API_KEY":"…"}`.
Only the transcription worker and authenticated credential broker can read it. The long-lived key never reaches the browser. The broker issues a 60-second Realtime credential; it is used only in memory and is never persisted or logged. Credentials can initialize sessions until expiry; provider sessions may continue afterward. CDK owns the
integration, queues, IAM and on-demand state. A configured ARN enables the UI, but an invalid
or unfunded key can still fail at the provider. Without that setting, new browser recording is disabled with a live-transcription availability
notice; existing retained audio can still be recovered and saved. Preview CDK changes in the correct
Panther account before deploying; do not create infrastructure through ad hoc AWS writes.

This user-authorized feature is a narrow paid OpenAI API integration. It is not a fallback
for the existing subscription-backed editorial/model workflows or local CLI ASR.

Record opens a recording dialog with Pause, Resume and Stop. Closing the dialog keeps
capture running; the header indicator reopens it. Paused time is excluded from recorded audio.
Live transcription uses OpenAI's dedicated `gpt-live-transcribe` Realtime model. A separate
24 kHz PCM side channel sends audio roughly every 100 ms, without altering archived 32 kHz WAV
parts. Incremental provider deltas appear while speech arrives, before a 15-second archive part
closes. Session configuration pins English (`languages: ["en"]`), low delay and far-field noise
reduction for room microphones. Client voice activity detection commits turns; server VAD is
disabled (`turn_detection: null`). Silence is not submitted as invented speech. These hints reduce
noise errors but do not guarantee perfect recognition. Live output remains provisional, with no
invented speaker identities, word timestamps or confidence scores.

The authenticated `/browser-recording/live-session` endpoint durably checkpoints issuance before
requesting a credential. An ambiguous mint or broken stream is never automatically reconnected or
repeated; the recorder keeps originals and shows the live error. A connection correlation ID is
separate from the actual provider session ID. Token-free, browser-relayed provider events are preserved as bounded,
immutable, idempotent `/browser-recording/live-events` receipts, independently of the final transcript.
These provisional browser observations are not a verified transcript or evidence of speaker identity.
The browser connects directly over TLS WebSocket; CDK's CSP permits only `wss://api.openai.com`.
See the [Realtime transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription)
and [client secret reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets).
Stop submits a **separate full pass** with `gpt-transcribe` and explicit English guidance, independent of live results, using contiguous windows
of up to 18 parts (4.5 minutes; below the provider file limit). Longer recordings use multiple
windows; this is not a promise of whole-session model context or perfect transcription.

Jobs have durable outbox delivery and deterministic identities. Repeating the same API request
reuses the same job. A potentially charged request is never automatically sent again following
an uncertain outcome. Sources and successfully saved provider responses remain available for
investigation. Failed aggregation retries publication without repeating inference. This can
leave an explicitly unknown result requiring operator intervention; it must not silently spend
again or replace evidence.

Provider JSON is saved immutably. A schema-1 `BrowserTranscript` retains source references,
response references, requested model, unassigned speakers, window-boundary timing and capture
warnings. Actual model/version is recorded only when reported by the provider; an alias is not
proof of a snapshot. Per-asset billed cost stays unknown without billing evidence. Finished
Inputs/Outputs traverse these intermediate provider responses through the existing asset catalog.
The raw transcript is unreviewed and does not automatically become a `PlayerTranscript` or
start the editorial pipeline. Speaker identity requires separate evidence and later annotation.

Tests use synthetic PCM, mocked OpenAI responses and the self-hosted Docker Chromium runner's
fake microphone. They make no paid calls and never access the user's microphone or browser profile.
