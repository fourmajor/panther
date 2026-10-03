const {test,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
const {MODEL_VIEWER_BUNDLE_PATH}=require('../dist/lib/panther-media-explorer-stack');

async function fixture(page,{lostResponse=false,ambiguous=false,unselected=false}={}) {
  const gameId='example-game',characterId='hero';
  const portrait=id=>`games/${gameId}/assets/${id}/original/portrait.svg`;
  const character={gameId,id:characterId,name:'Synthetic Hero',title:'Scout',summary:'Fictional appearance history.'};
  const timing={sessionId:null,eventId:null,date:null};
  const pair=(id,appearanceId,modelKey=null)=>({id,appearanceId,appearanceRevision:'b'.repeat(32),revision:'c'.repeat(32),portraitKey:portrait(id),modelKey,sourceKey:null,provenanceKey:null});
  const selections=[pair('current','ordinary','games/example-game/assets/current/original/model.glb'),pair('earlier','ordinary',ambiguous?'games/example-game/assets/current/original/model.glb':null),pair('stone','stone')];
  const previews=unselected?[pair('preview','ordinary'),pair('preview-state','candidate-look')]:[];
  let current='current',revision='a'.repeat(32),first=true;
  const posted=[],requests=[];
  const history=()=>({schemaVersion:2,gameId,characterId,current,activationRevision:revision,selections,
    appearances:[{id:'ordinary',name:'Ordinary appearance',story:timing},{id:'stone',name:'Stone skin — a deliberately long synthetic appearance name for small screen layout',story:timing}],
    activations:[{id:'current',appearanceId:'ordinary',selectionId:current,updatedAt:'2026-01-01T12:00:00Z',reason:'Synthetic selection',activationKind:'artwork-selection'}]});
  await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'synthetic'}))+'.test'})));
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**',async route=>{
    const url=new URL(route.request().url());requests.push({path:url.pathname,selection:url.searchParams.get('selectionId')});
    let body={};
    if(url.pathname==='/games') body={games:[{id:gameId,name:'Synthetic Game',purpose:'test'}]};
    else if(url.pathname==='/game') body={game:{id:gameId,name:'Synthetic Game',purpose:'test'},characters:[character],players:[],memberships:[]};
    else if(url.pathname==='/character-versions') body=history();
    else if(url.pathname==='/character-details') body={record:{gameId,characterId,name:character.name,revision:'e'.repeat(32),details:{schemaVersion:1,role:'Scout',status:'Active',backstory:'A fictional scout.',statistics:[],relationships:[]}}};
    else if(url.pathname==='/character') {
      const selected=[...selections,...previews].find(s=>s.id===(url.searchParams.get('selectionId')||current));
      if(!selected || (url.searchParams.get('appearanceId') && url.searchParams.get('appearanceId')!==selected.appearanceId))
        return route.fulfill({status:404,json:{error:'Exact appearance selection not found'}});
      body={character,selection:selected,appearance:history().appearances.find(a=>a.id===selected.appearanceId)||{id:'candidate-look',name:'Unselected physical-state proposal',story:timing},
        poster:{key:selected.portraitKey,url:`https://test.s3.amazonaws.com/${selected.id}.svg`},
        model:selected.modelKey?{key:selected.modelKey,url:'https://test.s3.amazonaws.com/model.glb',size:1024,cameraOrbit:'0deg 75deg auto',fieldOfView:'30deg'}:null,warnings:[]};
    } else if(url.pathname==='/character-appearance-current') {
      const request=route.request().postDataJSON();posted.push(request);
      current=request.selectionId;revision='d'.repeat(32);
      if(lostResponse && first) {first=false;return route.fulfill({status:503,json:{error:'Response uncertain'}});}
      body={record:{selectionId:current,revision},replayed:posted.length>1};
    } else if(url.pathname==='/assets') body={assets:[],cursor:null};
    return route.fulfill({json:body,headers:{'access-control-allow-origin':'https://panther.place'}});
  });
  await page.route('https://test.s3.amazonaws.com/*.svg',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600"><rect width="400" height="600" fill="tan"/></svg>'}));
  await page.route('https://panther.place/**',route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(pathname==='/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"synthetic",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    const file=pathname==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  return {posted,requests};
}

for(const width of [1280,390]) {
  for(const separateState of [false,true]) test(`exact unselected artwork remains a visible read-only profile at ${width}px, separate state ${separateState}`,async({page},testInfo)=>{
    await page.setViewportSize({width,height:900});const control=await fixture(page,{unselected:true});
    const id=separateState?'preview-state':'preview',appearance=separateState?'candidate-look':'ordinary';
    const target=`https://panther.place/games/example-game/characters/hero?appearance=${appearance}&selection=${id}`;
    await page.goto(target);
    const portrait=page.locator('#character-portrait-only');await expect(portrait).toBeVisible();await expect(portrait).toHaveAttribute('src',new RegExp(`${id}.svg$`));
    await expect.poll(()=>portrait.evaluate(image=>image.complete&&image.naturalWidth>0)).toBe(true);
    await expect(page.getByRole('heading',{name:'Synthetic Hero',exact:true})).toBeVisible();await expect(page.getByRole('region',{name:'Assets',exact:true})).toBeVisible();
    await expect(page.locator('#character-appearance-panel')).toBeHidden();await expect(page.locator('#model-version')).toBeHidden();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path:testInfo.outputPath('exact-edition-profile.png'),fullPage:true});
    await page.reload();await expect(portrait).toHaveAttribute('src',new RegExp(`${id}.svg$`));
    await page.goto('https://panther.place/games/example-game/characters/hero');await expect(portrait).toHaveAttribute('src',/current.svg$/);
    expect(control.posted).toEqual([]);
  });
  test(`historical portrait deep links preserve exact editions without activating them at ${width}px`,async({page},testInfo)=>{
    await page.setViewportSize({width,height:900});const control=await fixture(page);
    const portrait=page.locator('#character-portrait-only');
    for(const [appearance,selection] of [['ordinary','earlier'],['stone','stone']]){
      await page.goto(`https://panther.place/games/example-game/characters/hero?appearance=${appearance}&selection=${selection}`);
      await expect(portrait).toBeVisible();await expect(portrait).toHaveAttribute('src',new RegExp(`${selection}.svg$`));
      await expect(page.locator('#character-profile')).toBeVisible();await expect(page.locator('#character-assets')).toBeVisible();
      expect(control.posted).toEqual([]);
    }
    await page.reload();await expect(portrait).toHaveAttribute('src',/stone.svg$/);
    await page.screenshot({path:testInfo.outputPath('historical-profile.png'),fullPage:true});
    await page.goto('https://panther.place/games/example-game/characters/hero');await expect(portrait).toHaveAttribute('src',/current.svg$/);
    expect(control.posted).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

test('ambiguous old model URL does not substitute current artwork',async({page})=>{
  const control=await fixture(page,{ambiguous:true});
  await page.goto('https://panther.place/games/example-game/characters/hero?model=games%2Fexample-game%2Fassets%2Fcurrent%2Foriginal%2Fmodel.glb');
  await expect(page.locator('#appearance-status')).toContainText('does not identify one complete portrait/model pair');
  await expect(page.locator('#character-portrait-only')).toBeHidden();await expect(page.locator('#model-load')).toBeHidden();
  await expect(page.locator('#character-assets')).toBeVisible();expect(control.posted).toEqual([]);
});

test('missing exact deep link never falls back to current artwork',async({page})=>{
  const control=await fixture(page);
  await page.goto('https://panther.place/games/example-game/characters/hero?appearance=ordinary&selection=missing');
  await expect(page.locator('#characters-status')).toContainText('Exact appearance selection not found');await expect(page.locator('#character-profile')).toBeVisible();
  await expect(page.locator('#character-portrait-only')).toBeHidden();await expect(page.locator('#character-model-area')).toBeHidden();await expect(page.locator('#appearance-history')).toBeHidden();
  expect(control.requests.filter(r=>r.path==='/character').map(r=>r.selection)).toEqual(['missing']);expect(control.posted).toEqual([]);
});
