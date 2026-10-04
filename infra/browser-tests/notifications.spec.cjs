const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');

async function fixture(page,{readFails=false,feedFails=false}={}){
 const records=Array.from({length:12},(_,index)=>({id:String(index).padStart(64,'0'),title:index%2?'Storyboard review requested':'Workflow did not complete successfully',description:`Fictional session ${index+1}`,createdAt:100+index,readAt:null,target:{type:'workflow',gameId:'fictional-game',kind:'editorial',id:`editorial~run-${index}`}}));
 const calls=[];
 await page.addInitScript(()=>sessionStorage.setItem('panther.tokens',JSON.stringify({id_token:'test.'+btoa(JSON.stringify({sub:'fictional-sub',exp:Date.now()/1000+3600,'cognito:username':'example-member'}))+'.test'})));
 await page.route('https://test.execute-api.us-west-2.amazonaws.com/**',async route=>{
  const url=new URL(route.request().url());calls.push({path:url.pathname,method:route.request().method()});
  let json={};
  if(url.pathname==='/notifications'){
   if(feedFails)return route.fulfill({status:503,json:{error:'Notification history unavailable'}});
   const unread=url.searchParams.get('view')==='unread';json={notifications:records.filter(row=>!unread||!row.readAt).slice(0,unread?10:30),cursor:unread?'more':null};
  }else if(url.pathname==='/notifications/read'){
   if(readFails)return route.fulfill({status:500,json:{error:'Unavailable'}});
   const row=records.find(item=>item.id===route.request().postDataJSON().id);row.readAt=1000;json={read:true};
  }else if(url.pathname==='/games')json={games:[{id:'fictional-game',name:'Fictional campaign'}]};
  else if(url.pathname==='/game')json={game:{id:'fictional-game',name:'Fictional campaign'},players:[],memberships:[],characters:[]};
  else if(url.pathname==='/assets')json={assets:[],cursor:null};
  else if(url.pathname==='/dashboard-recent')json={groups:{},counts:{},complete:true};
  else if(url.pathname==='/recordings/live')json={recordings:[]};
  else if(url.pathname==='/workflows')json=url.searchParams.has('id')?{workflow:{schemaVersion:1,id:url.searchParams.get('id'),kind:'editorial',gameId:'fictional-game',title:'Fictional workflow',status:'failed',stages:[],activeStages:[],completedStages:0,totalStages:0}}:{workflows:[],types:[],cursor:null};
  await route.fulfill({json});
 });
 await page.route('https://panther.place/**',route=>{
  const name=new URL(route.request().url()).pathname;
  if(name==='/auth/account')return route.fulfill({json:{username:'example-member',name:'Example Member',picture:'https://panther.place/avatars/moon.svg'}});
  if(name.startsWith('/auth/'))return route.fulfill({json:{}});
  if(name==='/config.js')return route.fulfill({contentType:'application/javascript',body:'window.PANTHER_CONFIG={apiUrl:"https://test.execute-api.us-west-2.amazonaws.com",clientId:"test",cognitoDomain:"https://test.amazoncognito.com",redirectUri:"https://panther.place/"};'});
  if(name==='/vendor/model-viewer.min.js')return route.fulfill({body:'',contentType:'application/javascript'});
  const file=path.join(__dirname,'../../web/media-explorer',['/app.js','/styles.css','/ui-runtime.js','/ui-system.css'].includes(name)||name.startsWith('/avatars/')?name.slice(1):'index.html');
  return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html'});
 });
 return {records,calls};
}

async function usable(locator){
 await expect(locator).toBeVisible();await expect(locator).toBeInViewport();
 expect(await locator.evaluate(el=>{const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return el===hit||el.contains(hit);})).toBe(true);
}

for(const width of [1440,390])test(`avatar and persistent notifications work at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});const {records,calls}=await fixture(page);
 await page.goto('https://panther.place/games/fictional-game/dashboard');
 const avatar=page.getByRole('button',{name:'Account',exact:true}),bell=page.getByRole('button',{name:'Notifications, unread notifications',exact:true});
 await usable(avatar);await usable(bell);await expect(avatar.locator('img')).toHaveAttribute('src','https://panther.place/avatars/moon.svg');
 expect((await bell.boundingBox()).x).toBeLessThan((await avatar.boundingBox()).x);await expect(page.getByTestId('notification-dot')).toBeVisible();
 await avatar.click();await usable(page.getByRole('button',{name:'Account settings',exact:true}));await usable(page.getByRole('button',{name:'Sign out',exact:true}));
 await page.keyboard.press('Escape');await expect(avatar).toBeFocused();await bell.click();
 await expect(page.locator('.notification-popover .notification-row')).toHaveCount(10);
 await usable(page.getByRole('button',{name:'View all notifications →'}));
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:test.info().outputPath(`notification-bell-${width}.png`)});
 await page.getByRole('button',{name:'View all notifications →'}).click();await expect(page).toHaveURL('https://panther.place/notifications');
 await expect(page.locator('.notifications-page .notification-row')).toHaveCount(12);
 await page.locator('.notifications-page .notification-row').first().click();await expect.poll(()=>records[0].readAt).toBe(1000);
 await expect(page).toHaveURL(/\/workflows\/editorial\/editorial~run-0$/);
 await page.goto('https://panther.place/notifications');await expect(page.locator('.notifications-page .notification-row')).toHaveCount(12);
 await expect(page.locator('.notifications-page .notification-row').first().getByLabel('Read',{exact:true})).toBeVisible();
 await page.reload();await expect(page.locator('.notifications-page .notification-row')).toHaveCount(12);
 await page.screenshot({path:test.info().outputPath(`notification-history-${width}.png`)});
 expect(calls.some(call=>/generate|submit/.test(call.path))).toBe(false);
});

test('failed read stays unread and does not navigate',async({page})=>{
 await fixture(page,{readFails:true});await page.goto('https://panther.place/notifications');await page.locator('.notifications-page .notification-row').first().click();
 await expect(page.getByRole('alert')).toContainText('Could not mark');await expect(page).toHaveURL('https://panther.place/notifications');await expect(page.getByTestId('notification-dot')).toBeVisible();await expect(page.locator('.notifications-page .notification-row')).toHaveCount(12);
});

test('failed feed is unavailable rather than an empty inbox',async({page})=>{
 await fixture(page,{feedFails:true});await page.goto('https://panther.place/notifications');
 await expect(page.locator('.notifications-page').getByRole('alert')).toContainText('could not be loaded');await expect(page.getByText('No notifications yet.')).toHaveCount(0);
 await page.getByRole('button',{name:'Notifications',exact:true}).click();await expect(page.locator('.notification-popover').getByRole('alert')).toBeVisible();await usable(page.locator('.notification-popover').getByRole('button',{name:'Retry',exact:true}));
});
