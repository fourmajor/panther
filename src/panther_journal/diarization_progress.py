"""Lightweight, private progress snapshots; usable from the separate audio runtime."""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
import uuid


class Progress:
    def __init__(self, path, *, clock=time.monotonic, interval=2.0):
        self.path = Path(path)
        self.clock, self.interval = clock, interval
        self.started = clock()
        self.last_write = -math.inf
        self.last_stage = None
        self.last_counts = (None, None)
        self.completed_stages = []

    def update(self, stage, *, completed=None, total=None, state='running', force=False):
        now = self.clock()
        if not force and state == 'running' and stage == self.last_stage and now - self.last_write < self.interval:
            return
        percent = None
        if state in {'failed', 'interrupted'} and stage == self.last_stage and completed is None and total is None:
            completed, total = self.last_counts
        if completed is not None and total is not None:
            if any(isinstance(v, bool) or not math.isfinite(v) or int(v) != v or v < 0 for v in (completed, total)):
                raise ValueError('Invalid progress counters')
            completed, total = min(int(completed), int(total)), int(total)
            percent = round(100 * completed / total, 2) if total else None
        else:
            completed = total = None
        document = {
            'schemaVersion': 1, 'entityType': 'SpeakerDetectionProgress', 'state': state,
            'stage': stage, 'completed': completed, 'total': total, 'stagePercent': percent,
            'overallPercent': 100 if state == 'complete' else None,
            'completedStages': list(self.completed_stages),
            'elapsedSeconds': round(now - self.started, 2),
            'updatedAt': datetime.now(timezone.utc).isoformat(),
            'note': 'Percent describes this stage only, not overall completion. This is not a resumable model checkpoint.',
        }
        temporary = self.path.with_name(f'.progress-{uuid.uuid4().hex}.tmp')
        try:
            with temporary.open('x') as stream:
                json.dump(document, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.last_write, self.last_stage = now, stage
        self.last_counts = (completed, total)

    def __call__(self, step_name, step_artifact=None, *, completed=None, total=None, **kwargs):
        # Never serialize tensors, audio, embeddings, or the pipeline's `file` context.
        known = {'segmentation', 'speaker_counting', 'embeddings', 'discrete_diarization'}
        stage = step_name if step_name in known else 'pipeline'
        if completed is not None and total is not None:
            self.update(stage, completed=completed, total=total, force=completed == 0 or completed >= total)
            return
        if stage not in self.completed_stages:
            self.completed_stages.append(stage)
        following = {'segmentation': 'speaker-counting', 'speaker_counting': 'embeddings',
                     'embeddings': 'clustering', 'discrete_diarization': 'finalizing'}
        self.update(following.get(stage, 'pipeline'), force=True)
