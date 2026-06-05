from panther_journal.config import load_config
from panther_journal.pipeline.factory import audio_ingestor, llm_provider
from panther_journal.pipeline.filtering import filter_game_lines


def test_mock_pipeline_filters_sample_ids() -> None:
    config = load_config("config/example.yaml")
    raw = audio_ingestor("mock").ingest(config)
    classified = [llm_provider("mock").classify_line(line) for line in raw]
    filtered = filter_game_lines(classified, config)

    assert [line.id for line in filtered] == [
        "line-0001",
        "line-0002",
        "line-0003",
        "line-0004",
        "line-0006",
        "line-0007",
        "line-0009",
        "line-0010",
    ]
