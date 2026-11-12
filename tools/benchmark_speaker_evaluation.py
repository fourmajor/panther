"""Synthetic-only scorer benchmark. No audio, model, credentials or provider calls."""

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]

from panther_journal.speaker_evaluation import evaluate  # noqa: E402
from test_speaker_evaluation_sweep import scan_oracle  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intervals', type=int, default=3000)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.intervals <= 10000 or not 1 <= args.repeats <= 5:
        parser.error('Use 1–10000 intervals and 1–5 repeats')
    truth, prediction = [], []
    for i in range(args.intervals):
        person = None if i % 10 == 0 else f'fixture-{i % 5}'
        truth.append(dict(start=i * 4, end=i * 4 + 3, playerId=person,
                          confirmed=True, identityEvidence='Synthetic benchmark', context='playback'))
        for offset, length in ((0, 1.5), (1, 1.6), (2.5, 1.0)):
            prediction.append(dict(start=i * 4 + offset, end=i * 4 + offset + length,
                                   playerId=person if offset != 1 else None))
    expected, people = scan_oracle(truth, prediction)
    result = evaluate(truth, prediction)
    assert all(result[k] == value for k, value in expected.items())
    assert result['perPlayer'] == people
    timings = {}
    for name, function in [('scanOracle', scan_oracle), ('eventSweep', evaluate)]:
        samples = []
        for _ in range(args.repeats):
            start = time.perf_counter()
            function(truth, prediction)
            samples.append(time.perf_counter() - start)
        timings[name] = dict(samplesSeconds=samples, medianSeconds=statistics.median(samples))
    print(json.dumps(dict(referenceIntervals=len(truth), predictionIntervals=len(prediction),
                          repeats=args.repeats, timings=timings,
                          speedup=timings['scanOracle']['medianSeconds'] / timings['eventSweep']['medianSeconds'],
                          exactMetricParity=True, scope='Synthetic evaluation scoring only; not model inference or identity accuracy'), indent=2))


if __name__ == '__main__':
    main()
