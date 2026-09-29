# Recording den

The normal recording command stays script-friendly. Add `--tui` for the keyboard-first
Textual dashboard. Use the exact microphone name from `panther recording devices`:

```sh
panther recording start --game example-game --session example-session \
  --device 'Exact microphone name' --sync --tui --live
```

`--live` starts the existing local Whisper preview from the beginning. It needs the same
local models/tools as `panther recording live`; failures do not interrupt capture. With
`--sync`, the worker also publishes the existing provisional web feed. Without sync it
stays local. Omit `--live` to record without recognition. This preview is not the final
speaker-attributed transcript. No paid inference is introduced. The plain command without
`--tui` is unchanged, including its background uploader and streaming checkpoints.

The dashboard shows separate local capture, saved FLAC chunks, confirmed cloud backup and
transcription states. Audio peak metering is advisory: it cannot certify sound quality,
missing-sample integrity or cloud durability. Missing/stale readings say unknown, not silence.
Native metering runs on the existing consumer, never the real-time microphone callback;
failed meter writes do not abort recording. Its disposable local file is not uploaded.

- **S / Ctrl+C / Stop & save:** request graceful stop, then wait for the original controller
  to finalize/verify its final chunk. This is not an immediate exit.
- **Q:** stop first; press again after finalization to exit.
- **Tab / arrows / Page Up / Page Down:** focus and scroll transcript/event history.
- **L:** return to live speech. New text does not move a reader who scrolled back.
- **H:** show help in the persistent events panel.
- **`--reduced-motion`:** use a static recording indicator. State is always textual, not color-only.

The dashboard can scroll vertically in a small terminal. Transcript text retains the beginning
and backfilled chunks; a safety bound at 32 MiB reports an explicit limit and keeps the source
preview file for direct reading, rather than silently presenting a partial history as complete.
Events remain visible after recovery. All terminal text is literal, not injected Rich markup.

The TUI launches the original CLI controller in a separate process; rendering, status-read
errors, network outages and recognition backlog do not run on the capture path. Its private
wrapper directory contains `controller.log` and the actual recording subdirectory. The final
summary names the actual folder, unconfirmed chunk count and cloud-set completion separately.
The background uploader may still be working when the recorder stops. A zero unconfirmed count
does not imply the completed chunk set was finalized in the cloud.

On failure, preserve all files. Inspect `controller.log`, `capture.log`, `sync.log` or
`tui-preview.log` as indicated. `panther recording recover FOLDER` closes an interrupted
recording; `panther recording audit FOLDER` checks integrity; `panther recording sync FOLDER`
resumes backup through Panther login, not AWS administration. No original files are deleted.
Unexpected TUI exit also requests graceful recorder shutdown. If finalization exceeds the
cleanup timeout, the controller is left preserving audio and an explicit warning names its
folder; do not kill it or delete its files blindly.

Tests use Textual's [headless Pilot](https://textual.textualize.io/guide/testing/) at multiple
terminal sizes, including stop/finalization, persistent failures and history scroll behavior.
Native tests use generated ramps and verify exact decoded audio bytes with metering enabled;
they never open a microphone. The UI's
[RichLog](https://textual.textualize.io/widgets/rich_log/) keeps recognition text independent
of the capture controller.

If the local linker reports unsupported architectures in a newly installed SDK, use a
compatible installed SDK through `SDKROOT` for the recorder build, or update the matching
command-line tools. This is a toolchain setup failure, not a microphone/audio failure. Do
not skip native sample-preservation tests or start a recording before dependency checks pass.
