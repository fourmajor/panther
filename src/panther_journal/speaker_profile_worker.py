"""Bounded local speaker analysis, executed only inside the isolated audio runtime."""

import argparse
import json
import os
import sys
from pathlib import Path
import wave

os.environ.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', PYANNOTE_METRICS_ENABLED='0')


def process(pipeline, device, audio, output, reference=False):
    import numpy as np
    import torch
    with wave.open(audio, 'rb') as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getframerate() != 16000:
            raise ValueError('Supply mono 16 kHz PCM16 WAV')
        if not 0 < stream.getnframes() <= 120 * 16000:
            raise ValueError('Speaker analysis accepts at most 120 seconds per chunk/sample')
        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
    result = pipeline({'waveform': torch.from_numpy(samples).unsqueeze(0), 'sample_rate': 16000})
    labels = result.speaker_diarization.labels()
    document = {'inferenceDevice': device, 'turns': [{'start': float(t.start), 'end': float(t.end), 'speaker': s}
                          for t, _, s in result.speaker_diarization.itertracks(yield_label=True)],
                'embeddings': {s: result.speaker_embeddings[i].tolist() for i, s in enumerate(labels)}}
    if reference:
        # Only an explicitly confirmed single-speaker enrollment may use the whole waveform.
        # Preserve diarization evidence separately; its clustering vector is not this reference.
        document['referenceEmbedding'] = pipeline._embedding(
            torch.from_numpy(samples).reshape(1, 1, -1)
        )[0].tolist()
        document['referenceEmbeddingMethod'] = 'community-1-confirmed-full-waveform-v1'
    temporary = Path(output + '.partial')
    with temporary.open('x') as stream:
        json.dump(document, stream, allow_nan=False)
    # Link publishes only a complete file, without replacing any previous result.
    os.link(temporary, output)
    temporary.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio')
    parser.add_argument('--model', required=True)
    parser.add_argument('--output')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--reference', action='store_true')
    args = parser.parse_args()
    if args.reference and args.serve:
        parser.error('Reference extraction is only for explicit enrollment, not live recognition')
    import torch
    from pyannote.audio import Pipeline
    torch.set_num_threads(2)
    pipeline = Pipeline.from_pretrained(args.model)
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    pipeline.to(torch.device(device))
    if device == 'mps':
        pipeline.segmentation_batch_size = 8
        pipeline.embedding_batch_size = 8
    if args.serve:
        for line in sys.stdin:
            request = json.loads(line)
            process(pipeline, device, request['audio'], request['output'])
    else:
        process(pipeline, device, args.audio, args.output, reference=args.reference)


if __name__ == '__main__':
    main()
