from panther_journal import whisper_runtime as whisper


def test_command_uses_turbo_search_and_carries_a_name_prompt():
    command = whisper.command(
        "whisper-cli",
        "weights.bin",
        "input.wav",
        "recognizer",
        prompt="Names: Ada, Harbor",
        use_gpu=True,
    )
    assert command[command.index("-bs") + 1] == "5"
    assert command[command.index("-bo") + 1] == "5"
    assert command[command.index("-mc") + 1] == "224"
    assert "-ng" not in command
    assert command[command.index("--prompt") + 1] == "Names: Ada, Harbor"
    cpu = whisper.command("whisper-cli", "weights.bin", "input.wav", "recognizer", use_gpu=False)
    assert "-ng" in cpu and "--prompt" not in cpu


def test_catalog_prompt_includes_players_places_and_items():
    prompt = whisper.catalog_names(
        {
            "characters": [{"name": "Ada Voss", "aliases": ["Captain Ada"]}],
            "locations": ["Grey Harbor"],
            "npcs": [{"title": "Lighthouse Keeper"}],
            "items": ["Signal Lantern"],
        },
        [{"id": "player-1", "name": "Example Player"}],
    )
    for name in ("Ada Voss", "Captain Ada", "Grey Harbor", "Lighthouse Keeper", "Signal Lantern", "Example Player"):
        assert name in prompt
    assert "player-1" not in prompt


def test_repeated_or_low_confidence_text_resets_context():
    base = "Names: Ada"
    looping = "the the the the " * 4
    reset, cleared = whisper.carry(base, [{"text": looping}], {"transcription": [{"avg_logprob": -0.2}]})
    assert cleared and reset == base
    quiet, cleared = whisper.carry(base, [{"text": "Ada opened the harbor gate."}], {"transcription": [{"avg_logprob": -1.4}]})
    assert cleared and quiet == base
    carried, cleared = whisper.carry(base, [{"text": "Ada opened the harbor gate."}], {"transcription": [{"avg_logprob": -0.2}]})
    assert not cleared and "harbor gate" in carried and carried.startswith(base)


def test_model_cache_reuses_a_complete_file_and_rejects_a_short_download(tmp_path):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def read(self, _size):
            block, self.payload = self.payload[:8], self.payload[8:]
            return block

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    ready = tmp_path / whisper.MODEL_NAME
    ready.write_bytes(b"x" * 32)
    assert whisper.ensure_model(tmp_path, minimum_bytes=16) == ready
    ready.unlink()

    def opener(_url, timeout=0):
        assert timeout
        return Response(b"y" * 16)

    cached = whisper.ensure_model(tmp_path, opener=opener, minimum_bytes=16)
    assert cached.read_bytes() == b"y" * 16

    def short(_url, timeout=0):
        return Response(b"nope")

    try:
        whisper.ensure_model(tmp_path / "again", opener=short, minimum_bytes=16)
    except OSError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("short download was accepted")
