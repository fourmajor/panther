const {test,expect}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path');
for(const width of [390,1440]) test(`unlisted watch and download without login at ${width}`,async({page})=>{
  await page.setViewportSize({width,height:900});
  const token='a'.repeat(64),origin='https://panther.place';
  const html=fs.readFileSync(path.join(__dirname,'../lambda/media-api/share.html'),'utf8')
    .replaceAll('{{title}}','The Lantern at Sea').replaceAll('{{token}}',token).replace('{{social}}','')
    .replace('{{player}}',`<video controls playsinline preload="none" aria-label="Shared video" poster="/s/${token}/preview" src="/s/${token}/watch"></video>`);
  await page.route(origin+'/**',async route=>{
    const p=new URL(route.request().url()).pathname;
    if(p==='/share.css')return route.fulfill({contentType:'text/css',body:fs.readFileSync(path.join(__dirname,'../../web/media-explorer/share.css'),'utf8')});
    if(p.endsWith('/download'))return route.fulfill({contentType:'video/mp4',headers:{'content-disposition':'attachment; filename="film.mp4"'},body:Buffer.from('synthetic download')});
    if(p.endsWith('/watch'))return route.fulfill({status:204});
    if(p.endsWith('/preview'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675"><rect width="1200" height="675" fill="#294333"/><circle cx="600" cy="337" r="100" fill="#e6bc68"/></svg>'});
    return route.fulfill({contentType:'text/html',body:html});
  });
  await page.goto(origin+'/s/'+token);
  await expect(page.getByRole('heading',{name:'The Lantern at Sea'})).toBeVisible();
  await expect(page.getByLabel('Shared video')).toBeVisible();
  await expect(page.getByLabel('Shared video')).toHaveAttribute('poster', '/s/'+token+'/preview');
  await expect.poll(()=>page.evaluate(()=>document.querySelector('video').getBoundingClientRect().height)).toBeGreaterThan(190);
  const link=page.getByRole('link',{name:'Download file'});
  const box=await link.boundingBox();expect(box.y+box.height).toBeLessThan(900);expect(box.height).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`share-${width}.png`),fullPage:true});
  const pending=page.waitForEvent('download');await link.click();const dl=await pending;expect(dl.suggestedFilename()).toBe('film.mp4');
  await page.getByRole('link',{name:'Open directly'}).focus();await expect(page.getByRole('link',{name:'Open directly'})).toBeFocused();
  expect(await page.context().cookies()).toEqual([]);
});
