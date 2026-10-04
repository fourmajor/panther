"""Shared exact workflow-type summaries; records remain separate observations."""
from tag_management import timestamp
LABELS = {'session-finalization': 'Session finalization', 'editorial': 'Story & screen planning', 'model': '3D modeling', 'playback': 'Audio assembly', 'transcription': 'Transcription', 'video-production': 'Video finishing', 'video-generation': 'Video generation', 'scene-render': 'Scene video', 'episode-render': 'Episode assembly', 'narration': 'Narration', 'asset-generation': 'Asset generation', 'transcript-summary': 'Transcript summary'}


def summary(kind, records):
    counts = {state: 0 for state in ('done', 'failed', 'running', 'queued', 'paused', 'pending', 'unknown')}
    latest_run = latest_activity = 0
    for row in records:
        state = row.get('status', 'unknown')
        counts[state if state in counts else 'unknown'] += 1
        latest_run = max(latest_run, int(timestamp(row.get('createdAt'))))
        latest_activity = max(latest_activity, int(timestamp(row.get('reportedAt') or row.get('createdAt'))))
    return {'schemaVersion': 1, 'id': kind, 'name': LABELS.get(kind, kind.replace('-', ' ').title()), 'total': sum(counts.values()), 'successful': counts['done'], 'failed': counts['failed'], 'active': counts['running'] + counts['queued'], 'counts': counts, 'latestRunAt': latest_run or None, 'latestActivityAt': latest_activity or None}
