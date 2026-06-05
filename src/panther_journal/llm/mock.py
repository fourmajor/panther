from __future__ import annotations

from panther_journal.contracts import ClassifiedLine, Confidence, LineType, LoreFact, TranscriptLine
from panther_journal.llm.base import LLMProvider


class MockLLMProvider(LLMProvider):
    def classify_line(self, line: TranscriptLine) -> ClassifiedLine:
        text = line.text.lower()
        label = LineType.UNCERTAIN
        rationale = "No deterministic rule matched."
        confidence = 0.55

        if any(token in text for token in ["initiative", "roll", "armor class", "spell slot"]):
            label = LineType.RULES_CHAT
            rationale = "Line discusses mechanics or rolls."
            confidence = 0.86
        elif any(token in text for token in ["pizza", "drink", "chips"]):
            label = LineType.FOOD_DRINK
            rationale = "Line is food or drink table chatter."
            confidence = 0.93
        elif any(token in text for token in ["bathroom", "break", "pause"]):
            label = LineType.TABLE_LOGISTICS
            rationale = "Line is table logistics."
            confidence = 0.9
        elif any(token in text for token in ["my kid", "work meeting", "school pickup"]):
            label = LineType.FAMILY_PERSONAL
            rationale = "Line is personal non-game chatter."
            confidence = 0.9
        elif line.text.startswith('"') or "nyx says" in text or "bram says" in text:
            label = LineType.CHARACTER_DIALOGUE
            rationale = "Line is spoken in character."
            confidence = 0.88
        elif any(
            token in text
            for token in ["lantern", "mill", "briarwall", "cult", "clue", "door", "sigil"]
        ):
            label = LineType.GAME_CANON
            rationale = "Line contains story-world state."
            confidence = 0.84

        return ClassifiedLine(**line.model_dump(), label=label, classifier_confidence=confidence, rationale=rationale)

    def extract_lore(self, lines: list[ClassifiedLine]) -> list[LoreFact]:
        facts: list[LoreFact] = []
        accepted = [
            line
            for line in lines
            if line.label in {LineType.GAME_CANON, LineType.CHARACTER_DIALOGUE, LineType.RULES_CHAT}
        ]

        def matching(*needles: str) -> list[ClassifiedLine]:
            return [line for line in accepted if any(needle in line.text.lower() for needle in needles)]

        lantern = matching("lantern")
        if lantern:
            facts.append(
                LoreFact(
                    type="item",
                    name="Green-glass lantern",
                    session_id=lantern[0].session_id,
                    timestamp_start=lantern[0].timestamp_start,
                    timestamp_end=lantern[-1].timestamp_end,
                    facts=["A green-glass lantern was found beneath the old mill."],
                    status="active clue",
                    confidence=Confidence.CONFIRMED,
                    source_line_ids=[line.id for line in lantern],
                )
            )

        mill = matching("mill")
        if mill:
            facts.append(
                LoreFact(
                    type="location",
                    name="Old mill under Briarwall",
                    session_id=mill[0].session_id,
                    timestamp_start=mill[0].timestamp_start,
                    timestamp_end=mill[-1].timestamp_end,
                    facts=["The party investigated a hidden space below the old mill."],
                    status="visited",
                    confidence=Confidence.CONFIRMED,
                    source_line_ids=[line.id for line in mill],
                )
            )

        cult = matching("cult", "sigil")
        if cult:
            facts.append(
                LoreFact(
                    type="faction",
                    name="Ashen Sigil cult",
                    session_id=cult[0].session_id,
                    timestamp_start=cult[0].timestamp_start,
                    timestamp_end=cult[-1].timestamp_end,
                    facts=["The Ashen Sigil cult is connected to markings found near the mill."],
                    status="suspected threat",
                    confidence=Confidence.INFERRED,
                    source_line_ids=[line.id for line in cult],
                )
            )

        return facts
