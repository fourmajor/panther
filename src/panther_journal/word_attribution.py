"""Evidence-preserving word attribution; no recognition or identity inference."""

import json
import math
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone


class Progress:
    def __init__(self, path, total):
        self.path, self.total = path, total
        self.completed = 0
        self.started = time.monotonic()
        self.write(0)

    def write(self, completed, status="running", error=None):
        self.completed = completed
        elapsed = time.monotonic() - self.started
        remaining = elapsed * (self.total - completed) / completed if completed else None
        now = datetime.now(timezone.utc)
        value = dict(
            schemaVersion=1,
            stage="word-attribution",
            status=status,
            completed=completed,
            total=self.total,
            unit="source segments",
            processingPercent=100 * completed / self.total if self.total else 100,
            elapsedSeconds=elapsed,
            estimatedRemainingSeconds=remaining if status != "failed" else None,
            estimatedCompletionAt=(now + timedelta(seconds=remaining)).isoformat()
            if remaining is not None and status != "failed"
            else None,
            updatedAt=now.isoformat(),
            error=error,
        )
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w") as out:
            json.dump(value, out, indent=2)
        temporary.chmod(0o600)
        temporary.replace(self.path)


def words(line, raw):
    """Return original text slices and measured token bounds; never interpolate words."""
    tokens = [t for t in raw.get("tokens", []) if t.get("id", 999999) < 50257]
    full = "".join(t["text"] for t in tokens)
    if full.strip() != line["text"].strip():
        return None
    origin = len(full) - len(full.lstrip())
    text = full.strip()
    spans, position = [], 0
    for token in tokens:
        end = position + len(token["text"])
        spans.append((position - origin, end - origin, token))
        position = end
    result = []
    previous = line["start"]
    for match in re.finditer(r"\S+", text):
        selected = [t for a, b, t in spans if a < match.end() and b > match.start()]
        try:
            start = min(t["offsets"]["from"] for t in selected) / 1000
            end = max(t["offsets"]["to"] for t in selected) / 1000
        except (KeyError, ValueError, TypeError):
            return None
        if not (
            math.isfinite(start)
            and math.isfinite(end)
            and line["start"] <= start < end <= line["end"]
            and start >= previous
        ):
            return None
        result.append((match.start(), match.end(), start, end))
        previous = end
    return result or None


def decision(start, end, turns, mapping, minimum, margin):
    """Score exclusive speech only; simultaneous voices never count for either person."""
    turns = [t for t in turns if t.start < end and t.end > start]
    points = sorted(
        {start, end} | {max(start, t.start) for t in turns} | {min(end, t.end) for t in turns}
    )
    durations = defaultdict(float)
    overlap = 0.0
    for a, b in zip(points, points[1:]):
        labels = {t.speaker for t in turns if t.start < b and t.end > a}
        if len(labels) == 1:
            durations[next(iter(labels))] += b - a
        elif len(labels) > 1:
            overlap += b - a
    ranked = sorted(durations.items(), key=lambda item: (-item[1], item[0]))
    duration = end - start
    best = ranked[0][1] / duration if ranked else 0
    second = ranked[1][1] / duration if len(ranked) > 1 else 0
    label = ranked[0][0] if ranked else None
    accepted = best >= minimum and best - second >= margin and overlap / duration <= 0.1
    return (
        label if accepted else None,
        mapping.get(label) if accepted else None,
        {
            "exclusiveCoverage": best,
            "runnerUpCoverage": second,
            "overlapCoverage": overlap / duration,
            "reason": "matched"
            if accepted and label in mapping
            else "unmapped-speaker"
            if accepted
            else "ambiguous-timing-or-overlap",
        },
    )


def attribute(lines, raw, turns, mapping, minimum=0.65, margin=0.25, progress=None):
    from panther_journal.recording import attributed_lines

    if not 0.5 < minimum <= 1 or not 0 <= margin <= 1:
        raise ValueError("Invalid attribution thresholds")
    evidence = [s for s in raw["transcription"] if s["text"].strip()]
    if len(evidence) != len(lines):
        raise ValueError("Timing evidence does not match source segment count")
    result, fallback = [], 0
    for index, (line, original) in enumerate(zip(lines, evidence)):
        if (
            original["text"].strip() != line["text"].strip()
            or abs(original["offsets"]["from"] / 1000 - line["start"]) > 0.001
            or abs(original["offsets"]["to"] / 1000 - line["end"]) > 0.001
        ):
            raise ValueError("Timing evidence does not match source text/times")
        pieces = words(line, original)
        relevant = [t for t in turns if t.start < line["end"] and t.end > line["start"]]
        if pieces is None:
            group = attributed_lines([line], relevant, mapping)[0]
            group.update(sourceSegmentIndex=index, timingMethod="whole-segment-fallback")
            result.append(group)
            fallback += 1
        else:
            groups = []
            for n, (a, b, start, end) in enumerate(pieces):
                label, player, detail = decision(start, end, relevant, mapping, minimum, margin)
                # Preserve the parent's entire time partition for comparable duration statistics.
                boundary_start = line["start"] if n == 0 else (pieces[n - 1][3] + start) / 2
                boundary_end = line["end"] if n == len(pieces) - 1 else (end + pieces[n + 1][2]) / 2
                char_start = 0 if n == 0 else pieces[n - 1][1]
                word = dict(
                    start=start,
                    end=end,
                    text=line["text"][char_start:b],
                    speakerLabel=label,
                    playerId=player,
                    **detail,
                )
                if groups and (groups[-1]["speakerLabel"], groups[-1]["playerId"]) == (
                    label,
                    player,
                ):
                    groups[-1]["text"] += word["text"]
                    groups[-1]["end"] = boundary_end
                    groups[-1]["wordAttribution"].append(word)
                else:
                    group = dict(
                        line,
                        start=boundary_start,
                        end=boundary_end,
                        text=word["text"],
                        speakerLabel=label,
                        playerId=player,
                        attribution="word-timing-confirmed-map" if player else "unassigned",
                        sourceSegmentIndex=index,
                        timingMethod="whisper-token-estimate",
                        wordAttribution=[word],
                    )
                    groups.append(group)
            if "".join(g["text"] for g in groups) != line["text"]:
                raise ValueError("Attribution altered source text")
            result.extend(groups)
        if progress and ((index + 1) % 100 == 0 or index + 1 == len(lines)):
            progress.write(index + 1)
    total = sum(s["end"] - s["start"] for s in lines)
    assigned = sum(s["end"] - s["start"] for s in result if s["playerId"])
    reasons = defaultdict(float)
    for segment in result:
        if segment["playerId"] is None:
            reason = (
                "unusable-word-timing"
                if segment["timingMethod"] == "whole-segment-fallback"
                else segment["wordAttribution"][0]["reason"]
            )
            reasons[reason] += segment["end"] - segment["start"]
    return result, dict(
        sourceSegments=len(lines),
        outputSegments=len(result),
        timingFallbackSegments=fallback,
        durationSeconds=total,
        assignedDurationSeconds=assigned,
        assignedDurationPercent=100 * assigned / total if total else 0,
        unassignedDurationSecondsByReason=dict(reasons),
        coverageIsNotAccuracy=True,
    )
