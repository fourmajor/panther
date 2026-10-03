const {test, expect} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const {MODEL_VIEWER_BUNDLE_PATH} = require('../dist/lib/panther-media-explorer-stack');

const designs = ['studio','chronicle','cinema','mission','poster','field'];
async function fixture(page) {
  await page.addInitScript(() => sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-member'}))+'.test'})));
  const reads=[];
  await page.route('https://test.execute-api.us-west-2.amazonaws.com/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    reads.push(pathname);
    const game={id:'synthetic-game',name:'The Lantern Expedition',purpose:'campaign',ruleset:'Synthetic Rules',visualStyle:'photorealistic'};
    const bodies={
      '/games':{games:[game]},
      '/game':{game,canEditGame:true,gameSettings:{description:'A fictional campaign for interface testing.',descriptionRevision:null},visualStyles:[{id:'photorealistic',label:'Photorealistic'}],players:[{id:'person',name:'Example Player'}],characters:[],memberships:[{playerId:'person',role:'player',characterIds:[]}]},
      '/dashboard-recent':{complete:true,groups:{characters:[],transcripts:[],videos:[],chapters:[]},counts:{characters:0,transcripts:0,videos:0,chapters:0}},
      '/recordings/live':{recordings:[]},
      '/characters':{characters:[],cursor:null},
      '/objects':{prefixes:[],objects:[],cursor:null},
      '/assets':{assets:[{key:'games/synthetic-game/assets/review/original/plan.json',kind:'movie-review-plan',name:'plan.json',metadata:{title:'Last session storyboard',sessionId:'synthetic-session'}}],cursor:null},
    };
    await route.fulfill({json:bodies[pathname] || {},headers:{'access-control-allow-origin':'https://panther.place'}});
  });
  await page.route('https://panther.place/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    if(pathname==='/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    const file=pathname==='/vendor/model-viewer.min.js'?MODEL_VIEWER_BUNDLE_PATH:path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  return reads;
}

async function accessible(locator, width) {
  await expect(locator).toBeVisible();
  await expect(locator).toBeInViewport();
  const box=await locator.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(-1);
  expect(box.x+box.width).toBeLessThanOrEqual(width+1);
  expect(await locator.evaluate(element=>{const r=element.getBoundingClientRect();const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return hit===element||element.contains(hit);})).toBe(true);
}

for(const width of [1440,390]) for(const design of designs) {
  test(`${design} is a usable distinct shell at ${width}px`,async({page})=>{
    await page.setViewportSize({width,height:1000});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const reads=await fixture(page);
    await page.goto(`https://panther.place/games/synthetic-game/dashboard?ui=${design}`);
    await expect(page.locator('html')).toHaveAttribute('data-interface',design);
    await expect(page.locator('#dashboard-name')).toHaveText('The Lantern Expedition');
    await accessible(page.locator('#design-open'),width);
    for(const link of await page.locator('#primary-nav a').all()) await accessible(link,width);
    const contrast=await page.locator('#primary-nav a[aria-current]').evaluate(el=>{
      const style=getComputedStyle(el);
      const luminance=color=>{const values=color.match(/[\d.]+/g).slice(0,3).map(n=>{const v=Number(n)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return values[0]*.2126+values[1]*.7152+values[2]*.0722;};
      const background=style.backgroundColor==='rgba(0, 0, 0, 0)'?getComputedStyle(document.documentElement).getPropertyValue('--panel'):style.backgroundColor;
      const canvas=document.createElement('canvas').getContext('2d');canvas.fillStyle=background;
      const hex=canvas.fillStyle;const normalized=hex.startsWith('#')?'rgb('+[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)).join(',')+')':hex;
      const a=luminance(style.color),b=luminance(normalized);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
    });
    expect(contrast).toBeGreaterThanOrEqual(4.5);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
    await accessible(page.locator('#storyboard-entry'),width);
    await expect(page.locator('#approval-inbox')).toContainText('Last session storyboard');
    if(design==='studio')await expect(page.locator('#workspace-home')).toBeHidden();
    else {
      await expect(page.locator('#dashboard-sections')).toBeHidden();
      await expect(page.locator('#workspace-home')).toHaveAttribute('data-layout',design);
      const signature={chronicle:'.workspace-split',field:'.workspace-index input',cinema:'.workspace-feature',mission:'.workspace-kanban',poster:'.workspace-pinboard'}[design];
      await expect(page.locator(signature)).toBeVisible();
      if(['chronicle','field'].includes(design)){
        await page.locator('.workspace-index button').filter({hasText:'The archive'}).click();
        await expect(page.locator('.workspace-page')).toContainText('The archive');
      }
    }
    if(width===1440) {
      const header=await page.locator('.masthead').boundingBox();
      if(design==='chronicle') expect(header.width).toBeLessThan(250);
      if(design==='field') expect(header.x).toBeGreaterThan(1000);
    }
    await page.screenshot({path:test.info().outputPath(`${design}-${width}.png`),fullPage:true});
    await page.locator('#primary-nav').getByRole('link',{name:'Settings',exact:true}).click();
    await expect(page.locator('#game-name')).toHaveValue('The Lantern Expedition');
    await page.locator('#game-description').fill('Unsaved draft must survive every shell.');
    const route=page.url();
    const beforeReads=reads.filter(item=>item==='/game').length;
    await page.locator('#design-open').click();
    await expect(page.locator('#design-atlas')).toBeVisible();
    await expect(page.locator('.atlas-option')).toHaveCount(6);
    if(design==='studio') await page.screenshot({path:test.info().outputPath(`atlas-${width}.png`)});
    const other=design==='field'?'chronicle':'field';
    const choice=page.locator(`[data-design=${other}]`);
    // On a small screen the contact sheet deliberately scrolls, not a clipped carousel.
    await choice.scrollIntoViewIfNeeded();
    await accessible(choice,width);
    await choice.click();
    await expect(page.locator('html')).toHaveAttribute('data-interface',other);
    await expect(page.locator('#game-description')).toHaveValue('Unsaved draft must survive every shell.');
    expect(page.url()).toBe(route);
    expect(reads.filter(item=>item==='/game').length).toBe(beforeReads);
    await accessible(page.locator('#design-keep'),width);
    await page.locator('#design-compare').click();
    await expect(page.locator('html')).toHaveAttribute('data-interface','studio');
    await page.locator('#design-compare').click();
    await expect(page.locator('html')).toHaveAttribute('data-interface',other);
    await page.locator('#design-keep').click();
    await expect(page.locator('#design-preview-tools')).toBeHidden();
    expect(await page.evaluate(()=>localStorage.getItem('panther.interface.v1'))).toBe(other);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-interface',other);
    await expect(page.locator('#game-name')).toHaveValue('The Lantern Expedition');
    expect(errors).toEqual([]);
  });
}

test('Atlas keyboard, invalid preference, cancellation and blocked storage',async({page})=>{
  await fixture(page);
  await page.addInitScript(()=>localStorage.setItem('panther.interface.v1','not-a-design'));
  await page.goto('https://panther.place/games/synthetic-game/dashboard?ui=invalid');
  await expect(page.locator('html')).toHaveAttribute('data-interface','studio');
  await page.keyboard.press('Shift+D');
  await expect(page.locator('#design-atlas')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('#design-atlas')).toBeHidden();
  await expect(page.locator('#design-open')).toBeFocused();
  await page.locator('#design-open').click();
  await page.locator('[data-design=poster]').click();
  await page.keyboard.press('Escape');
  await expect(page.locator('html')).toHaveAttribute('data-interface','studio');
  await page.locator('#primary-nav').getByRole('link',{name:'Settings',exact:true}).click();
  await page.locator('#game-description').focus();
  await page.keyboard.press('Shift+D');
  await expect(page.locator('#design-atlas')).toBeHidden();
  await page.evaluate(()=>{const original=Storage.prototype.setItem;Storage.prototype.setItem=function(...args){if(this===localStorage)throw new Error('blocked');return original.apply(this,args);};});
  await page.locator('#design-open').click();
  await page.locator('[data-design=cinema]').click();
  await page.locator('#design-keep').click();
  await expect(page.locator('#design-feedback')).toContainText('prevented saving');
  await expect(page.locator('html')).toHaveAttribute('data-interface','cinema');
});

test('storyboard approval doorway is game-scoped and does not generate or approve anything',async({page})=>{
  const reads=await fixture(page);
  await page.goto('https://panther.place/games/synthetic-game/dashboard');
  const entry=page.locator('#storyboard-entry');
  await expect(entry).toHaveAttribute('href','/games/synthetic-game/videos?review=1');
  await entry.click();
  await expect(page.locator('#video-approval-inbox')).toContainText('Last session storyboard');
  await expect(page.locator('#video-approval-inbox .approval-card a')).toHaveAttribute('href',/videos\?project=games%2Fsynthetic-game/);
  expect(reads.every(path=>!path.includes('generate')&&!path.includes('submit'))).toBe(true);
});
