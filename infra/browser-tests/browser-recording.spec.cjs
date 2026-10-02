const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const os=require('node:os');
const {MODEL_VIEWER_BUNDLE_PATH}=require('../dist/lib/panther-media-explorer-stack');

const fakeMicrophone=path.join(os.tmpdir(),'panther-browser-synthetic-microphone.wav');
const fixturePcm=Buffer.alloc(44+32000*2);
fixturePcm.write('RIFF');fixturePcm.writeUInt32LE(fixturePcm.length-8,4);fixturePcm.write('WAVEfmt ',8);fixturePcm.writeUInt32LE(16,16);fixturePcm.writeUInt16LE(1,20);fixturePcm.writeUInt16LE(1,22);fixturePcm.writeUInt32LE(32000,24);fixturePcm.writeUInt32LE(64000,28);fixturePcm.writeUInt16LE(2,32);fixturePcm.writeUInt16LE(16,34);fixturePcm.write('data',36);fixturePcm.writeUInt32LE(64000,40);
for(let i=0;i<32000;i++) fixturePcm.writeInt16LE(Math.round(8192*Math.sin(2*Math.PI*440*i/32000)),44+i*2);
fs.writeFileSync(fakeMicrophone,fixturePcm);
test.use({launchOptions:{args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${fakeMicrophone}`]}});
let server,origin;
const headers={'access-control-allow-origin':'','access-control-allow-methods':'GET,POST,PUT,OPTIONS','access-control-allow-headers':'*'};

// AudioWorklet module requests bypass DevTools routing. Serve the real module on
// an isolated localhost origin rather than mocking capture or replacing its processor.
test.beforeAll(async()=>{
  server=http.createServer((request,response)=>{
    const name=new URL(request.url,origin || 'http://localhost').pathname;
    if(name==='/config.js') {response.setHeader('Content-Type','application/javascript');response.end(`window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"${origin}/"};`);return;}
    const file=name==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/pcm-capture-v1.js'].includes(name)?name.slice(1):'index.html');
    response.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html');response.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://127.0.0.1:${server.address().port}`;headers['access-control-allow-origin']=origin;
});
test.afterAll(async()=>{await new Promise(resolve=>server.close(resolve));});
async function fixture(page,transcriptionAvailable=true,failFinal=false) {
  const posts=[],files=new Map(),signed=new Map();let live=null,final=null,finalAttempts=0;
  await page.context().grantPermissions(['microphone'],{origin});
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-member'}))+'.test'})));
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**',async route=>{
    const request=route.request(),url=new URL(request.url()),name=url.pathname;
    const respond=(json,status=200)=>route.fulfill({json,status,headers});
    if(request.method()==='OPTIONS') return respond({});
    if(name==='/signed-upload') {
      const upload=signed.get(url.searchParams.get('id'));
      const raw=request.postDataBuffer();files.set(upload.filename,{raw,metadata:upload.metadata,size:upload.size});
      return respond({});
    }
    let body={};
    if(request.method()==='POST') {body=request.postDataJSON();posts.push({name,body});}
    if(name==='/games') return respond({games:[{id:'test-game',name:'Synthetic Campaign',purpose:'test',ruleset:'Synthetic System'}]});
    if(name==='/game') return respond({game:{id:'test-game',name:'Synthetic Campaign',purpose:'test'},players:[],characters:[],memberships:[],visualStyles:[],gameSettings:{description:null},canEditGame:false});
    if(name==='/browser-recording/capabilities') return respond({canRecord:true,transcriptionAvailable,model:'gpt-transcribe',chunkSeconds:15,maxParts:1000});
    if(name==='/assets') return respond({assets:[],cursor:null});
    if(name==='/recordings/live') return respond({recordings:[]});
    if(name==='/object-url') {
      const file=files.get(url.searchParams.get('key').split('/').at(-1));
      if(url.searchParams.get('key').endsWith('playback.mp3')) return respond({url:'https://test.execute-api.us-west-2.amazonaws.com/listening.wav'});
      return file?respond({size:file.size,metadata:file.metadata}):respond({error:'Not found'},404);
    }
    if(name==='/uploads') {
      signed.set(String(signed.size),body);
      return respond({url:`https://test.execute-api.us-west-2.amazonaws.com/signed-upload?id=${signed.size-1}`,headers:{'Content-Type':body.contentType}});
    }
    if(name==='/listening.wav') return route.fulfill({body:files.get('part-0000.wav').raw,contentType:'audio/wav',headers});
    if(name==='/browser-recording/complete') return respond({jobId:'verified-set',workflowVersion:2});
    if(name==='/browser-transcriptions') {
      if(request.method()==='POST') {
        if(body.mode==='live') live={id:'live-result',start:0,status:'DONE',text:'Synthetic live speech'};
        else {finalAttempts++;if(failFinal && finalAttempts===1) return respond({error:'Request unavailable'},503);final={id:'final-result',status:'DONE',text:'Fresh full pass'};}
        return respond({jobs:[body.mode==='live'?live:final]});
      }
      return url.searchParams.get('mode')==='final'?respond({jobs:final?[final]:[],transcriptKey:final?'games/test-game/assets/final/original/transcript.json':null}):respond({jobs:live?[live]:[],playback:url.searchParams.has('playbackJobId')?{status:'DONE',audioKey:'games/test-game/assets/copy/original/playback.mp3'}:null});
    }
    return respond({});
  });
  await page.goto(origin+'/games/test-game/audio');
  await expect(page.locator('#room-recorder')).toBeVisible();
  await expect(page.locator('#room-recorder').getByRole('button')).toHaveCount(1);
  await expect(page.locator('#room-result')).not.toBeVisible();
  await expect(page.locator('#room-recorder')).not.toContainText('Capture the session');
  await expect(page.locator('#room-recorder').getByRole('textbox')).toHaveCount(0);
  await expect(page.locator('#live-transcript')).not.toBeVisible();
  expect((await page.locator('#library-title').boundingBox()).y).toBeLessThan((await page.locator('#room-start').boundingBox()).y);
  return {posts,files};
}

for(const width of [1280,390]) {
  test(`live can be disabled and final ASR is independent at ${width}px`,async({page})=>{
    test.setTimeout(65000);
    await page.setViewportSize({width,height:900});
    const {posts,files}=await fixture(page);
    await expect(page.locator('#live-transcript')).toBeHidden();
    await expect(page.locator('#room-recorder')).not.toContainText('Capture the session');
    for(const id of ['room-start']) {
      const box=await page.locator('#'+id).boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(width);expect(box.height).toBeGreaterThanOrEqual(44);
      await expect(page.locator('#'+id)).toBeInViewport();
    }
    await page.locator('#room-start').click();
    await expect.poll(()=>page.evaluate(()=>roomCapture.recording?'Recording':document.querySelector('#room-status').textContent)).toBe('Recording');
    await expect(page.locator('#room-state')).toBeVisible();
    await expect(page.locator('#room-live-text')).toContainText('Synthetic live speech',{timeout:25000});
    await page.locator('#room-live-toggle').click();
    await expect(page.locator('#room-live-toggle')).toHaveAttribute('aria-pressed','false');
    await page.locator('#room-stop').click();
    await expect(page.locator('#room-audio-status')).toHaveText('Audio ready',{timeout:15000});
    await expect(page.locator('#room-final-link')).toBeVisible();
    const recordBox=await page.locator('#room-start').boundingBox(), resultBox=await page.locator('#room-result').boundingBox();
    expect(resultBox.y).toBeGreaterThanOrEqual(recordBox.y+recordBox.height);
    expect(resultBox.y-recordBox.y-recordBox.height).toBeLessThan(32);
    await expect(page.locator('#library-status')).toBeHidden();
    const calls=posts.filter(p=>p.name==='/browser-transcriptions');
    expect(calls.filter(p=>p.body.mode==='live')).toHaveLength(1);
    expect(calls.filter(p=>p.body.mode==='final')).toHaveLength(1);
    expect(calls.at(-1).body.playbackJobId).toBe('verified-set');
    const doc=JSON.parse(files.get('recording.json').raw.toString());
    expect(doc.entityType).toBe('BrowserRecording');expect(doc.sessionName).toMatch(/^Session · /);expect(doc.sessionId).toMatch(/^session-\d{4}-\d{2}-\d{2}-[a-f0-9]{8}$/);expect(doc.sourceFormat).toBe('wav');expect(doc.parts.length).toBeGreaterThanOrEqual(1);
    for(const part of doc.parts) {const raw=files.get(part.file).raw;expect(raw.subarray(0,4).toString()).toBe('RIFF');expect(raw.readUInt32LE(24)).toBe(32000);expect(raw.length).toBe(part.size);}
    await page.screenshot({path:test.info().outputPath(`browser-room-${width}.png`),fullPage:true});
  });
}

test('capture works without an OpenAI token and retains originals',async({page})=>{
  const {posts,files}=await fixture(page,false);
  await expect(page.locator('#room-live-toggle')).not.toBeVisible();
  await page.locator('#room-start').click();
  await expect.poll(()=>page.evaluate(()=>roomCapture.recording?'Recording':document.querySelector('#room-status').textContent)).toBe('Recording');
  await expect(page.locator('#room-state')).toBeVisible();
  await expect.poll(()=>page.locator('#room-level').evaluate(e=>e.value)).toBeGreaterThan(0);
  let release;const completing=new Promise(resolve=>{release=resolve;});
  await page.route('**/browser-recording/complete',async route=>{await completing;await route.fulfill({json:{jobId:'verified-set',workflowVersion:2},headers});});
  await page.locator('#room-stop').click();
  await expect(page.locator('#room-result')).toBeVisible();
  await expect(page.locator('#room-audio-status')).toHaveText('Saving audio…');
  expect((await page.locator('#room-result').boundingBox()).y).toBeGreaterThan((await page.locator('.room-controls').boundingBox()).y);
  release();
  await expect(page.locator('#room-audio-status')).toHaveText('Audio ready');
  expect(posts.some(p=>p.name==='/browser-transcriptions')).toBe(false);
  expect(files.has('recording.json')).toBe(true);
  expect(JSON.parse(files.get('recording.json').raw).sessionName).toMatch(/^Session · /);
  expect(await page.evaluate(()=>new Promise(resolve=>{const open=indexedDB.open('panther-room-audio-v1');open.onsuccess=()=>{const read=open.result.transaction('parts').objectStore('parts').getAll();read.onsuccess=()=>resolve(read.result.length);};}))).toBeGreaterThan(0);
});

test('failed full-pass request reuses immutable interrupted manifest',async({page})=>{
  const {posts,files}=await fixture(page,true,true);
  await page.locator('#room-start').click();
  await expect.poll(()=>page.evaluate(()=>roomCapture.recording?'Recording':document.querySelector('#room-status').textContent)).toBe('Recording');
  await expect(page.locator('#room-state')).toBeVisible();
  await expect.poll(()=>page.locator('#room-level').evaluate(e=>e.value)).toBeGreaterThan(0);
  await page.evaluate(()=>roomCapture.stop('Synthetic interruption warning.'));
  await expect(page.locator('#room-resume')).toBeVisible();
  const original=Buffer.from(files.get('recording.json').raw);
  expect(JSON.parse(original).status).toBe('interrupted');
  await page.locator('#room-resume').click();
  await expect(page.locator('#room-final-link')).toBeVisible();
  expect(files.get('recording.json').raw.equals(original)).toBe(true);
  expect(posts.filter(p=>p.name==='/browser-transcriptions' && p.body.mode==='final')).toHaveLength(2);
});
