import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import test from 'node:test';
const {publicRead}=require('../../deployed-tests/safety.cjs');

test('deployed QA cannot leak synthetic credentials to private assets or external services',()=>{
  for(const url of ['https://panther.place/app.js','https://panther.place/releases/abcd/styles.css','https://panther.place/avatars/cat.svg'])assert.equal(publicRead(url,'GET'),true);
  assert.equal(publicRead('https://panther.place/games/qa-campaign/sessions','GET',true),true);
  for(const url of ['https://provider.example/generate','https://test.s3.amazonaws.com/private.wav','http://panther.place/app.js','https://fake.panther.place/app.js','https://panther.place/games/private/assets/portrait.png','https://panther.place/auth/refresh','https://panther.place/__qa__/transcript.txt','https://user:secret@panther.place/app.js'])assert.equal(publicRead(url,'GET'),false,url);
  assert.equal(publicRead('https://panther.place/games/private/sessions','GET',true),false);
  for(const method of ['POST','PUT','PATCH','DELETE','OPTIONS'])assert.equal(publicRead('https://panther.place/app.js',method),false);
});

test('nightly quality is scoped to reviewed source, owned runners and read-only permissions',()=>{
  const workflow=readFileSync(path.join(__dirname,'../../../.github/workflows/ci.yml'),'utf8');
  assert.match(workflow,/schedule:\s*\n\s*- cron:/);assert.match(workflow,/github\.event_name == 'schedule' && github\.ref == 'refs\/heads\/main'/);
  assert.doesNotMatch(workflow,/pull_request:|pull_request_target:|push:/);assert.doesNotMatch(workflow,/contents: write|issues: write|runs-on: ubuntu/);
  assert.match(workflow,/runs-on: \[self-hosted, Linux, panther-local\]/);assert.match(workflow,/contents: read/);assert.match(workflow,/cancel-in-progress: false/);
  assert.match(workflow,/Deployed website journeys/);assert.match(workflow,/npm run test:deployed/);assert.match(workflow,/deployed-journey-results/);
});
