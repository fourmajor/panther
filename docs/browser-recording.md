# Browser room recording

Audio and Transcripts offer **Record room audio** to signed-in catalog members. Get agreement from everyone being recorded, then press **Record** and grant microphone access.
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

## Optional OpenAI transcription

Deploy with CDK context `browserTranscriptionSecretArn` pointing to an existing **us-west-2**
Secrets Manager secret containing the API key as a plain string or `{"OPENAI_API_KEY":"…"}`.
Only the transcription worker can read it; browser configuration contains no key. CDK owns the
integration, queues, IAM and on-demand state. A configured ARN enables the UI, but an invalid
or unfunded key can still fail at the provider. Without that setting, recording and backup
remain available and transcription controls are disabled. Preview CDK changes in the correct
Panther account before deploying; do not create infrastructure through ad hoc AWS writes.

This user-authorized feature is a narrow paid OpenAI API integration. It is not a fallback
for the existing subscription-backed editorial/model workflows or local CLI ASR.

Live transcription defaults on when configured. One click disables new live requests; already
submitted work can finish. Live requests use completed 15-second parts and `gpt-transcribe`, so
results arrive after a part closes and provider processing completes. Live output is provisional.
Stop submits a **separate full pass**, regardless of the live toggle, using contiguous windows
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
