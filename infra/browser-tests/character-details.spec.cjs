const {test,expect}=require('@playwright/test');
const fs=require('node:fs'), path=require('node:path');
const {MODEL_VIEWER_BUNDLE_PATH}=require('../dist/lib/panther-media-explorer-stack');
const gameId='example-game', characterId='hero';
const portrait='games/example-game/assets/portrait/original/image.png';
async function fixture(page) {
  let record={gameId,characterId,name:'Lantern Hero',revision:'a'.repeat(32),details:{schemaVersion:1,aliases:['Lantern Bearer'],pronouns:'they/them',role:'Scout',status:'Active',subtitle:'A patient guide',overview:'An explicitly recorded fictional summary.',backstory:'A long journey began at the river.',notes:null,statistics:[{group:'Abilities',name:'Strength',value:14}],relationships:[{entityType:'Character',id:'guide',relation:'Travels with'}],thumbnailAssetKey:portrait}};
  const characters=[{gameId,id:characterId,name:'Lantern Hero',detailsSubtitle:record.details.subtitle,detailsThumbnailKey:portrait},{gameId,id:'guide',name:'River Guide'}];
  const posted=[],created=[],history=[],requests=[]; let fail=false;
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'synthetic'}))+'.test'})));
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**',async route=>{
    const url=new URL(route.request().url());requests.push(url.pathname); let body={};
    if(url.pathname==='/games') body={games:[{id:gameId,name:'Example Game',purpose:'test'}]};
    else if(url.pathname==='/game') body={game:{id:gameId,name:'Example Game',purpose:'test',ruleset:'Synthetic Rules'},characters,players:[{id:'player',name:'Example Player'}],memberships:[{playerId:'player',role:'player',characterIds:[characterId]}]};
    else if(url.pathname==='/characters') body={characters:url.searchParams.get('cursor')?[characters[1]]:[characters[0]],cursor:url.searchParams.get('cursor')?null:'second'};
    else if(url.pathname==='/game/characters') {
      const body=route.request().postDataJSON(); created.push(body);
      const character={gameId,id:body.id,name:body.name}; characters.push(character);
      record={...record,characterId:body.id,name:body.name,revision:'c'.repeat(32),details:{...record.details,aliases:[],pronouns:null,role:null,status:null,subtitle:null,overview:null,backstory:null,notes:null,statistics:[],relationships:[],thumbnailAssetKey:null}};
      return route.fulfill({status:201,json:{character},headers:{'access-control-allow-origin':'https://panther.place'}});
    }
    else if(url.pathname==='/character-details/history') body={history,cursor:null};
    else if(url.pathname==='/character-details') {
      if(route.request().method()==='POST') {const edit=route.request().postDataJSON(); posted.push(edit);
        if(fail) return route.fulfill({status:409,json:{error:'Character changed'},headers:{'access-control-allow-origin':'https://panther.place'}});
        history.unshift({revision:'b'.repeat(32),previousRevision:record.revision,recordedAt:'2026-10-01T12:00:00Z',reason:edit.reason,details:edit.details,previousDetails:record.details,name:edit.name || record.name,previousName:record.name});
        record={...record,name:edit.name || record.name,details:edit.details,revision:'b'.repeat(32)};
      }
      body={character:record};
    }
    else if(url.pathname==='/character') body={character:{gameId,id:url.searchParams.get('characterId'),name:record.name},appearance:null,selection:null,model:null,poster:null,warnings:[]};
    else if(url.pathname==='/character-versions') body={schemaVersion:2,appearances:[],selections:[],activations:[],current:null,activationRevision:null};
    else if(url.pathname==='/asset-generation') body=url.searchParams.get('view')==='options'?{generationTypes:[{id:'portrait',name:'Portrait',available:true,models:[{id:'gpt-image-1',name:'gpt-image-1',inputs:{}}],defaultModel:'gpt-image-1',styles:[]},{id:'image',name:'Image',available:true,models:[{id:'gpt-image-1',name:'gpt-image-1',inputs:{}}],defaultModel:'gpt-image-1',styles:[]}]}:{jobs:[],cursor:null};
    else if(url.pathname==='/assets') body={assets:[{key:portrait,name:'Portrait.png',kind:'portrait',contentType:'image/png',lastModified:'2026-01-01T00:00:00Z',metadata:{title:'Selected reference',characterIds:[characterId],category:'reference'}}],cursor:null};
    else if(url.pathname==='/image-links') body={images:{[portrait]:{url:'https://test.s3.amazonaws.com/portrait.svg'}},expiresIn:300};
    return route.fulfill({json:body,headers:{'access-control-allow-origin':'https://panther.place'}});
  });
  await page.route('https://test.s3.amazonaws.com/**',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="gold"/></svg>'}));
  await page.route('https://panther.place/**',route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(pathname==='/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"synthetic",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    const file=pathname==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  return {posted,created,requests,history,conflict:()=>{fail=true;}};
}
for(const width of [1280,390]) test(`structured character editing and catalog pagination at ${width}px`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:900}); const control=await fixture(page);
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`https://panther.place/games/${gameId}/characters`);
  await expect(page.getByRole('button',{name:/Lantern Hero/})).toBeVisible();
  await expect(page.locator('.character-monogram img')).toBeVisible();
  await expect(page.getByRole('button',{name:/River Guide/})).toHaveCount(0);
  await page.getByRole('button',{name:'Load more characters'}).click();
  await expect(page.getByRole('button',{name:/River Guide/})).toBeVisible();
  await expect(page.getByRole('button',{name:'Load more characters'})).toBeHidden();
  await page.getByRole('button',{name:/Lantern Hero/}).click();
  const facts=page.locator('#character-facts');
  expect(control.requests).not.toContain('/character-details/history');await expect(page.locator('#character-assets')).toBeVisible();await expect(page.locator('#character-appearance-panel')).toBeHidden();await expect(page.getByRole('heading',{name:'Characters',exact:true})).toBeHidden();await expect(page.getByRole('heading',{name:'Lantern Hero',exact:true})).toHaveCount(1);
  await expect(facts).toContainText('Example Player'); await expect(facts).not.toContainText('they/them');
  await page.getByRole('button',{name:'Connections',exact:true}).click();await expect(facts.getByRole('link',{name:'River Guide'})).toHaveAttribute('href',`/games/${gameId}/characters/guide`);
  await expect(page.locator('#character-assets')).toBeVisible();await expect(page.locator('#character-assets-list').getByRole('link',{name:'Preview Selected reference',exact:true})).toBeVisible();await expect(page.locator('#character-assets-list')).not.toContainText('portrait · reference');
  await page.getByRole('button',{name:'Edit',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Edit character',exact:true})).toBeVisible();await expect(page.getByRole('dialog',{name:'Edit character',exact:true})).toBeInViewport();
  await page.getByLabel('Backstory',{exact:true}).fill('Updated fictional backstory.');
  await chooseSelect(page,'Status','Retired');
  await page.getByRole('button',{name:'Add Relationship'}).click(); // untouched optional row must not block saving
  await page.getByRole('button',{name:'Add Statistic'}).click();
  const row=page.locator('.character-stat-editor').last();
  await row.getByLabel('Name',{exact:true}).fill('Brave');
  await row.getByLabel('Value',{exact:true}).fill('true');
  const save=page.getByRole('button',{name:'Save changes'}); await save.scrollIntoViewIfNeeded();
  const bounds=await save.boundingBox(); expect(bounds.x).toBeGreaterThanOrEqual(0); expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);
  expect(await save.evaluate(el=>{const r=el.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===el;})).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`character-editor-${width}.png`),fullPage:true});
  await save.click(); await expect(facts).toContainText('Character information saved');
  expect(control.posted[0].expectedRevision).toBe('a'.repeat(32)); expect(control.posted[0].details.statistics[1].value).toBe(true);expect(control.posted[0].details.statistics[0].group).toBe('Abilities');expect(control.posted[0].details.pronouns).toBe('they/them');expect(control.posted[0].details.aliases).toEqual(['Lantern Bearer']);
  await expect(facts).toContainText('Updated fictional backstory.');
  await page.screenshot({path:testInfo.outputPath(`character-profile-${width}.png`),fullPage:true});
  control.conflict(); await page.getByRole('button',{name:'Edit',exact:true}).click(); await page.getByRole('button',{name:'Save changes'}).click();
  await expect(page.getByRole('dialog',{name:'Edit character',exact:true})).toContainText('Another update changed'); await expect(page.getByRole('button',{name:'Retry exact save'})).toBeDisabled();
  await page.getByRole('button',{name:'Cancel'}).click(); await expect(facts).toContainText('Retired');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  expect(errors).toEqual([]);
});

test('an uncertain character save retries the identical operation without accepting changed fields',async({page})=>{
  await fixture(page); const requests=[];
  await page.route('**/character-details',async route=>{
    if(route.request().method()!=='POST') return route.fallback();
    requests.push(route.request().postDataJSON());
    if(requests.length===1) return route.fulfill({status:503,json:{error:'Response unavailable'},headers:{'access-control-allow-origin':'https://panther.place'}});
    return route.fallback();
  });
  await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);
  await page.getByRole('button',{name:'Edit',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Edit character',exact:true})).toBeVisible();await expect(page.getByRole('dialog',{name:'Edit character',exact:true})).toBeInViewport();
  await chooseSelect(page,'Status','Retired');
  await page.getByRole('button',{name:'Save changes'}).click();
  await expect(page.getByRole('combobox',{name:'Status',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Retry exact save'}).click();
  await expect(page.locator('#character-facts')).toContainText('Character information saved');
  expect(requests).toHaveLength(2); expect(requests[1]).toEqual(requests[0]);
});

for(const width of [1280,390]) test(`create a character, edit background and inspect real changes at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:900}); const control=await fixture(page);
  await page.goto(`https://panther.place/games/${gameId}/characters`);
  await page.getByRole('button',{name:'Create Character',exact:true}).click();
  const form=page.locator('#character-create-form');
  await form.getByLabel('Character name').fill('New Ranger');
  await form.getByRole('button',{name:'Create Character'}).click();
  await expect(page).toHaveURL(/characters\/new-ranger-[a-f0-9]{8}$/);
  expect(control.created[0].name).toBe('New Ranger');
  await expect(page.getByRole('button',{name:'History',exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:'Backstory',exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'Statistics',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Edit',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Edit character',exact:true})).toBeVisible();await expect(page.getByRole('dialog',{name:'Edit character',exact:true})).toBeInViewport();
  await page.getByRole('dialog',{name:'Edit character',exact:true}).getByLabel('Character name',{exact:true}).fill('River Ranger');
  await page.getByLabel('Backstory',{exact:true}).fill('A recorded childhood on the river.');
  await page.getByRole('button',{name:'Add Relationship'}).click();
  const connection=page.locator('.character-connection-editor').last();
  await expect(connection).toBeVisible();
  await chooseSelect(page,'Player','Example Player');
  await chooseSelect(page,'Relationship','Ally');
  await page.getByRole('button',{name:'Save changes'}).click();
  await expect(page.locator('#character-facts')).toContainText('A recorded childhood on the river.');
  expect(control.posted[0].details.relationships).toEqual([{entityType:'Player',id:'player',relation:'Ally'}]);
  expect(control.history[0].name).toBe('River Ranger');expect(control.history[0].previousName).toBe('New Ranger');await expect(page.locator('.character-change-history')).toHaveCount(0);
  await expect(page.getByRole('button',{name:/Refresh|Retry character information/})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
});

for(const width of [1280,390])test(`New character information remains editable when artwork is unavailable at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});const control=await fixture(page);await page.route('https://test.execute-api.us-west-2.amazonaws.com/character?**',route=>route.fulfill({status:503,headers:{'access-control-allow-origin':'https://panther.place'},json:{error:'Appearance unavailable while old artwork is verified'}}));
 await page.goto(`https://panther.place/games/${gameId}/characters`);await page.getByRole('button',{name:'Create Character',exact:true}).click();const form=page.locator('#character-create-form');await form.getByLabel('Character name').fill('New Guide');await form.getByRole('button',{name:'Create Character'}).click();
 await expect(page.locator('#character-profile')).toBeVisible();await expect(page.locator('#characters-status')).toContainText('Appearance unavailable');await page.getByRole('button',{name:'Edit',exact:true}).click();
 await page.getByLabel('Backstory',{exact:true}).fill('An explicitly recorded background.');await page.getByRole('button',{name:'Save changes',exact:true}).click();await expect(page.locator('#character-facts')).toContainText('An explicitly recorded background.');expect(control.posted[0].details.backstory).toBe('An explicitly recorded background.');
 await page.screenshot({path:testInfo.outputPath(`character-artwork-unavailable-${width}.png`)});
});

for(const width of [1280,390]) test(`portrait generation continues inline after the composer closes at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});const control=await fixture(page);const posts=[];
 const headers={'access-control-allow-origin':'https://panther.place'};let job=null;
 await page.route('**/asset-generation**',route=>{const url=new URL(route.request().url());if(url.searchParams.get('view')==='options')return route.fallback();if(route.request().method()==='POST'){posts.push(route.request().postDataJSON());job={...posts[0],jobId:'a'.repeat(64),name:'River scout',status:'QUEUED'};return route.fulfill({headers,json:job});}return route.fulfill({headers,json:url.searchParams.get('jobId')?job:{jobs:job?[job]:[],cursor:null}});});
 await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);await page.locator('#character-portrait-generate').click();const dialog=page.getByRole('dialog',{name:'Generate asset',exact:true});await expect(dialog).toBeInViewport();await dialog.getByLabel('Prompt',{exact:true}).fill('A scout beside the river');const submit=dialog.getByRole('button',{name:'Generate asset',exact:true});await expect(submit).toBeInViewport();expect(await submit.evaluate(el=>{const b=el.getBoundingClientRect();return el.contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2));})).toBe(true);await submit.click();await expect(dialog).toHaveCount(0);
 await expect(page.locator('#character-portrait-progress')).toContainText('Queued');expect(posts[0].characterId).toBe(characterId);expect(posts[0].selectAsPortrait).toBe(true);expect(posts[0].name).toBeUndefined();expect(control.posted).toHaveLength(0);
 await page.reload();await expect(page.locator('#character-portrait-progress')).toContainText('Queued');expect(posts).toHaveLength(1);
 await expect(page.getByRole('heading',{name:'Assets',exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'Artwork',exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:'References',exact:true})).toHaveCount(0);
 const name=await page.locator('#character-name').boundingBox(),role=await page.locator('#character-title').boundingBox();expect(role.y).toBeGreaterThanOrEqual(name.y+name.height);
 await page.screenshot({path:testInfo.outputPath(`character-background-generation-${width}.png`),fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for(const width of [1280,390]) test(`uploaded profile portrait survives reload without replacing official artwork at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:900});const control=await fixture(page);let upload;
  const key='games/example-game/assets/new-portrait/original/upload.png',url='https://test.s3.amazonaws.com/new-portrait.svg',headers={'access-control-allow-origin':'https://panther.place'};
  await page.route('**/character?**',route=>route.fulfill({headers,json:{character:{gameId,id:characterId,name:'Lantern Hero'},poster:{url:'https://test.s3.amazonaws.com/official.svg'},model:null,appearance:null,selection:null}}));
  await page.route('**/uploads',route=>{upload=route.request().postDataJSON();return route.fulfill({headers,json:{key,url:'https://test.s3.amazonaws.com/put-portrait',headers:{}}});});
  await page.route('https://test.s3.amazonaws.com/put-portrait',route=>route.fulfill({status:200,headers}));
  await page.route('**/object-url?**',route=>route.fulfill({headers,json:{key,url,sha256:upload.sha256,size:upload.size,metadata:upload.metadata}}));
  await page.route('**/image-links',route=>route.fulfill({headers,json:{images:{[portrait]:{url:'https://test.s3.amazonaws.com/old.svg'},[key]:{url}},expiresIn:300}}));
  await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);await expect(page.getByRole('button',{name:'Edit',exact:true})).toBeVisible();
  const chooser=page.waitForEvent('filechooser');await page.locator('#character-portrait-upload').click();await(await chooser).setFiles({name:'portrait.png',mimeType:'image/png',buffer:Buffer.from('synthetic image upload')});
  await expect(page.locator('#character-portrait-only')).toHaveAttribute('src',url);expect(upload.metadata.characterIds).toEqual([characterId]);expect(control.posted[0].details.thumbnailAssetKey).toBe(key);
  await page.reload();await expect(page.locator('#character-portrait-only')).toHaveAttribute('src',url);await expect(page.locator('#character-portrait-only')).toBeVisible();
});

async function chooseSelect(page,label,choice){await page.getByRole('combobox',{name:label,exact:true}).click();await page.getByRole('option',{name:choice,exact:true}).click();}

for(const width of [1280,390])test(`empty character fields and portrait actions remain visible at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});await fixture(page);await page.goto(`https://panther.place/games/${gameId}/characters`);await page.getByRole('button',{name:'Create Character',exact:true}).click();await page.locator('#character-create-form').getByLabel('Character name').fill('Quiet Ranger');await page.getByRole('button',{name:'Create Character',exact:true}).click();
 await expect(page.locator('#character-title')).toHaveText('');await expect(page.getByRole('heading',{name:'Backstory',exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'Statistics',exact:true})).toBeVisible();await expect(page.locator('#character-facts')).toContainText('Status');await expect(page.locator('#character-facts')).toContainText('Played by');await expect(page.getByRole('button',{name:'History',exact:true})).toHaveCount(0);
 const frame=await page.locator('#character-portrait-empty').boundingBox();for(const id of ['character-portrait-upload','character-portrait-generate']){const button=page.locator('#'+id);await expect(button).toBeVisible();const box=await button.boundingBox();expect(box.x).toBeGreaterThanOrEqual(frame.x);expect(box.y).toBeGreaterThanOrEqual(frame.y);expect(box.x+box.width).toBeLessThanOrEqual(frame.x+frame.width);expect(box.y+box.height).toBeLessThanOrEqual(frame.y+frame.height);}
 await page.screenshot({path:testInfo.outputPath(`character-empty-profile-${width}.png`),fullPage:true});
});

for(const width of [1280,390]) test(`generic character Assets generation does not replace the portrait at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});const control=await fixture(page);const posts=[],headers={'access-control-allow-origin':'https://panther.place'};
 await page.route('**/asset-generation**',route=>{const url=new URL(route.request().url());if(url.searchParams.get('view')==='options')return route.fallback();if(route.request().method()==='POST'){posts.push(route.request().postDataJSON());return route.fulfill({headers,json:{...posts[0],jobId:'b'.repeat(64),status:'QUEUED'}});}return route.fulfill({headers,json:url.searchParams.get('jobId')?{...posts[0],jobId:'b'.repeat(64),status:'QUEUED'}:{jobs:[],cursor:null}});});
 await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);await page.locator('#character-assets-generate').click();const dialog=page.getByRole('dialog',{name:'Generate asset',exact:true});await dialog.getByLabel('Prompt',{exact:true}).fill('An illustration of the scout camp');await dialog.getByRole('button',{name:'Generate asset',exact:true}).click();await expect(dialog).toHaveCount(0);expect(posts[0].characterId).toBe(characterId);expect(posts[0].type).toBe('image');expect(posts[0].selectAsPortrait).toBeUndefined();expect(control.posted).toHaveLength(0);await expect(page.locator('#character-assets-progress')).toContainText('Queued');
});

for(const width of [1280,390])test(`character edits stay in a focused dialog and cancel restores profile at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:900});const control=await fixture(page);
  await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);const edit=page.getByRole('button',{name:'Edit',exact:true});await expect(edit).toBeInViewport();
  const nameBox=await page.locator('#character-name').boundingBox(),editBox=await edit.boundingBox();
  expect(editBox.x).toBeGreaterThanOrEqual(nameBox.x+nameBox.width);expect(editBox.x-nameBox.x-nameBox.width).toBeLessThanOrEqual(16);
  expect(Math.abs(editBox.y+editBox.height/2-nameBox.y-nameBox.height/2)).toBeLessThan(2);expect(editBox.height).toBeGreaterThanOrEqual(36);expect(editBox.width).toBeGreaterThanOrEqual(44);
  expect(await edit.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  for(const action of await page.getByRole('button',{name:/^(Upload|Generate)(?: |$)/}).all())if(await action.isVisible()){
    await expect(action.locator('svg')).toHaveCount(1);await expect(action.locator('svg')).toHaveAttribute('aria-hidden','true');
    await expect(action.locator('svg')).toHaveClass((await action.textContent()).trim().startsWith('Upload')?/lucide-upload/:/lucide-sparkles/);
    const measured=await action.evaluate(el=>{const style=getComputedStyle(el);return {height:el.getBoundingClientRect().height,border:style.borderTopStyle};});expect(measured.height).toBe(36);expect(measured.border).toBe('solid');
  }
  await page.screenshot({path:test.info().outputPath(`character-edit-link-${width}.png`)});await edit.click();
  const dialog=page.getByRole('dialog',{name:'Edit character',exact:true});await expect(dialog).toBeVisible();
  await dialog.getByLabel('Backstory',{exact:true}).fill('An unsaved change');
  const cancel=dialog.getByRole('button',{name:'Cancel'});await expect(cancel).toBeInViewport();
  const hit=await cancel.evaluate(el=>{const r=el.getBoundingClientRect();const found=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return found===el||el.contains(found);});expect(hit).toBe(true);
  await page.screenshot({path:test.info().outputPath(`character-edit-modal-${width}.png`)});
  await cancel.click();await expect(dialog).toHaveCount(0);await expect(edit).toBeFocused();expect(control.posted).toHaveLength(0);
  await expect(page.locator('#character-facts')).toContainText('A long journey began at the river.');
});

test('local portrait actions are disabled when the image worker is unavailable',async({page})=>{
 await fixture(page);await page.route('**/config.js',route=>route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={development:true,apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"synthetic",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'}));
 await page.route('**/generation-capabilities',route=>route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{images:false}}));
 await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);await expect(page.locator('#character-portrait-generate')).toBeDisabled();await expect(page.locator('#character-portrait-generate')).toHaveAttribute('title','Image generation is unavailable');
});


for(const width of [1280,390])test(`References show finished media and open previews in place at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});await fixture(page);
 const second='games/example-game/assets/portrait-second/original/image.png',clip='games/example-game/assets/action/original/take.webm';
 const image=key=>({key,name:'image.png',kind:'portrait',contentType:'image/png',lastModified:'2026-10-01',metadata:{title:'Lantern at the river',characterIds:[characterId],extra:{relationshipRole:'finished'}}});
 const assets=[image(portrait),image(portrait),image(second),{key:clip,name:'take.webm',kind:'video',contentType:'video/webm',lastModified:'2026-10-02',metadata:{title:'Crossing the river',characterIds:[characterId],extra:{relationshipRole:'finished',mediaProbe:{format:{duration:'8'}}}}},...['generation-provenance','video-shot-list','generation-receipt'].map(kind=>({key:`games/example-game/assets/${kind}/original/data.json`,name:'data.json',kind,contentType:'application/json',lastModified:'2026-10-03',metadata:{title:'Lantern at the river',characterIds:[characterId]}}))];
 const bytes=await page.evaluate(async()=>{const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;const c=canvas.getContext('2d');c.fillStyle='#b39e6d';c.fillRect(0,0,160,90);const stream=canvas.captureStream(10),recorder=new MediaRecorder(stream,{mimeType:'video/webm'}),parts=[];recorder.ondataavailable=e=>parts.push(e.data);const done=new Promise(resolve=>recorder.onstop=resolve);recorder.start();for(let i=0;i<5;i++){c.fillRect(0,0,160,90);await new Promise(resolve=>setTimeout(resolve,100));}recorder.stop();await done;stream.getTracks().forEach(track=>track.stop());return Array.from(new Uint8Array(await new Blob(parts).arrayBuffer()));});
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/assets?**',route=>route.fulfill({json:{assets,cursor:null},headers:{'access-control-allow-origin':'https://panther.place'}}));
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/image-links',route=>route.fulfill({json:{images:{}},headers:{'access-control-allow-origin':'https://panther.place'}}));
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/object-url?**',route=>{const key=new URL(route.request().url()).searchParams.get('key');const asset=assets.find(asset=>asset.key===key);return route.fulfill({json:{...asset,filename:asset.name,url:key===clip?'https://test.s3.amazonaws.com/take.webm':'https://test.s3.amazonaws.com/portrait.svg'},headers:{'access-control-allow-origin':'https://panther.place'}});});
 await page.route('https://test.s3.amazonaws.com/take.webm',route=>route.fulfill({contentType:'video/webm',body:Buffer.from(bytes)}));
 const url=`https://panther.place/games/${gameId}/characters/${characterId}`;await page.goto(url);
 const gallery=page.locator('#character-assets-list');await expect(gallery.getByRole('link')).toHaveCount(3);await expect(gallery.getByRole('heading')).toHaveCount(0);await expect(gallery).not.toContainText('provenance');
 await gallery.scrollIntoViewIfNeeded();await expect(gallery.locator('img')).toHaveCount(2);await expect.poll(()=>gallery.locator('img').first().evaluate(img=>img.complete&&img.naturalWidth)).toBe(64);await expect(gallery.locator('video')).toBeVisible();await expect(gallery.locator('.character-video-play')).toBeVisible();await expect(gallery.locator('.character-video-duration')).toHaveText('0:08');
 await gallery.scrollIntoViewIfNeeded();await page.screenshot({path:testInfo.outputPath(`character-references-${width}.png`)});
 const imageLink=gallery.getByRole('link',{name:'Preview Lantern at the river'}).first();await expect(imageLink).toBeVisible();await imageLink.click();await expect(page.locator('#preview-body img')).toBeVisible();await expect(page).toHaveURL(url);await page.getByRole('button',{name:'Close preview',exact:true}).click();
 await gallery.getByRole('link',{name:'Preview Crossing the river',exact:true}).click();await expect(page.locator('#preview-body video')).toBeVisible();await expect(page.getByRole('link',{name:'Download',exact:true})).toBeVisible();await expect(page.locator('#preview-dialog')).not.toContainText('Technical files and original exports');const videoBox=await page.locator('#preview-body video').boundingBox(),downloadBox=await page.getByRole('link',{name:'Download',exact:true}).boundingBox();expect(downloadBox.y).toBeGreaterThanOrEqual(videoBox.y+videoBox.height);expect(downloadBox.height).toBeLessThan(36);await expect.poll(()=>page.locator('#preview-body video').evaluate(video=>video.readyState)).toBeGreaterThanOrEqual(2);await expect(page).toHaveURL(url);await page.getByRole('button',{name:'Close preview',exact:true}).click();await expect(gallery).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('uncertain official-portrait submission keeps its intent separate from generic Assets',async({page})=>{
 await fixture(page);const posts=[],headers={'access-control-allow-origin':'https://panther.place'};
 await page.route('**/asset-generation**',route=>{const url=new URL(route.request().url());if(url.searchParams.get('view')==='options')return route.fallback();if(route.request().method()==='POST'){posts.push(route.request().postDataJSON());return route.fulfill({status:503,headers,json:{error:'Submission could not be confirmed.'}});}return route.fulfill({headers,json:{jobs:[],cursor:null}});});
 await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);await page.locator('#character-portrait-generate').click();let dialog=page.getByRole('dialog',{name:'Generate asset',exact:true});await dialog.getByLabel('Prompt',{exact:true}).fill('A river portrait');await dialog.getByRole('button',{name:'Generate asset',exact:true}).click();await expect(dialog.getByRole('alert')).toContainText('could not be confirmed');await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
 await page.locator('#character-assets-generate').click();dialog=page.getByRole('dialog',{name:'Generate asset',exact:true});await expect(dialog.getByLabel('Prompt',{exact:true})).toHaveValue('');await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
 await page.locator('#character-portrait-generate').click();dialog=page.getByRole('dialog',{name:'Generate asset',exact:true});await expect(dialog.getByLabel('Prompt',{exact:true})).toHaveValue('A river portrait');await dialog.getByRole('button',{name:'Retry',exact:true}).click();await expect(dialog.getByRole('alert')).toContainText('could not be confirmed');expect(posts).toHaveLength(2);expect(posts[1]).toEqual(posts[0]);expect(posts[1].selectAsPortrait).toBe(true);
});

for(const width of [1280,390])test(`Empty portrait Generate remains readable on hover at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await fixture(page);
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/character-details?**',route=>route.fulfill({headers:{'access-control-allow-origin':'https://panther.place'},json:{character:{gameId,characterId,name:'New Guide',revision:'a'.repeat(32),details:{schemaVersion:1,role:null,status:null,backstory:null,overview:null,statistics:[],relationships:[],thumbnailAssetKey:null}}}}));
 await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);await expect(page.locator('#character-portrait-empty')).toBeVisible();
 const generate=page.getByRole('button',{name:'Generate portrait',exact:true});await expect(generate).toBeInViewport();await generate.hover();
 const contrast=await generate.evaluate(el=>{const context=document.createElement('canvas').getContext('2d');context.canvas.width=context.canvas.height=1;const rgb=color=>{context.clearRect(0,0,1,1);context.fillStyle=color;context.fillRect(0,0,1,1);return [...context.getImageData(0,0,1,1).data].slice(0,3);};const luminance=values=>values.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);const css=getComputedStyle(el),a=luminance(rgb(css.color)),b=luminance(rgb(css.backgroundColor));return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);});
 expect(contrast).toBeGreaterThanOrEqual(4.5);const rectangle=await generate.boundingBox();expect(rectangle.x+rectangle.width).toBeLessThanOrEqual(width);expect(await generate.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
 await page.screenshot({path:test.info().outputPath(`portrait-generate-hover-${width}.png`),fullPage:true});
});
