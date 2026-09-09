# macOS capture discrepancy investigation

## Finding

The retained pre-FLAC PCM files already contain fewer samples than the capture device's elapsed
timestamps. Lossless compression, joining and cloud sync are not the cause of this discrepancy.
A consented 15-second local-only diagnostic using the same installed FFmpeg 7.1.1/AVFoundation path
reproduced the failure: 13.517333 seconds of captured audio. Packet tracing showed 139 timestamp
gaps of approximately 10,667 microseconds each, totaling 1.482761 seconds. At 48 kHz these are
whole 512-sample input buffers missing **at the demuxer**, before PCM encoding or segmentation.
That is approximately 9.9% missing in this diagnostic. The earlier longer test was about 11.2% short.
The diagnostic audio/logs are private and are not repository fixtures or uploaded game assets.

[The exact upstream capture implementation](https://github.com/FFmpeg/FFmpeg/blob/n7.1.1/libavdevice/avfoundation.m#L274)
releases an unread `current_audio_frame` before storing the next callback buffer. It retains one
pending buffer rather than a queue. The trace establishes missing input buffers; this overwrite
path explains how a delayed consumer can silently lose them. No instrumented FFmpeg build was used
to count executions of that line, so the specific scheduling cause is not claimed as proven.
An [upstream report for FFmpeg 7.1](https://lists.ffmpeg.org/pipermail/ffmpeg-trac/2025-January/072278.html)
also describes missing samples during AVFoundation capture across codecs and devices.

## Consequences

- Valid FLAC checksums establish that stored bytes survived, not that every microphone sample arrived.
- Original device-clock time and the concatenated surviving-audio timeline differ. Current transcript
  timestamps point into the surviving audio, not reconstructed wall-clock time.
- Resampling or padding silence cannot recover missing words and must not be presented as a repair.
- Do not blame the microphone based on this evidence; the reproducible loss is in the software capture
  path. A native Core Audio/AVAudioEngine recorder or an instrumented/fixed queued capture adapter needs
  a fresh consented acceptance test before replacing the production recorder.

The requested diagnosis is complete; this change does not silently swap recording backends.
`panther recording audit RECORDING_DIR` now compares decoded duration with the segment timestamp
journal. New raw transcripts retain this warning. A matching duration is necessary but not sufficient
for good capture: future acceptance should include known-tone/sample continuity, long-run load,
disconnect, disk-full, interruption/recovery, and actual speech tests. Synthetic input tests alone
did not exercise AVFoundation and therefore missed this defect.
