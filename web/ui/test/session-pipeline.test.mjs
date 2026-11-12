import {test} from 'node:test';
import assert from 'node:assert/strict';
import {presentation, statusText} from '../src/session-pipeline-model.js';

test('pipeline colors use success, failure, running, and gray for everything else', () => {
  assert.equal(presentation('done'), 'done');
  assert.equal(presentation('failed'), 'failed');
  assert.equal(presentation('running'), 'running');
  for (const status of ['pending', 'queued', 'paused', 'unknown', undefined]) assert.equal(presentation(status), 'pending');
  assert.equal(statusText('paused'), 'Waiting');
  assert.equal(statusText('failed'), 'Failed');
});
