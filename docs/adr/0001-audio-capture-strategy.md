# ADR 0001: Audio Capture Strategy for Speaker-Attributed TTRPG Sessions

Status: Accepted

Date: 2026-06-05

## Context

The system must turn 2.5-3 hour tabletop RPG sessions with 5 people, typically 4 players plus 1 GM, into a near-real-time speaker-attributed transcript and grounded recap artifacts.

The primary requirement is accurate speaker attribution. Transcription quality matters, but the system should not rely on diarization as the primary attribution method. Each speaker should map to a known channel whenever possible. Diarization may be used only as fallback for leakage, remote joins, or unexpected audio routing failures.

There is now a hard hardware constraint:

- Total microphone budget must be $500 or less.
- Options that require more than $500 for the 5-person table are out of scope for the initial project.
- The capture design should still preserve an upgrade path, but recommendations must fit the $500 cap.

## Decision Drivers

- Hard maximum microphone budget of $500 total
- Highest practical speaker attribution accuracy within that cap
- Prefer known speaker-to-channel mapping over diarization
- Good enough transcription quality for natural tabletop conversation
- Setup that a technical user can repeat without studio labor
- Support for 5 in-person participants and occasional remote participants
- Cloud APIs are acceptable initially; local/offline paths should remain possible

## Budget Interpretation

The $500 cap applies to microphones/transmitters/receivers needed for the in-person table. It does not include the Mac/Linux computer.

If an option needs an audio interface, cables, or adapters to make the channels usable by software, those costs must be considered when selecting the actual shopping list. A setup that buys cheap microphones but requires expensive capture hardware is not a valid budget solution.

## Options Compared

Cost estimates are current practical street-price ranges in USD for a 5-person setup.

### 1. Single Room Microphone

Examples: Blue Yeti, Audio-Technica AT2020USB-X, Rode NT-USB+, Zoom H1essential/H4essential as room recorder.

- Estimated cost: $80-$350
- Within $500 cap: Yes
- Speaker attribution accuracy: Low, typically 45-65% without manual correction; may improve to 60-75% with diarization in clean rooms
- Transcription quality: Fair to good for dominant speakers; weak for quiet speakers, side comments, crosstalk, dice noise, snacks, and distance variance
- Setup complexity: Very low
- User friction: Very low
- Ability to handle interruptions/talkovers: Poor; overlapping speech collapses into one mixed signal
- Suitability for 5-person TTRPG sessions: Poor for the primary requirement, acceptable only as fallback/reference audio
- Recommended products: Zoom H1essential/H4essential, Blue Yeti, Rode NT-USB+, Audio-Technica AT2020USB-X

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

Assessment: Within budget, but not acceptable as the main capture path when accurate attribution is the primary requirement.

### 2. Multiple Tabletop Boundary Microphones

Examples: MXL AC-404, CAD Audio U7, Behringer BA 19A, used boundary microphones, inexpensive USB conference puck mics.

- Estimated cost: $150-$500 if using inexpensive or used mics; higher-quality boundary setups often exceed the cap
- Within $500 cap: Yes only with budget/used products
- Speaker attribution accuracy: Medium-low, typically 60-75%; 75-80% only with careful seating and one mic per table zone
- Transcription quality: Fair to good for nearby speakers; degraded by bleed between adjacent seats and table noise
- Setup complexity: Medium
- User friction: Low
- Ability to handle interruptions/talkovers: Fair for separated table zones, poor for adjacent speakers talking at once
- Suitability for 5-person TTRPG sessions: Moderate if participant-worn mics are rejected, but weaker than lav-style capture
- Recommended products: used boundary mics, MXL AC-404, Behringer BA 19A, CAD Audio U7, budget USB conference mics used as table-zone inputs

Pros:

- Less intrusive than wearable microphones
- Better signal-to-noise ratio than a single room mic
- Can create rough table-zone attribution
- Fits the budget if bought carefully

Cons:

- Channels represent zones, not guaranteed speakers
- Bleed and shared table surfaces reduce attribution accuracy
- Dice, paper, laptops, and table taps are captured strongly
- Seating changes can break channel assumptions

Assessment: Valid fallback under $500, but not the recommended path because it does not give one known channel per speaker.

### 3. One Lavalier or Clip-On Wireless Microphone per Participant

Budget examples: SYNCO G2(A2), Movo WMX-2-DUO, Hollyland Lark M1 Duo, COMICA Vimo C3, Saramonic Blink500 B2+ if discounted, used Rode Wireless GO II Dual, refurbished DJI Mic 2.

- Estimated cost: $270-$500 for three 2TX/1RX kits, depending on model and used/refurb pricing
- Within $500 cap: Yes, if using budget or used/refurb dual-transmitter kits
- Speaker attribution accuracy: High for the budget, typically 80-92% if each receiver preserves transmitter A/B as stereo left/right and the software maps those channels
- Transcription quality: Good enough to good; varies by radio reliability, clipping, noise reduction, and mic placement
- Setup complexity: Medium
- User friction: Medium; each participant clips on a transmitter or lav
- Ability to handle interruptions/talkovers: Good within the limits of stereo-pair capture; each speaker has a known side/channel unless receiver output is mixed
- Suitability for 5-person TTRPG sessions: Best fit under the $500 cap
- Recommended products: first test one SYNCO G2(A2) or Movo WMX-2-DUO; then scale to three 2TX/1RX kits only after verifying split stereo output on the Mac

Pros:

- Best available path to known speaker-channel mapping under $500
- Three 2TX/1RX kits provide six transmitter positions for five people
- Much better attribution than room or table-zone microphones
- Used/refurb Rode Wireless GO II or DJI Mic 2 can add onboard recording backup while staying near the cap

Cons:

- Many cheap kits advertise "dual mics" but output a forced mono mix; those are not suitable
- Consumer receivers usually expose only two channels, so five people require three receivers or post-session sync
- Cheap systems may apply aggressive noise reduction or automatic gain control
- No guaranteed onboard backup on the cheapest systems
- Multiple 2.4 GHz kits in one room should be tested before relying on them for a session

Assessment: Recommended initial capture strategy. The key purchase requirement is not "wireless lav"; it is "2TX/1RX with stereo/split output or onboard per-transmitter recording."

### 4. Headset Microphone per Participant

Examples: budget wired TRRS/USB headsets, gaming headsets, inexpensive wired broadcast-style headsets.

- Estimated cost: $100-$500 for five budget headsets; more robust headset/interface setups exceed the cap
- Within $500 cap: Yes only with budget consumer headsets and simple USB/TRRS routing
- Speaker attribution accuracy: High if each headset is recorded as an isolated device/channel, typically 85-95%
- Transcription quality: Fair to good; cheap headset mics can sound compressed but reject table noise well
- Setup complexity: Medium to high because five separate USB/TRRS devices are awkward to aggregate
- User friction: High; visible, physical, and roleplay-disruptive for many groups
- Ability to handle interruptions/talkovers: Good if each headset is isolated
- Suitability for 5-person TTRPG sessions: Technically plausible under $500, socially unattractive
- Recommended products: low-cost wired USB headsets only for testing or groups that tolerate headset wear

Pros:

- Strong isolation for the price
- Better rejection of dice/table noise than room microphones
- Good attribution if each device can be captured separately

Cons:

- Highest participant friction
- Five USB devices can be annoying to route and keep stable
- Cheap headset audio quality varies heavily
- Changes the social feel of an in-person tabletop session

Assessment: A budget-valid technical fallback, not the preferred TTRPG experience.

### 5. Conference-Room Microphone Arrays

Examples: Jabra Speak series, AnkerWork conference speakers, used meeting bars, Poly/Owl-style devices.

- Estimated cost: $100-$500 for budget/used products; professional arrays exceed the cap
- Within $500 cap: Yes for budget/used conference devices only
- Speaker attribution accuracy: Medium-low, typically 55-75%; higher only if the device exposes usable direction or channel metadata, which most budget products do not
- Transcription quality: Good for meetings; variable for dramatic roleplay, quiet voices, dice/table noise, and overlapping banter
- Setup complexity: Low
- User friction: Very low
- Ability to handle interruptions/talkovers: Fair at best; beamforming helps audibility but usually outputs a mixed signal
- Suitability for 5-person TTRPG sessions: Convenient but weak for the primary requirement
- Recommended products: budget Jabra/AnkerWork-style devices only as fallback or remote-call helper, not as primary attribution capture

Pros:

- Clean user experience
- Simple setup
- Often good echo cancellation for remote participants
- Fits under $500

Cons:

- Most budget conference devices output a processed mono/stereo mix, not isolated speaker channels
- Direction/beam labels are not stable speaker identities
- Overlapping speech remains difficult
- Processing may damage ASR input

Assessment: Useful for hybrid call audio and fallback recording, but not recommended as the primary capture path.

### 6. Hybrid In-Person + Remote Participant Setups

Examples: budget 2TX/1RX in-person kits plus Zoom/Discord/Meet remote track, OBS, BlackHole/Loopback, Audio Hijack, ffmpeg, or separate remote ASR channel.

- Estimated cost: $0-$150 incremental if using existing remote platform and free routing tools; up to $500 if buying a routing app and backup recorder
- Within $500 cap: Yes
- Speaker attribution accuracy: High for the remote participant if captured as an isolated channel, typically 90-99%; in-person accuracy depends on the local setup
- Transcription quality: Good for remote if the participant uses a headset; lower with laptop speakers/mic
- Setup complexity: Medium to high
- User friction: Medium for host; low to medium for remote participant
- Ability to handle interruptions/talkovers: Good if remote track and in-person tracks are isolated; poor if remote audio leaks into room mics
- Suitability for 5-person TTRPG sessions: Required extension pattern for occasional remote attendance
- Recommended products: remote participant headset, BlackHole or Loopback-style routing, headphones or echo-controlled speaker setup

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

Assessment: Treat remote participants as additional isolated channels. This is compatible with the recommended budget lav/clip-on approach.

## Quantified Comparison

| Option | Cost | Within $500? | Attribution | ASR Quality | Setup | Friction | Talkovers | 5-Person Fit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Single room mic | $80-$350 | Yes | 45-65% | 2/5 | 1/5 | 1/5 | 1/5 | 1/5 |
| Budget boundary/table-zone mics | $150-$500 | Yes | 60-75% | 3/5 | 3/5 | 2/5 | 2/5 | 3/5 |
| Budget lav/clip-on 2TX/1RX kits | $270-$500 | Yes | 80-92% | 3-4/5 | 3/5 | 3/5 | 4/5 | 5/5 |
| Budget headset per participant | $100-$500 | Yes | 85-95% | 3/5 | 4/5 | 5/5 | 4/5 | 3/5 |
| Budget conference array | $100-$500 | Yes | 55-75% | 3/5 | 1/5 | 1/5 | 2/5 | 2/5 |
| Hybrid extension | $0-$150 incremental | Yes | 90-99% remote isolated | 3-5/5 | 3/5 | 2/5 | 4/5 | 5/5 |

The jump from a single room microphone to budget split-channel clip-on/lav capture is still dramatic: expected attribution improves from roughly 45-65% to roughly 80-92%, a practical gain of 25-45 percentage points. This improvement comes from mapping each known participant to a receiver/channel, not from better diarization.

More expensive professional lav/headset systems can improve reliability, backup recording, dynamic range, and isolation, but those options are explicitly out of scope for the initial project because they exceed the $500 hard cap.

## Recommended Products Under $500

Budget experiment:

- Buy one SYNCO G2(A2), Movo WMX-2-DUO, Hollyland Lark M1 Duo, or COMICA Vimo C3.
- Verify that transmitter A and transmitter B record as separate left/right channels on the Mac.
- Reject the product if it forces a mono mix.

Recommended initial 5-person setup:

- Three 2TX/1RX budget wireless kits with confirmed stereo/split output.
- Assign five participants to five transmitter positions and leave the sixth transmitter as spare.
- Capture each receiver's stereo output and split it into mono speaker channels in software.

Used/refurb upgrade within the same cap:

- Prefer used Rode Wireless GO II Dual kits or refurbished DJI Mic 2 kits when the total can stay under $500.
- These are better than no-name cheap kits because they are more likely to provide stable dual-channel behavior and onboard recording backup.

Products to avoid:

- Cheap phone-first "TikTok" lav kits that only say "dual microphones" or "real-time mixing."
- Any product that lacks stereo/split output or per-transmitter onboard recording.
- Any product that only exposes a forced mono USB-C/Lightning phone input.

## Decision

Use budget dual-transmitter wireless lav/clip-on kits as the architectural target for the initial project.

The initial hardware profile is:

- Three budget 2TX/1RX kits.
- Five active transmitters for five participants.
- Confirmed stereo/split output per receiver, mapped as left/right speaker channels.
- Optional sixth transmitter as spare.
- Diarization fallback only for bleed, missed routing, or recovery.

The software should continue to model speakers as configured channel mappings. It should not depend on professional hardware, and it should not assume the user can buy microphone systems costing more than $500.

Remote participants should be captured as their own isolated digital channels. Their call audio must not be played into the physical room unless the room capture path is echo-cancelled or headphones are used.

## Recommendations

Budget solution:

- One verified 2TX/1RX budget kit for proof of concept.
- Expected attribution: 80-90% for the two captured speakers if split stereo works.
- Use this to test Panther's channel mapping before buying the full five-person setup.

Recommended solution:

- Three verified 2TX/1RX budget kits with split stereo output, total cost target $270-$500.
- Expected attribution: 80-92%.
- This is the preferred hardware target for the project under the hard budget cap.

Best-practical solution within $500:

- Used/refurb Rode Wireless GO II Dual or DJI Mic 2 kits, if three kits can be sourced within the $500 cap.
- Expected attribution: 85-94%, mostly due to better reliability and onboard backup rather than fundamentally different channel mapping.
- If prices exceed $500, fall back to the recommended budget 2TX/1RX kits.

## Consequences

- The pipeline will model speakers as configured channel mappings.
- The capture layer should support splitting stereo receiver feeds into per-speaker mono streams.
- Diarization support is fallback logic, not the central design.
- The sample implementation will start with mock multichannel input so the data contracts can be tested without hardware.
- Future ingestion implementations should support CoreAudio, ffmpeg, stereo receiver splitting, multichannel WAV inputs, and synchronized per-speaker files.
