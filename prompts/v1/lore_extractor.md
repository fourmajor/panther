# Lore Extractor Prompt v1

Extract grounded campaign memory from filtered transcript lines only. Do not infer critical facts unless marked as `inferred` or `uncertain`.

Return an array of JSON objects with:

```json
{
  "type": "npc | pc | location | faction | item | clue | quest | event | rule_note",
  "name": "Name",
  "session_id": "session id",
  "timestamp_start": 0.0,
  "timestamp_end": 0.0,
  "facts": ["Grounded fact"],
  "status": "active",
  "confidence": "confirmed | inferred | uncertain",
  "source_line_ids": ["line-0001"]
}
```
