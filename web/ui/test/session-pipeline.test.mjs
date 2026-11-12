import {test} from 'node:test';
import assert from 'node:assert/strict';
import {cardText, cardTone, presentation, runIdentity, sessionHeadline, statusText} from '../src/session-pipeline-model.js';

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

test('a session headline is its name or date, and a pipeline card keeps the run separate', () => {
  assert.equal(sessionHeadline('Night one', 'session-one'), 'Night one');
  assert.equal(sessionHeadline('session-2026-10-15', 'session-2026-10-15'), '2026-10-15');
  assert.equal(sessionHeadline('', ''), 'Session');
  assert.equal(cardTone('done'), 'done');
  assert.equal(cardTone('failed'), 'failed');
  assert.equal(cardTone('started'), 'pending');
  assert.equal(cardText({status: 'pending'}), 'Not started');
  assert.equal(cardText({status: 'failed', stage: {title: 'Novel chapter', status: 'failed'}}), 'Failed · Novel chapter');
  assert.equal(cardText({status: 'started', stage: {id: 'context', title: 'Context selection', status: 'pending'}}), 'Context selection');
  assert.equal(runIdentity({id: 'editorial~66d4b374'}), '66d4b374');
  assert.equal(runIdentity(null), null);
});
