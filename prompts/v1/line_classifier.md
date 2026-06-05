# Line Classifier Prompt v1

Classify each transcript line into exactly one label:

- GAME_CANON
- RULES_CHAT
- CHARACTER_DIALOGUE
- TABLE_LOGISTICS
- FOOD_DRINK
- FAMILY_PERSONAL
- JOKE_OOC
- UNCERTAIN

Prefer keeping story-relevant uncertainty. Do not classify a line as disposable table chatter if it may contain a clue, character choice, NPC fact, location fact, quest update, or rules decision that affects canon.

Return JSON with:

```json
{
  "line_id": "line-0001",
  "label": "GAME_CANON",
  "confidence": 0.82,
  "rationale": "Short reason"
}
```
