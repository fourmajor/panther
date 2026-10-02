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
  expect(control.requests).not.toContain('/character-details/history');await expect(page.locator('#character-assets')).toBeVisible();await expect(page.locator('#character-appearance-panel')).toBeVisible();await expect(page.getByRole('heading',{name:'Characters',exact:true})).toBeHidden();await expect(page.getByRole('heading',{name:'Lantern Hero',exact:true})).toHaveCount(1);
  await expect(facts).toContainText('Example Player'); await expect(facts).not.toContainText('they/them');
  await page.getByRole('button',{name:'Connections',exact:true}).click();await expect(facts.getByRole('link',{name:'River Guide'})).toHaveAttribute('href',`/games/${gameId}/characters/guide`);
  await expect(page.locator('#character-assets')).toBeVisible();await expect(page.locator('#character-assets-list')).toContainText('portrait · reference');
  await page.getByRole('button',{name:'Edit character information'}).click();
  await page.getByLabel('Backstory',{exact:true}).fill('Updated fictional backstory.');
  await chooseSelect(page,'Status','Retired');
  await page.getByRole('button',{name:'Add relationship'}).click(); // untouched optional row must not block saving
  await page.getByRole('button',{name:'Add statistic'}).click();
  const row=page.locator('.character-stat-editor').last();
  await row.getByLabel('Name',{exact:true}).fill('Brave');
  await row.getByLabel('Value',{exact:true}).fill('true');
  const save=page.getByRole('button',{name:'Save character information'}); await save.scrollIntoViewIfNeeded();
  const bounds=await save.boundingBox(); expect(bounds.x).toBeGreaterThanOrEqual(0); expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);
  expect(await save.evaluate(el=>{const r=el.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===el;})).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`character-editor-${width}.png`),fullPage:true});
  await save.click(); await expect(facts).toContainText('Character information saved');
  expect(control.posted[0].expectedRevision).toBe('a'.repeat(32)); expect(control.posted[0].details.statistics[1].value).toBe(true);expect(control.posted[0].details.statistics[0].group).toBe('Abilities');expect(control.posted[0].details.pronouns).toBe('they/them');expect(control.posted[0].details.aliases).toEqual(['Lantern Bearer']);
  await expect(facts).toContainText('Updated fictional backstory.');
  await page.screenshot({path:testInfo.outputPath(`character-profile-${width}.png`),fullPage:true});
  control.conflict(); await page.getByRole('button',{name:'Edit character information'}).click(); await page.getByRole('button',{name:'Save character information'}).click();
  await expect(facts).toContainText('Another update changed'); await expect(page.getByRole('button',{name:'Retry exact save'})).toBeDisabled();
  await page.getByRole('button',{name:'Cancel edit'}).click(); await expect(facts).toContainText('Retired');
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
  await page.getByRole('button',{name:'Edit character information'}).click();
  await chooseSelect(page,'Status','Retired');
  await page.getByRole('button',{name:'Save character information'}).click();
  await expect(page.getByRole('combobox',{name:'Status',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Retry exact save'}).click();
  await expect(page.locator('#character-facts')).toContainText('Character information saved');
  expect(requests).toHaveLength(2); expect(requests[1]).toEqual(requests[0]);
});

for(const width of [1280,390]) test(`create a character, edit background and inspect real changes at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:900}); const control=await fixture(page);
  await page.goto(`https://panther.place/games/${gameId}/characters`);
  await page.getByRole('button',{name:'Add character',exact:true}).click();
  const form=page.locator('#character-create-form');
  await form.getByLabel('Character name').fill('New Ranger');
  await form.getByRole('button',{name:'Create character'}).click();
  await expect(page).toHaveURL(/characters\/new-ranger-[a-f0-9]{8}$/);
  expect(control.created[0].name).toBe('New Ranger');
  await expect(page.getByRole('button',{name:'History',exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:'Backstory',exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'Statistics',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Edit character information'}).click();
  await page.locator('#character-facts').getByLabel('Character name',{exact:true}).fill('River Ranger');
  await page.getByLabel('Backstory',{exact:true}).fill('A recorded childhood on the river.');
  await page.getByRole('button',{name:'Add relationship'}).click();
  const connection=page.locator('.character-connection-editor').last();
  await expect(connection).toBeVisible();
  await chooseSelect(page,'Player','Example Player');
  await chooseSelect(page,'Relationship','Ally');
  await page.getByRole('button',{name:'Save character information'}).click();
  await expect(page.locator('#character-facts')).toContainText('A recorded childhood on the river.');
  expect(control.posted[0].details.relationships).toEqual([{entityType:'Player',id:'player',relation:'Ally'}]);
  expect(control.history[0].name).toBe('River Ranger');expect(control.history[0].previousName).toBe('New Ranger');await expect(page.locator('.character-change-history')).toHaveCount(0);
  await expect(page.getByRole('button',{name:/Refresh|Retry character information/})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
});

for(const width of [1280,390])test(`New character information remains editable when artwork is unavailable at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});const control=await fixture(page);await page.route('https://test.execute-api.us-west-2.amazonaws.com/character?**',route=>route.fulfill({status:503,headers:{'access-control-allow-origin':'https://panther.place'},json:{error:'Appearance unavailable while old artwork is verified'}}));
 await page.goto(`https://panther.place/games/${gameId}/characters`);await page.getByRole('button',{name:'Add character',exact:true}).click();const form=page.locator('#character-create-form');await form.getByLabel('Character name').fill('New Guide');await form.getByRole('button',{name:'Create character'}).click();
 await expect(page.locator('#character-profile')).toBeVisible();await expect(page.locator('#characters-status')).toContainText('Appearance unavailable');await page.getByRole('button',{name:'Edit character information',exact:true}).click();
 await page.getByLabel('Backstory',{exact:true}).fill('An explicitly recorded background.');await page.getByRole('button',{name:'Save character information',exact:true}).click();await expect(page.locator('#character-facts')).toContainText('An explicitly recorded background.');expect(control.posted[0].details.backstory).toBe('An explicitly recorded background.');
 await page.screenshot({path:testInfo.outputPath(`character-artwork-unavailable-${width}.png`)});
});

for(const width of [1280,390]) test(`portrait creation binds the current character at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:900});const control=await fixture(page);
  const jobs=[];await page.route('**/asset-generation**',route=>{if(route.request().method()==='POST')jobs.push(route.request().postDataJSON());return route.fulfill({json:{jobId:'a'.repeat(64),status:'PUBLISHED',assetKey:portrait},headers:{'access-control-allow-origin':'https://panther.place'}});});
  await page.route('**/object-url?**',route=>route.fulfill({json:{key:portrait,url:'https://test.s3.amazonaws.com/portrait.svg',metadata:{characterIds:[characterId]}},headers:{'access-control-allow-origin':'https://panther.place'}}));
  await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);
  await page.locator('#character-portrait-generate').click();const form=page.locator('#character-portrait-generation');await form.getByLabel('Portrait direction').fill('A scout beside the river');await form.getByRole('button',{name:'Generate portrait',exact:true}).click();
  await expect(form).toHaveCount(0);expect(jobs[0].characterId).toBe(characterId);expect(jobs[0].type).toBe('portrait');expect(control.posted[0].expectedRevision).toBe('a'.repeat(32));expect(control.posted[0].details.thumbnailAssetKey).toBe(portrait);
  await expect(page.locator('#character-portrait-only')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
});

for(const width of [1280,390]) test(`uploaded profile portrait survives reload without replacing official artwork at ${width}px`,async({page})=>{
  await page.setViewportSize({width,height:900});const control=await fixture(page);let upload;
  const key='games/example-game/assets/new-portrait/original/upload.png',url='https://test.s3.amazonaws.com/new-portrait.svg',headers={'access-control-allow-origin':'https://panther.place'};
  await page.route('**/character?**',route=>route.fulfill({headers,json:{character:{gameId,id:characterId,name:'Lantern Hero'},poster:{url:'https://test.s3.amazonaws.com/official.svg'},model:null,appearance:null,selection:null}}));
  await page.route('**/uploads',route=>{upload=route.request().postDataJSON();return route.fulfill({headers,json:{key,url:'https://test.s3.amazonaws.com/put-portrait',headers:{}}});});
  await page.route('https://test.s3.amazonaws.com/put-portrait',route=>route.fulfill({status:200,headers}));
  await page.route('**/object-url?**',route=>route.fulfill({headers,json:{key,url,sha256:upload.sha256,size:upload.size,metadata:upload.metadata}}));
  await page.route('**/image-links',route=>route.fulfill({headers,json:{images:{[portrait]:{url:'https://test.s3.amazonaws.com/old.svg'},[key]:{url}},expiresIn:300}}));
  await page.goto(`https://panther.place/games/${gameId}/characters/${characterId}`);await expect(page.getByRole('button',{name:'Edit character information'})).toBeVisible();
  const chooser=page.waitForEvent('filechooser');await page.locator('#character-portrait-upload').click();await(await chooser).setFiles({name:'portrait.png',mimeType:'image/png',buffer:Buffer.from('synthetic image upload')});
  await expect(page.locator('#character-portrait-only')).toHaveAttribute('src',url);expect(upload.metadata.characterIds).toEqual([characterId]);expect(control.posted[0].details.thumbnailAssetKey).toBe(key);
  await page.reload();await expect(page.locator('#character-portrait-only')).toHaveAttribute('src',url);await expect(page.locator('#character-portrait-only')).toBeVisible();
});

async function chooseSelect(page,label,choice){await page.getByRole('combobox',{name:label,exact:true}).click();await page.getByRole('option',{name:choice,exact:true}).click();}

for(const width of [1280,390])test(`empty character fields and portrait actions remain visible at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});await fixture(page);await page.goto(`https://panther.place/games/${gameId}/characters`);await page.getByRole('button',{name:'Add character',exact:true}).click();await page.locator('#character-create-form').getByLabel('Character name').fill('Quiet Ranger');await page.getByRole('button',{name:'Create character',exact:true}).click();
 await expect(page.locator('#character-title')).toHaveText('Class / role · —');await expect(page.getByRole('heading',{name:'Backstory',exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'Statistics',exact:true})).toBeVisible();await expect(page.locator('#character-facts')).toContainText('Status');await expect(page.locator('#character-facts')).toContainText('Played by');await expect(page.getByRole('button',{name:'History',exact:true})).toHaveCount(0);
 const frame=await page.locator('#character-portrait-empty').boundingBox();for(const id of ['character-portrait-upload','character-portrait-generate']){const button=page.locator('#'+id);await expect(button).toBeVisible();const box=await button.boundingBox();expect(box.x).toBeGreaterThanOrEqual(frame.x);expect(box.y).toBeGreaterThanOrEqual(frame.y);expect(box.x+box.width).toBeLessThanOrEqual(frame.x+frame.width);expect(box.y+box.height).toBeLessThanOrEqual(frame.y+frame.height);}
 await page.screenshot({path:testInfo.outputPath(`character-empty-profile-${width}.png`),fullPage:true});
});
