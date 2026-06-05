# ADR 0001: Audio Capture Strategy for Speaker-Attributed TTRPG Sessions

Status: Accepted

Date: 2026-06-05

## Context

The system must turn 2.5-3 hour tabletop RPG sessions with 5 people, typically 4 players plus 1 GM, into a near-real-time speaker-attributed transcript and grounded recap artifacts.

The primary requirement is accurate speaker attribution. Transcription quality matters, but the system should not rely on diarization as the primary attribution method. Each speaker should map to a known audio channel whenever possible. Diarization may be used as a fallback for leakage, remote joins, or unexpected audio routing failures.

## Decision Drivers

- Highest practical speaker attribution accuracy
- Good transcription quality during natural tabletop conversation
- Robustness to interruptions, jokes, rules debate, and overlapping speech
- Setup that can be repeated by a technical user without studio labor
- Support for 5 in-person participants and occasional remote participants
- Upgrade path from cloud ASR/LLM APIs to local/offline processing

## Options Compared

Cost estimates are street-price ranges in USD for a 5-person setup, excluding the Mac/Linux machine.

### 1. Single Room Microphone

Examples: Blue Yeti, Audio-Technica AT2020USB-X, Rode NT-USB+, Zoom H1essential/H4essential as room recorder.

- Estimated cost: $80-$350
- Speaker attribution accuracy: Low, typically 45-65% without manual correction; may improve to 60-75% with diarization in clean rooms
- Transcription quality: Fair to good for dominant speakers; weak for quiet speakers, side comments, crosstalk, dice noise, snacks, and distance variance
- Setup complexity: Very low
- User friction: Very low
- Interruptions/talkovers: Poor; overlapping speech collapses into one mixed signal
- Suitability for 5-person TTRPG: Poor for the primary requirement, acceptable only for rough notes

Pros:

- Cheapest and fastest to start
- Minimal table clutter
- No participant behavior changes
- Useful as a backup/reference recording

Cons:

- Speaker attribution depends almost entirely on diarization
- Cannot separate simultaneous speakers
- ASR quality varies sharply by seat position
- Non-game chatter is harder to classify because speaker identity and intent are weaker

Assessment: Not acceptable as the main capture path when accurate attribution is the primary requirement.

### 2. Multiple Tabletop Boundary Microphones

Examples: Audio-Technica U841R, Shure Centraverse CVB, MXL AC-404, Behringer BA 19A, Crown PCC-style boundary mics.

- Estimated cost: $400-$1,500 for 3-5 mics plus interface/mixer
- Speaker attribution accuracy: Medium, typically 65-80%; 75-85% with careful seating and one mic per table zone
- Transcription quality: Good for nearby speakers; degraded by bleed between adjacent seats
- Setup complexity: Medium
- User friction: Low to medium
- Interruptions/talkovers: Fair; can separate table zones but not reliably separate adjacent speakers talking at once
- Suitability for 5-person TTRPG: Moderate; useful when lav/headset friction is unacceptable

Pros:

- Less intrusive than wearable microphones
- Better signal-to-noise ratio than a single room mic
- Can use multichannel interfaces and preserve channel mapping
- Reasonable backup or compromise setup

Cons:

- Channels represent zones, not guaranteed speakers
- Bleed and shared table surfaces reduce attribution accuracy
- Dice, paper, laptops, and table taps are captured strongly
- Seating changes can break channel mapping

Assessment: A workable budget-to-midrange compromise, but not the best fit for hard attribution guarantees.

### 3. One Lavalier Microphone per Participant

Examples: Rode Wireless PRO/GO II, DJI Mic 2, Deity Theos, Sennheiser XSW-D or EW-DP, Tascam DR-10L Pro, Zoom F2/F2-BT, Tentacle Track E.

- Estimated cost: $750-$2,500 for 5 participants depending on wired/wireless and recording strategy
- Speaker attribution accuracy: High, typically 90-97% when each lav is recorded to an isolated channel or file
- Transcription quality: Good to excellent, especially with consistent mic placement
- Setup complexity: Medium to high
- User friction: Medium; participants must clip on mics and manage cables/transmitters
- Interruptions/talkovers: Good if channels are isolated; ASR can process each speaker independently
- Suitability for 5-person TTRPG: High

Pros:

- Strong known-speaker channel mapping
- Much better crosstalk handling than table/room microphones
- Quiet speakers are captured well
- Local recorders can provide resilient backup

Cons:

- Clothing rustle and bad placement can hurt quality
- Wireless systems require battery/channel management
- Consumer wireless kits usually expose only 2 channels per receiver, requiring multiple receivers or post-sync workflows
- Some participants dislike being wired

Assessment: The best balance for a serious system when attribution is primary and the group will tolerate clip-on mics.

### 4. Headset Microphone per Participant

Examples: Shure WH20/XLR, Audio-Technica BPHS1, Countryman E6, DPA 4066/4088, Antlion ModMic with interface, broadcast headsets.

- Estimated cost: $600-$3,500 for 5 participants plus interface/mixer
- Speaker attribution accuracy: Very high, typically 95-99% with isolated channels
- Transcription quality: Excellent; best rejection of table noise and room bleed
- Setup complexity: Medium to high
- User friction: High; visible, physical, and roleplay-disruptive for many groups
- Interruptions/talkovers: Excellent when isolated per channel
- Suitability for 5-person TTRPG: Technically excellent, socially mixed

Pros:

- Best practical audio isolation
- Most robust against talkovers
- Consistent mouth-to-mic distance improves ASR
- Handles poor rooms better than other options

Cons:

- Highest participant friction
- Can feel like a streamed show or call center rather than a home game
- Requires cable routing or wireless bodypacks
- More hardware to clean, fit, store, and maintain

Assessment: Technically strongest for attribution and ASR, but often too intrusive for casual in-person TTRPG sessions.

### 5. Conference-Room Microphone Arrays

Examples: Shure MXA310/MXA710, Sennheiser TeamConnect Ceiling 2, Nureva HDL, Poly Studio, Jabra Speak2 75, Owl Labs Meeting Owl.

- Estimated cost: $250-$6,000+
- Speaker attribution accuracy: Medium to high for direction/seat inference, typically 65-85%; lower if device outputs only mixed audio
- Transcription quality: Good for meetings; variable for dramatic roleplay, low voices, dice/table noise, and overlapping banter
- Setup complexity: Low to high depending on device class
- User friction: Very low
- Interruptions/talkovers: Fair to good; beamforming helps but cannot fully separate overlapped speakers if output is mixed
- Suitability for 5-person TTRPG: Moderate for convenience, weak if the array cannot expose per-beam/per-speaker channels

Pros:

- Cleanest user experience
- Good echo cancellation for hybrid sessions
- Some systems provide direction-of-arrival metadata
- Strong option for meeting-style remote inclusion

Cons:

- Many products output a processed mono/stereo mix, not isolated speaker channels
- Beam labels are not stable speaker identities unless seating is fixed and calibrated
- Expensive pro systems can still underperform lav/headset setups for attribution
- Vendor SDK/API access may be limited

Assessment: Attractive for convenience and hybrid audio, but only suitable as the main capture path if the chosen system exposes stable per-zone audio or reliable direction metadata.

### 6. Hybrid In-Person + Remote Participant Setups

Examples: In-person lav/headset/boundary capture plus Zoom/Discord/Meet remote track, OBS, BlackHole/Loopback, Audio Hijack, Voicemeeter on Windows, ffmpeg, separate remote ASR channel.

- Estimated cost: $0-$300 incremental if using existing remote platform; $100-$500 with virtual audio routing tools and backup recorder
- Speaker attribution accuracy: High for remote participant if captured as an isolated channel, typically 95-99%; in-person accuracy depends on chosen local setup
- Transcription quality: Good for remote if the participant uses a headset; lower with laptop speakers/mic
- Setup complexity: Medium to high
- User friction: Medium for host; low to medium for remote participant
- Interruptions/talkovers: Good if remote track and in-person tracks are isolated; poor if remote audio leaks into room mics
- Suitability for 5-person TTRPG: Required as an extension pattern, not a standalone local capture strategy

Pros:

- Remote participant can be mapped cleanly to a known channel
- Works with the same per-channel transcript architecture
- Allows remote-specific echo cancellation and gain handling
- Can record the call track separately for recovery

Cons:

- Requires careful routing to avoid remote audio being recorded both digitally and through speakers
- Latency can create unnatural talkovers
- The remote participant needs headset discipline
- More failure modes at session start

Assessment: Treat remote participants as additional isolated channels. Use headphones or echo cancellation to keep their audio out of room microphones.

## Quantified Comparison

| Option | Cost | Attribution | ASR Quality | Setup | Friction | Talkovers | 5-Person Fit |
|---|---:|---:|---:|---:|---:|---:|---:|
| Single room mic | $80-$350 | 45-65% | 2/5 | 1/5 | 1/5 | 1/5 | 1/5 |
| Boundary mics | $400-$1,500 | 65-80% | 3/5 | 3/5 | 2/5 | 2/5 | 3/5 |
| Lavalier per participant | $750-$2,500 | 90-97% | 4/5 | 3/5 | 3/5 | 4/5 | 5/5 |
| Headset per participant | $600-$3,500 | 95-99% | 5/5 | 3/5 | 5/5 | 5/5 | 4/5 |
| Conference array | $250-$6,000+ | 65-85% | 3/5 | 2-4/5 | 1/5 | 2-3/5 | 3/5 |
| Hybrid extension | $0-$500 incremental | 95-99% remote isolated | 3-5/5 | 3/5 | 2/5 | 4/5 | 5/5 |

The jump from single-room capture to isolated lavalier channels is dramatic: expected attribution accuracy improves from roughly 45-65% to 90-97%, a practical gain of 30-50 percentage points. This improvement is not mainly because lavaliers are higher fidelity; it comes from removing the need to infer identity from a mixed waveform. Each ASR stream already has a known speaker.

Headsets can add another 3-8 percentage points over lavaliers in difficult rooms because they reject table noise and other voices better, but the social friction is much higher. For most TTRPG groups, lavaliers are the best practical point on the curve.

## Recommended Products

Budget:

- Zoom H6essential or H8 with wired lavs where practical
- Behringer UMC1820 or Focusrite Scarlett 18i20 with inexpensive wired lav/headset adapters
- Audio-Technica ATR3350xIS lavs or similar budget lavs for early testing
- A room recorder such as Zoom H1essential as backup

Recommended:

- Rode Wireless PRO kits, DJI Mic 2 kits, or Tascam DR-10L Pro/Zoom F2-style bodypack recorders per participant
- Multichannel interface or synchronized per-speaker files
- Headphones or echo-controlled routing for any remote participant
- Backup room recording for recovery and QA

Best-practical:

- DPA 4060/4061 or Countryman B3/B6 lavaliers into reliable bodypacks/interfaces, or DPA/Countryman/Shure headset mics if the group accepts them
- Sound Devices MixPre-10 II, Zoom F8n Pro, or equivalent multitrack recorder/interface
- Remote participant isolated through Loopback/BlackHole/Audio Hijack/OBS/ffmpeg into a dedicated channel
- Optional room/conference mic only for ambience and failure recovery

## Decision

Use one isolated audio channel per participant as the architectural target. The recommended default is one lavalier microphone per participant, with headset microphones reserved for best-practical or noisy-room deployments. Boundary microphones and conference arrays may be supported as secondary profiles, but the software must not depend on diarization for primary speaker attribution.

Remote participants should be captured as their own isolated digital channels. Their call audio must not be played into the physical room unless the room capture path is echo-cancelled or headphones are used.

## Recommendations

Budget solution:

- Multiple tabletop boundary microphones or inexpensive wired lavaliers into a multichannel interface.
- Expected attribution: 70-85% depending on seating discipline and bleed.
- Use diarization only to resolve bleed and ambiguous segments.

Recommended solution:

- One lavalier microphone per participant, captured as isolated channels or synchronized mono files.
- Expected attribution: 90-97%.
- This is the preferred hardware target for the project.

Best-practical solution:

- One headset microphone per participant, or high-quality lavaliers into a professional multitrack recorder/interface.
- Expected attribution: 95-99%.
- Choose this when accuracy matters more than visible hardware and participant comfort.

## Consequences

- The pipeline will model speakers as configured channel mappings.
- VAD, ASR, line classification, filtering, and memory extraction will operate on timestamped speaker-attributed lines.
- Diarization support is fallback logic, not the central design.
- The sample implementation will start with mock multichannel input so the data contracts can be tested without hardware.
- Future ingestion implementations should support CoreAudio, ffmpeg, and multichannel WAV inputs.
