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
  assert.equal(statusText('running'), 'Running');
  assert.equal(statusText('done'), 'Done');
});

test('storyboard approval stays a gate and does not look finished or running', () => {
  assert.equal(presentation('paused', 'storyboard-approval'), 'gate');
  assert.equal(presentation('queued', 'storyboard-approval'), 'gate');
  assert.equal(presentation('done', 'storyboard-approval'), 'done');
  assert.equal(presentation('pending', 'video-generation'), 'pending');
  assert.equal(statusText('paused', 'storyboard-approval'), 'Needs approval');
  assert.equal(statusText('pending', 'video-generation'), 'Not started');
});
