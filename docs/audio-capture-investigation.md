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

The original diagnosis did not change the backend. The follow-up capture fix replaces that input
path with a bundled native C recorder using PortAudio's Core Audio host API. It keeps a preallocated
single-producer/single-consumer queue, checks input-loss flags and ADC timestamp continuity, and writes
24-bit PCM in a separate consumer thread. The existing verified FLAC/checkpoint/sync pipeline remains.
Source audio already lost by the previous implementation cannot be restored.

[PortAudio's callback contract](https://portaudio.com/docs/v19-doxydocs/portaudio_8h.html) supplies
input-overflow/underflow flags and buffer timestamps. The callback copies into preallocated storage
using lock-free atomic queue indices; no allocation, filesystem access, Python, or waiting occurs
there. Its consumer keeps active WAV headers current, flushes them periodically, and publishes a
CSV row only after a chunk is closed and flushed. Missing/ambiguous device names fail rather than
selecting a default. Requested sample rate is the device's advertised current/default rate and all
input channels are retained, with an explicit 24-bit integer archival format.

`capture-health.json` is immutable final evidence, uploaded alongside the recording manifest through
Panther. Error codes: 1 input overflow/underflow, 2 timestamp discontinuity, 3 application queue full,
4 invalid/oversized callback, 5 disk/journal failure, 6 stopped/stalled device, 7 startup/no-audio failure.
Any error returns nonzero and keeps recoverable audio; a missing health report after a crash is a
warning. ADC timestamps are host/backend-reported estimates, not proof of hardware-perfect capture.

Native synthetic tests exercise the same callback/queue/writer with a known 24-bit integer ramp,
including exact sample sequence across chunk boundaries, timestamp gap and overflow injection,
queue exhaustion, overwrite rejection, controller EOF, and abrupt kill/recovery. These do not open
a microphone. Real-device acceptance is separate and requires recording consent.

The consented 60-second TONOR acceptance test captured exactly 2,880,000 samples at 48 kHz in six
verified ten-second FLAC chunks, with 704 native callbacks, no input-loss/queue errors, and queue
high-water 4 of 128 buffers. Reported ADC elapsed time was 59.999646584 seconds (0.353416 ms shorter
than nominal sample duration); the largest adjacent timestamp deviation was 10.709 microseconds.
This replaces the prior repeatable ~10% shortfall with matching sample counts and no reported buffer
loss. It is not a multi-hour or speech-intelligibility certification. This diagnostic stayed local;
it was not uploaded or transcribed.

Audit permits at most 100 ppm accumulated ADC-vs-nominal-clock skew, independently of callback
continuity checks (100 microseconds or two samples per callback, whichever is larger), exact
accepted/written/decoded sample counts, and explicit backend error flags. The exact clock difference
and tolerance remain visible. These are engineering thresholds, not guarantees of perfect hardware
or detection of every possible defect. No resampling, padding or reconstruction is performed.

`panther recording audit RECORDING_DIR` now compares decoded duration with the segment timestamp
journal. New raw transcripts retain this warning. A matching duration is necessary but not sufficient
for good capture: future acceptance should include known-tone/sample continuity, long-run load,
disconnect, disk-full, interruption/recovery, and actual speech tests. Synthetic input tests alone
did not exercise AVFoundation and therefore missed this defect.
