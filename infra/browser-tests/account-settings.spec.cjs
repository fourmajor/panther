const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const jwt='test.'+Buffer.from(JSON.stringify({exp:Date.now()/1000+3600,'cognito:username':'example-member'})).toString('base64url')+'.test';

async function fixture(context,{signedIn=true,mfa=false}={}) {
  const calls=[];
  const profile={username:'example-member',name:'Example Member',picture:'',email:'member@example.invalid',emailVerified:true,totpEnabled:mfa};
  await context.route('https://test.execute-api.us-west-2.amazonaws.com/**',route=>route.fulfill({json:{games:[{id:'test-game',name:'Test Game'}],game:{id:'test-game',name:'Test Game'},players:[],memberships:[],assets:[],characters:[],objects:[],prefixes:[],cursor:null},headers:{'access-control-allow-origin':'https://panther.place'}}));
  await context.route('https://test.amazoncognito.com/logout*',route=>route.fulfill({contentType:'text/html',body:'Signed out'}));
  await context.route('https://panther.place/**',async route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(pathname==='/auth/account'||pathname==='/auth/recovery') {
      const body=route.request().postDataJSON(); calls.push(body);
      expect(route.request().method()).toBe('POST');
      expect((await route.request().allHeaders()).origin).toBe('https://panther.place');
      if(body.action==='get') return route.fulfill({json:profile});
      if(body.action==='profile') Object.assign(profile,{name:body.name,picture:body.picture});
      if(body.action==='mfa-start') return route.fulfill({json:{secretCode:'SYNTHETIC-SETUP-KEY'}});
      if(body.action==='mfa-confirm'&&body.code==='000000') return route.fulfill({status:400,json:{error:'The verification code is incorrect. Try again.'}});
      if(body.action==='mfa-confirm') profile.totpEnabled=true;
      if(body.action==='mfa-disable') profile.totpEnabled=false;
      return route.fulfill({json:body.action==='forgot'?{sent:true}:body.action==='sign-out-everywhere'?{signedOut:true}:{saved:true}});
    }
    if(pathname.startsWith('/auth/')) return route.fulfill({status:signedIn?200:401,json:signedIn?{id_token:jwt,expires_in:3600}:{}});
    if(pathname==='/config.js') return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
    if(pathname==='/vendor/model-viewer.min.js') return route.fulfill({contentType:'application/javascript',body:''});
    const source=path.join(__dirname,'../../web/media-explorer',pathname.startsWith('/avatars/')?pathname.slice(1):['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(pathname)?pathname.slice(1):'index.html');
    return route.fulfill({body:fs.readFileSync(source),contentType:source.endsWith('.svg')?'image/svg+xml':source.endsWith('.js')?'application/javascript':source.endsWith('.css')?'text/css':'text/html'});
  });
  return {calls,profile};
}

async function visibleControl(locator) {
  await locator.scrollIntoViewIfNeeded();
  await expect(locator).toBeInViewport();
  const box=await locator.boundingBox();
  expect(await locator.evaluate((node,p)=>node.contains(document.elementFromPoint(p.x,p.y)),{x:box.x+box.width/2,y:box.y+box.height/2})).toBe(true);
}

for(const width of [1280,390]) {
  test(`self-service account profile, email, passwords and authenticator at ${width}`,async({page,context},testInfo)=>{
    await page.setViewportSize({width,height:900}); const {calls,profile}=await fixture(context);
    await page.goto('https://panther.place/media');
    await visibleControl(page.getByRole('button',{name:'Account',exact:true}));
    await page.getByRole('button',{name:'Account',exact:true}).click();
    await expect(page).toHaveURL('https://panther.place/account');
    const dialog=page.locator('#account-page');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('navigation',{name:'Account sections'})).toHaveCount(0);
    await expect(dialog.locator('.account-section')).toHaveCount(5);
    await expect(dialog.getByLabel('Display name')).toHaveValue('Example Member');
    await dialog.getByLabel('Display name').focus(); await page.keyboard.press('Tab');
    await expect(dialog.getByLabel('Avatar',{exact:true})).toBeFocused();
    await page.keyboard.press('Tab'); await expect(dialog.getByRole('button',{name:'Save profile',exact:true})).toBeFocused();
    await dialog.getByLabel('Display name').fill('New Example Name');
    await dialog.getByLabel('Avatar',{exact:true}).selectOption('https://panther.place/avatars/moon.svg');
    await expect(dialog.getByAltText('Selected avatar')).toBeVisible();
    await visibleControl(dialog.getByRole('button',{name:'Save profile',exact:true}));
    await dialog.getByRole('button',{name:'Save profile',exact:true}).click();
    await expect(dialog).toContainText('Profile saved.'); expect(profile.name).toBe('New Example Name');
    await page.screenshot({path:testInfo.outputPath(`account-profile-${width}.png`)});
    await dialog.getByLabel('Email address',{exact:true}).fill('new-member@example.invalid');
    await dialog.getByRole('button',{name:'Send email verification',exact:true}).click();
    await expect(dialog).toContainText('your old address remains active until verified');
    await dialog.getByLabel('Email verification code').fill('123456');
    await dialog.getByRole('button',{name:'Verify email',exact:true}).click();
    await expect(dialog).toContainText('Email verified.');
    await dialog.getByLabel('Current password',{exact:true}).fill('Synthetic-old!123');
    await dialog.getByLabel('New password',{exact:true}).fill('Synthetic-new!123');
    await dialog.getByLabel('Confirm new password',{exact:true}).fill('Synthetic-new!123');
    await dialog.getByRole('button',{name:'Change password',exact:true}).click();
    await expect(dialog).toContainText('Password changed.');
    await expect(dialog.getByLabel('Current password',{exact:true})).toHaveValue('');
    await dialog.getByRole('button',{name:'Set up authenticator',exact:true}).click();
    await expect(dialog.getByLabel('Authenticator setup key')).toHaveValue('SYNTHETIC-SETUP-KEY');
    await dialog.getByLabel('Authenticator code',{exact:true}).fill('000000');
    await dialog.getByRole('button',{name:'Enable authenticator',exact:true}).click();
    await expect(dialog).toContainText('verification code is incorrect');
    await dialog.getByLabel('Authenticator code',{exact:true}).fill('123456');
    await dialog.getByRole('button',{name:'Enable authenticator',exact:true}).click();
    await expect(dialog).toContainText('Authenticator enabled.');
    await expect(dialog.getByLabel('Authenticator setup key')).toHaveCount(0);
    await expect(dialog.getByRole('button',{name:'Set up authenticator',exact:true})).not.toBeVisible();
    await expect(dialog).toContainText('Authenticator MFA is enabled.');
    await page.screenshot({path:testInfo.outputPath(`account-authenticator-${width}.png`)});
    await visibleControl(page.getByRole('link',{name:'Back to game'}));
    await page.getByRole('link',{name:'Back to game'}).click();
    await expect(dialog).not.toBeVisible();
    const stored=await page.evaluate(()=>JSON.stringify([sessionStorage,localStorage]));
    expect(stored).not.toMatch(/SETUP-KEY|Synthetic-old|Synthetic-new/);
    expect(calls.filter(v=>v.action==='mfa-confirm')).toHaveLength(2);
    expect(calls.every(v=>!Object.hasOwn(v,'AccessToken')&&!Object.hasOwn(v,'UserPoolId'))).toBe(true);
  });
}

test('authenticator removal and global sign-out require explicit acknowledgement',async({page,context})=>{
  const {calls}=await fixture(context,{mfa:true}); await page.goto('https://panther.place/media');
  await page.getByRole('button',{name:'Account',exact:true}).click();
  const dialog=page.locator('#account-page');
  await dialog.getByRole('button',{name:'Disable authenticator',exact:true}).click();
  await expect(dialog).toContainText('Confirm that you want to remove');
  expect(calls.some(v=>v.action==='mfa-disable')).toBe(false);
  await dialog.getByLabel('I understand this removes authenticator protection').check();
  await dialog.getByRole('button',{name:'Disable authenticator',exact:true}).click();
  await expect(dialog).toContainText('Authenticator disabled.');
  await dialog.getByRole('button',{name:'Sign out everywhere',exact:true}).click();
  await expect(dialog).toContainText('Confirm that you want to sign out all devices');
  await expect(dialog).toContainText('one-hour expiry');
  await dialog.getByLabel('Sign out all my devices').check();
  await dialog.getByRole('button',{name:'Sign out everywhere',exact:true}).click();
  await expect(page).toHaveURL(/amazoncognito.com\/logout/);
  expect(calls.some(v=>v.action==='sign-out-everywhere')).toBe(true);
});

for(const width of [1280,390]) {
  test(`signed-out recovery is a visible keyboard-accessible text link at ${width}`,async({page,context},testInfo)=>{
    await page.setViewportSize({width,height:900});
    await fixture(context,{signedIn:false}); await page.goto('https://panther.place/media');
    const signIn=page.getByRole('button',{name:'Sign in',exact:true});
    const recovery=page.getByRole('button',{name:'Forgot password?'});
    for(const control of [signIn,recovery]) {
      await expect(control).toBeVisible();
      await expect(control).toBeInViewport();
      const box=await control.boundingBox();
      expect(box.height).toBeGreaterThanOrEqual(36);
      expect(await control.evaluate((node,p)=>node.contains(document.elementFromPoint(p.x,p.y)),{x:box.x+box.width/2,y:box.y+box.height/2})).toBe(true);
    }
    await expect(recovery).toHaveCSS('text-decoration-line','underline');
    await expect(recovery).toHaveCSS('border-top-width','0px');
    await expect(recovery).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
    await signIn.focus(); await page.keyboard.press('Tab');
    await expect(recovery).toBeFocused();
    await expect(recovery).toHaveCSS('outline-style','solid');
    await page.screenshot({path:testInfo.outputPath(`sign-in-recovery-${width}.png`)});
    await page.keyboard.press('Enter');
    await expect(page.locator('#account-page')).toBeVisible();
    await page.getByRole('button',{name:'Back to sign in'}).click();
    await expect(recovery).toBeVisible();
    await recovery.click();
    await expect(page.locator('#account-page')).toBeVisible();
  });
}

test('signed-out recovery uses generic acknowledgement and clears new passwords',async({page,context})=>{
  const {calls}=await fixture(context,{signedIn:false}); await page.goto('https://panther.place/media');
  await page.getByRole('button',{name:'Forgot password?'}).click();
  const dialog=page.locator('#account-page');
  await dialog.getByLabel('Username',{exact:true}).fill('example-member');
  await dialog.getByRole('button',{name:'Send recovery code',exact:true}).click();
  await expect(dialog).toContainText('If this account can recover by email');
  await dialog.getByLabel('Recovery code',{exact:true}).fill('123456');
  await dialog.getByLabel('New password',{exact:true}).fill('Synthetic-new!123');
  await dialog.getByLabel('Confirm new password',{exact:true}).fill('Synthetic-new!123');
  await dialog.getByRole('button',{name:'Reset password',exact:true}).click();
  await expect(dialog).toContainText('Password reset.');
  await expect(dialog.getByLabel('New password',{exact:true})).toHaveValue('');
  expect(calls.map(v=>v.action)).toEqual(['forgot','confirm']);
  await page.getByRole('button',{name:'Back to sign in'}).click(); await expect(dialog).not.toBeVisible();
  await expect(page.locator('#account-settings-body')).toBeEmpty();
});

test('closing account setup discards a delayed authenticator secret',async({page,context})=>{
  await fixture(context); let release,requested;
  const seen=new Promise(resolve=>requested=resolve), held=new Promise(resolve=>release=resolve);
  await context.route('https://panther.place/auth/account',async route=>{
    if(route.request().postDataJSON().action!=='mfa-start')return route.fallback();
    requested(); await held; return route.fulfill({json:{secretCode:'DELAYED-SYNTHETIC-SECRET'}});
  });
  await page.goto('https://panther.place/media'); await page.getByRole('button',{name:'Account',exact:true}).click();
  await page.getByRole('button',{name:'Set up authenticator',exact:true}).click(); await seen;
  await page.getByRole('link',{name:'Back to game'}).click();
  const completed=page.waitForResponse(response=>response.url().endsWith('/auth/account'));
  release(); await completed;
  await expect(page.locator('#account-settings-body')).toBeEmpty();
  await expect(page.getByText('DELAYED-SYNTHETIC-SECRET')).toHaveCount(0);
});

test('Account supports direct URLs and browser back while discarding enrollment secrets',async({page,context})=>{
  const {calls}=await fixture(context);
  await page.goto('https://panther.place/account');
  await expect(page.getByRole('heading',{name:'Account',exact:true})).toBeVisible();
  await expect(page.getByLabel('Display name')).toHaveValue('Example Member');
  await page.getByRole('link',{name:'Back to game'}).click();
  await expect(page.locator('#dashboard')).toBeVisible();
  await page.getByRole('button',{name:'Account',exact:true}).click();
  await page.getByRole('button',{name:'Set up authenticator',exact:true}).click();
  await expect(page.getByLabel('Authenticator setup key')).toBeVisible();
  await page.goBack();
  await expect(page.locator('#account-settings-body')).toBeEmpty();
  await page.goForward();
  await expect(page.getByLabel('Display name')).toBeVisible();
  await expect(page.getByLabel('Authenticator setup key')).toHaveCount(0);
  expect(calls.filter(call=>call.action==='get')).toHaveLength(3);
});

test('Password recovery supports a direct signed-out URL',async({page,context})=>{
  await fixture(context,{signedIn:false});
  await page.goto('https://panther.place/account/recovery');
  await expect(page.getByRole('heading',{name:'Password recovery',exact:true})).toBeVisible();
  await expect(page.getByLabel('Username',{exact:true})).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

for(const width of [1280,390])test(`Account header return and independent section stacks at ${width}px`,async({page,context},testInfo)=>{
  await page.setViewportSize({width,height:900});await fixture(context);
  await page.goto('https://panther.place/games/test-game/characters');
  const account=page.getByRole('button',{name:'Account',exact:true});
  await expect(account).toHaveAttribute('title','Account');await expect(account).toHaveText('');
  await expect(account.locator('svg')).toBeVisible();
  await account.click();const panel=page.locator('#account-page');
  await expect(panel.locator('.account-section')).toHaveCount(5);
  await expect(account).toBeHidden();
  const back=page.locator('.masthead').getByRole('link',{name:'Back to game',exact:true});
  await expect(back).toHaveAttribute('href','/games/test-game/characters');
  await expect(back).toHaveAttribute('title','Back to game');await expect(back).toHaveText('');
  await expect(back.locator('svg')).toBeVisible();await expect(back).toBeInViewport();
  const backBox=await back.boundingBox();expect(backBox.width).toBeGreaterThanOrEqual(44);expect(backBox.height).toBeGreaterThanOrEqual(44);
  expect(await back.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));})).toBe(true);
  await expect(panel.getByRole('button',{name:'Back to game',exact:true})).toHaveCount(0);
  const headings=panel.locator('.account-section h3');
  await expect(headings).toHaveText(['Profile','Email & recovery','Password','Authenticator security','Sessions']);
  const sections=panel.locator('.account-section'), boxes=await sections.evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,bottom:r.bottom};}));
  if(width>700){
    expect(boxes[0].x).toBe(boxes[1].x);expect(boxes[2].x).toBe(boxes[3].x);expect(boxes[3].x).toBe(boxes[4].x);
    expect(boxes[2].x).toBeGreaterThan(boxes[0].x);expect(boxes[2].y).toBeCloseTo(boxes[0].y,0);
    expect(boxes[1].y-boxes[0].bottom).toBeCloseTo(24,0);expect(boxes[3].y-boxes[2].bottom).toBeCloseTo(24,0);expect(boxes[4].y-boxes[3].bottom).toBeCloseTo(24,0);
  }else{for(let i=1;i<boxes.length;i++){expect(boxes[i].x).toBe(boxes[0].x);expect(boxes[i].y).toBeGreaterThanOrEqual(boxes[i-1].bottom);}}
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`account-stacks-${width}.png`),fullPage:true});
  await back.focus();await page.keyboard.press('Enter');await expect(page).toHaveURL('https://panther.place/games/test-game/characters');
  await expect(account).toBeVisible();await expect(back).toBeHidden();
  await account.click();await panel.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page).toHaveURL(/^https:\/\/test.amazoncognito.com\/logout\?/);
});
