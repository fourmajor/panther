const {test,expect}=require('@playwright/test');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
let server,origin,directory;
test.beforeEach(async()=>{
  directory=fs.mkdtempSync(path.join(os.tmpdir(),'panther-development-browser-'));
  server=spawn('python3',[path.resolve(__dirname,'../../tools/dev_server.py'),'--port','0','--database',path.join(directory,'development.sqlite')],{stdio:['ignore','pipe','pipe']});
  origin=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('Development server did not start')),10000);
    server.once('exit',code=>{clearTimeout(timer);reject(new Error(`Development server exited ${code}`));});
    server.stdout.on('data',chunk=>{const match=chunk.toString().match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});
  });
});
test.afterEach(async()=>{if(server && server.exitCode===null) await new Promise(resolve=>{server.once('exit',resolve);server.kill();});if(directory)fs.rmSync(directory,{recursive:true,force:true});});

for(const width of [1280,390]) test(`development data comes from the database and edits survive a reload at ${width}px`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:900});
  await page.goto(origin+'/account');
  await page.getByRole('button',{name:'Regenerate demo data'}).click();
  await expect(page.getByText('Demo data regenerated.',{exact:true})).toBeVisible();
  await page.goto(origin+'/games/preview-campaign/settings');
  await expect(page.locator('#game-name')).toHaveValue('The Lantern Campaign');
  await page.locator('#game-name').fill('Lantern adventures');
  await page.getByRole('button',{name:'Save game details'}).click();
  await expect(page.locator('#game-settings-status')).toContainText('saved');
  await page.reload();
  await expect(page.locator('#game-name')).toHaveValue('Lantern adventures');
  await page.screenshot({path:testInfo.outputPath(`development-settings-${width}.png`),fullPage:true});
  await expect(page.locator('#game-ruleset')).toBeHidden();
  await expect(page.locator('#game-purpose')).toBeHidden();
  await expect(page.locator('#username')).toBeHidden();
  await expect(page.getByText(/sample data|Example Fantasy System|Your game, your world/i)).toHaveCount(0);
  await page.goto(origin+'/games/preview-campaign/characters');
  await page.getByRole('button',{name:'Create Character',exact:true}).click();
  await page.locator('#character-create-form').getByLabel('Character name').fill('Ash Meadow');
  await page.getByRole('button',{name:'Create Character',exact:true}).click();
  await expect(page.locator('#character-name')).toHaveText('Ash Meadow');
  await page.reload();
  await expect(page.locator('#character-name')).toHaveText('Ash Meadow');
  await page.screenshot({path:testInfo.outputPath(`development-character-${width}.png`),fullPage:true});
  await page.goto(origin+'/games/preview-campaign/novel');
  await page.getByRole('button',{name:'Create Chapter',exact:true}).filter({visible:true}).click();
  await page.locator('#manual-chapter-form').getByLabel('Chapter title').fill('The northern gate');
  await page.locator('#manual-chapter-form').getByLabel('Chapter text').fill('A lantern burned beside the northern gate.');
  await page.locator('#manual-chapter-form').getByRole('button',{name:'Create Chapter',exact:true}).click();
  await expect(page.locator('#novel-title')).toHaveText('The northern gate');
  await page.reload();
  await expect(page.locator('#novel-prose')).toContainText('A lantern burned');
  await page.screenshot({path:testInfo.outputPath(`development-chapter-${width}.png`),fullPage:true});
  await page.goto(origin+'/games/preview-campaign/episodes');
  await page.getByRole('button',{name:'Create Episode',exact:true}).click();
  await page.getByLabel('Episode title',{exact:true}).fill('The northern gate');
  await page.locator('form').filter({has:page.getByLabel('Episode title',{exact:true})}).getByRole('button',{name:'Create Episode',exact:true}).click();
  await page.getByRole('button',{name:'Create Scene',exact:true}).click();
  await page.getByLabel('Scene title',{exact:true}).fill('Ash Meadow watches the northern gate');
  await page.locator('form').filter({has:page.getByLabel('Scene title',{exact:true})}).getByRole('button',{name:'Create Scene',exact:true}).click();
  await expect(page.locator('#scene-video-composer')).toBeVisible();
  const videoComposer=page.locator('#scene-video-composer');
  await page.getByRole('button',{name:'Edit scene',exact:true}).click();
  const sceneEditor=page.getByRole('form',{name:'Scene editor'});
  await sceneEditor.getByRole('combobox',{name:'Characters',exact:true}).click();
  await page.getByRole('option',{name:'Ash Meadow',exact:true}).click();
  await sceneEditor.getByRole('button',{name:'Save changes',exact:true}).click();
  await expect(page.locator('.selected-scene').getByRole('heading',{name:'Ash Meadow watches the northern gate',exact:true})).toBeVisible();
  await expect(videoComposer.locator('textarea')).toHaveCount(0);
  await videoComposer.locator('form').getByRole('button',{name:'Generate',exact:true}).click();
  await expect(page.locator('#scene-video-composer form')).toBeHidden();
  await expect(page.locator('#scene-work-progress')).toContainText('Waiting to start');
  await expect(page.locator('#scene-work-progress').getByRole('progressbar',{name:'Video generation stages'})).toBeVisible();
  const queued=await page.request.get(origin+'/scene-renders?gameId=preview-campaign',{headers:{Authorization:'Bearer isolated-development-test'}});
  expect(queued.ok()).toBe(true);const jobs=(await queued.json()).jobs;expect(jobs).toHaveLength(1);expect(jobs[0]).toMatchObject({status:'QUEUED',prompt:'Ash Meadow watches the northern gate'});expect(jobs[0].outputKey).toBeUndefined();
  await page.reload();
  await expect(page.getByText('The northern gate',{exact:true}).filter({visible:true}).first()).toBeVisible();
  await expect(page.locator('#scene-work-progress')).toContainText('Waiting to start');
  await page.goto(origin+'/games/preview-campaign/dashboard');
  await expect(page.locator('#dashboard-sections').getByRole('link',{name:'The northern gate'})).toBeVisible();
  await expect(page.locator('#dashboard-sections').getByRole('link',{name:'Ash Meadow'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({path:testInfo.outputPath(`development-dashboard-${width}.png`),fullPage:true});
});

for(const width of [1280,390])test(`Real local map upload feeds a pinned scene after reload at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});await page.goto(origin+'/account');await page.getByRole('button',{name:'Regenerate demo data'}).click();await expect(page.getByText('Demo data regenerated.',{exact:true})).toBeVisible();
 await page.goto(origin+'/games/preview-campaign/assets');const library=page.getByRole('region',{name:'Assets',exact:true});await library.getByRole('button',{name:'Maps',exact:true}).click();await page.getByRole('button',{name:'Upload',exact:true}).click();const form=page.getByRole('form',{name:'Upload asset',exact:true});await form.getByLabel('Name (optional)',{exact:true}).fill('Northern route');
 const png=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=480;canvas.height=240;const c=canvas.getContext('2d');c.fillStyle='#e6d5aa';c.fillRect(0,0,480,240);c.fillStyle='#39392e';c.font='20px serif';c.fillText('Harbor',40,180);c.fillText('Hills',340,60);return canvas.toDataURL('image/png').split(',')[1];});await form.getByLabel('File',{exact:true}).setInputFiles({name:'route.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});await form.getByRole('button',{name:'Upload asset',exact:true}).click();await expect(library.getByRole('button',{name:'Northern route Map · PNG',exact:true})).toBeVisible();const mapCard=library.getByRole('button',{name:'Northern route Map · PNG',exact:true});await expect(mapCard.locator('img')).toBeVisible();await expect.poll(()=>mapCard.locator('img').evaluate(image=>image.complete&&image.naturalWidth)).toBe(480);await page.reload();await expect(mapCard).toBeVisible();await expect(mapCard.locator('img')).toBeVisible();await expect.poll(()=>mapCard.locator('img').evaluate(image=>image.complete&&image.naturalWidth)).toBe(480);
 await page.goto(origin+'/games/preview-campaign/episodes');await page.getByRole('button',{name:'Create Episode',exact:true}).click();await page.getByLabel('Episode title',{exact:true}).fill('A journey');await page.getByRole('form',{name:'Episode editor'}).getByRole('button',{name:'Create Episode',exact:true}).click();await page.getByRole('button',{name:'Create Scene',exact:true}).click();const editor=page.getByRole('form',{name:'Scene editor'});await editor.getByLabel('Scene title',{exact:true}).fill('Travel from Harbor to Hills');await editor.getByRole('combobox',{name:'Scene type',exact:true}).click();await page.getByRole('option',{name:'Map',exact:true}).click();await editor.getByRole('combobox',{name:'Map image',exact:true}).click();await page.getByRole('option',{name:'Northern route',exact:true}).click();await editor.getByRole('button',{name:'Create Scene',exact:true}).click();await expect(page.locator('#scene-video-composer')).toBeVisible();const composer=page.locator('#scene-video-composer');await expect(composer.getByRole('img',{name:'Northern route',exact:true})).toBeVisible();await composer.getByRole('button',{name:'Generate',exact:true}).click();await expect(composer.locator('form')).toBeHidden();await expect(page.locator('#scene-work-progress')).toContainText('Waiting to start');const renders=await page.request.get(origin+'/scene-renders?gameId=preview-campaign',{headers:{Authorization:'Bearer isolated-development-test'}});expect(renders.ok()).toBe(true);const jobs=(await renders.json()).jobs;expect(jobs).toHaveLength(1);expect(jobs[0]).toMatchObject({status:'QUEUED',sceneType:'map',prompt:'Travel from Harbor to Hills'});expect(jobs[0].mapPin.key).toMatch(/\/original\/route\.png$/);expect(jobs[0].mapPin.sha256).toMatch(/^[A-Za-z0-9+/]{43}=$/);expect(jobs[0].inputRefs).toContainEqual(jobs[0].mapPin);await page.reload();await expect(page.locator('#scene-work-progress')).toContainText('Waiting to start');
 await page.goto(origin+'/games/preview-campaign/assets');await expect(page.getByRole('button',{name:'Generate',exact:true})).toBeDisabled();const imageJobs=await page.request.get(origin+'/asset-generation?gameId=preview-campaign',{headers:{Authorization:'Bearer isolated-development-test'}});expect(imageJobs.ok()).toBe(true);expect((await imageJobs.json()).jobs).toEqual([]);await expect(page.getByRole('button',{name:'Open asset',exact:true})).toHaveCount(0);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:testInfo.outputPath(`real-local-assets-${width}.png`),fullPage:true});
});

for(const width of [1280,390]) test(`chapter generation polls its submitted non-preview game and denies another game at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});const headers={Authorization:'Bearer synthetic-development-test'};
 const games=[{id:'northern-chronicle',name:'Northern Chronicle'},{id:'southern-chronicle',name:'Southern Chronicle'}];
 for(const game of games){const response=await page.request.post(origin+'/games',{headers,data:{...game,purpose:'campaign',players:[],characters:[],memberships:[]}});expect(response.ok()).toBe(true);}
 const reads=[];page.on('request',request=>{const url=new URL(request.url());if(url.pathname==='/editorial-jobs'&&request.method()==='GET')reads.push(url);});
 await page.goto(origin+'/games/southern-chronicle/novel');await page.getByRole('button',{name:'Generate Chapter',exact:true}).filter({visible:true}).click();
 const dialog=page.getByRole('dialog',{name:'Generate Chapter',exact:true});await dialog.getByLabel('Prompt',{exact:true}).fill('Describe the companions arriving at the southern harbor.');
 const submitted=page.waitForResponse(response=>new URL(response.url()).pathname==='/editorial-jobs'&&response.request().method()==='POST');await dialog.getByRole('button',{name:'Generate Chapter',exact:true}).click();
 const response=await submitted;expect(response.ok()).toBe(true);const job=await response.json();expect(job.gameId).toBe('southern-chronicle');expect(job.jobId).toMatch(/^[a-f0-9]{64}$/);
 const progress=page.locator('.novel-job-card');await expect(progress).toContainText('Generation unavailable');await expect(progress).not.toContainText('Generation job not found');
 expect(reads.filter(url=>url.searchParams.has('jobId')).length).toBeGreaterThan(0);expect(reads.filter(url=>url.searchParams.has('jobId')).every(url=>url.searchParams.get('gameId')==='southern-chronicle'&&url.searchParams.get('jobId')===job.jobId)).toBe(true);
 const actual=await page.request.get(origin+`/editorial-jobs?gameId=southern-chronicle&jobId=${job.jobId}`,{headers});expect(actual.ok()).toBe(true);expect((await actual.json()).job.gameId).toBe('southern-chronicle');
 const denied=await page.request.get(origin+`/editorial-jobs?gameId=northern-chronicle&jobId=${job.jobId}`,{headers});expect(denied.status()).toBe(404);
 await page.reload();await expect(progress).toContainText('Generation unavailable');await expect(progress).not.toContainText('Generation job not found');
 await page.goto(origin+'/games/northern-chronicle/novel');await expect(page.locator('.novel-job-card')).toHaveCount(0);
});

for(const width of [1280,390])test(`Real local selected portrait loads and exposes replacement controls at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});await page.goto(origin+'/account');await page.getByRole('button',{name:'Regenerate demo data'}).click();await expect(page.getByText('Demo data regenerated.',{exact:true})).toBeVisible();
 await page.goto(origin+'/games/preview-campaign/characters');await page.getByRole('button',{name:'Create Character',exact:true}).click();await page.locator('#character-create-form').getByLabel('Character name').fill('Harbor Scout');await page.getByRole('button',{name:'Create Character',exact:true}).click();await expect(page.locator('#character-name')).toHaveText('Harbor Scout');
 const profileUrl=page.url(),characterId=new URL(profileUrl).pathname.split('/').at(-1),image=page.locator('#character-portrait-only'),avatar=page.locator('.character-avatar'),actions=page.locator('.character-portrait-actions'),upload=page.locator('#character-portrait-upload'),generate=page.locator('#character-portrait-generate');
 const png=await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=240;canvas.height=320;const c=canvas.getContext('2d');c.fillStyle='#233c45';c.fillRect(0,0,240,320);c.fillStyle='#e3bd79';c.beginPath();c.arc(120,100,45,0,Math.PI*2);c.fill();c.fillRect(65,160,110,130);return canvas.toDataURL('image/png').split(',')[1];});
 const chooser=page.waitForEvent('filechooser');await upload.click();await(await chooser).setFiles({name:'harbor-scout.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});await expect(image).toBeVisible();await expect.poll(()=>image.evaluate(el=>el.complete&&el.naturalWidth)).toBe(240);await expect.poll(()=>image.evaluate(el=>el.naturalHeight)).toBe(320);
 const headers={Authorization:'Bearer synthetic-development-test'},record=await page.request.get(origin+`/character-details?gameId=preview-campaign&characterId=${characterId}`,{headers});expect(record.ok()).toBe(true);const selectedKey=(await record.json()).character.details.thumbnailAssetKey;expect(selectedKey).toMatch(/\/original\/harbor-scout\.png$/);
 for(const reload of [false,true]){
  if(reload){await page.reload();await expect(image).toBeVisible();await expect.poll(()=>image.evaluate(el=>el.complete&&el.naturalWidth)).toBe(240);}
  await avatar.hover();await expect.poll(()=>actions.evaluate(el=>Number(getComputedStyle(el).opacity))).toBe(1);
  for(const button of [upload,generate]){await expect(button).toBeVisible();const [portraitBox,buttonBox]=await Promise.all([image.boundingBox(),button.boundingBox()]);expect(buttonBox.x).toBeGreaterThanOrEqual(portraitBox.x);expect(buttonBox.x+buttonBox.width).toBeLessThanOrEqual(portraitBox.x+portraitBox.width);expect(buttonBox.y).toBeGreaterThanOrEqual(portraitBox.y);expect(buttonBox.y+buttonBox.height).toBeLessThanOrEqual(portraitBox.y+portraitBox.height);if(await button.isEnabled())expect(await button.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);}
  await page.mouse.move(width-5,850);await page.locator('#character-back').focus();await page.keyboard.press('Tab');await expect(upload).toBeFocused();await expect.poll(()=>actions.evaluate(el=>Number(getComputedStyle(el).opacity))).toBe(1);if(await generate.isEnabled()){await page.keyboard.press('Tab');await expect(generate).toBeFocused();await expect.poll(()=>actions.evaluate(el=>Number(getComputedStyle(el).opacity))).toBe(1);}else{await expect(generate).toHaveAttribute('title','Image generation is unavailable');}
 }
 expect(page.url()).toBe(profileUrl);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:testInfo.outputPath(`real-local-portrait-${width}.png`),fullPage:true});
});
