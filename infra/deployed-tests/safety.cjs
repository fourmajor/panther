const origin='https://panther.place';
function publicRead(url,method,navigation=false){
 const parsed=new URL(url);
 if(parsed.origin!==origin||method!=='GET'||parsed.username||parsed.password)return false;
 if(navigation)return ['/', '/account','/games/qa-campaign/assets','/games/qa-campaign/sessions'].includes(parsed.pathname);
 return /^\/(?:releases\/[a-f0-9]+\/)?[a-z0-9_.-]+\.(?:js|css|svg|png|webp|ico|woff2?)$/i.test(parsed.pathname)||/^\/(?:vendor|avatars|style-previews)\/[a-z0-9_.-]+\.(?:js|svg|png|webp)$/i.test(parsed.pathname);
}
module.exports={origin,publicRead};
