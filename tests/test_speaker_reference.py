from panther_journal.speaker_reference import exclusive_speech, reference_embeddings


def _audio():
    # Three seconds: speaker A, then speaker B, then speaker A again.
    return [0.0] * 16000 + [1.0] * 16000 + [2.0] * 16000


def _turns():
    return [
        {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
        {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
        {"start": 2.0, "end": 3.0, "speaker": "SPEAKER_00"},
    ]


def test_reference_embedding_uses_that_speakers_exclusive_speech_not_a_centroid():
    seen = {}

    def embed(speech):
        seen[len(seen)] = list(speech[:8]) + list(speech[-4:])
        return [1.0, 0.0]

    embeddings, unavailable = reference_embeddings(embed, _audio(), _turns())
    assert unavailable == {}
    assert embeddings == {"SPEAKER_00": [1.0, 0.0], "SPEAKER_01": [1.0, 0.0]}
    # Equal-length turns stay in timeline order. Speaker 00 is the first second, then the third.
    assert seen[0][:4] == [0.0, 0.0, 0.0, 0.0]
    assert seen[0][-4:] == [2.0, 2.0, 2.0, 2.0]
    assert set(seen[1]) == {1.0}


def test_short_exclusive_speech_stays_unavailable_instead_of_inventing_a_vector():
    embeddings, unavailable = reference_embeddings(
        lambda _speech: [1.0], [0.0] * 8000, [{"start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"}]
    )
    assert embeddings == {"SPEAKER_00": None}
    assert unavailable["SPEAKER_00"]["reason"] == "insufficient-exclusive-speech"


def test_extractor_failure_keeps_the_speaker_unknown():
    def embed(_speech):
        raise RuntimeError("weights unavailable")

    embeddings, unavailable = reference_embeddings(
        embed, [0.25] * 16000, [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]
    )
    assert embeddings["SPEAKER_00"] is None
    assert unavailable["SPEAKER_00"] == {
        "reason": "reference-extraction-failed",
        "errorType": "RuntimeError",
    }
    assert "weights" not in str(unavailable)


def test_exclusive_speech_caps_the_longest_turns():
    samples = [float(index) for index in range(16000 * 4)]
    turns = [
        {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
        {"start": 1.0, "end": 4.0, "speaker": "SPEAKER_00"},
    ]
    speech = exclusive_speech(samples, turns, "SPEAKER_00", max_seconds=1.5)
    assert len(speech) == int(1.5 * 16000)
    assert speech[0] == 16000.0
