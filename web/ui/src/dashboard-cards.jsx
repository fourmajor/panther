import React from 'react';
import {AssetThumbnail} from './assets-library.jsx';
import {Users,Mic,BookOpen,Clapperboard,Folder,ChevronRight} from 'lucide-react';

const sections = [
  {id:'characters',key:'characters',label:'Characters',unit:'Character',Icon:Users,empty:'The people and creatures in your game, with portraits, details and related assets.'},
  {id:'sessions',key:'sessions',fallback:'transcripts',label:'Sessions',unit:'Session',Icon:Mic,empty:'Recordings of you and your friends playing a game, transcribed to generate novels, TV episodes and other assets.'},
  {id:'novel',key:'chapters',label:'Novel',unit:'Chapter',Icon:BookOpen,empty:'Write chapters yourself or generate a novel from your game and recorded sessions.'},
  {id:'videos',key:'episodes',fallback:'videos',label:'Episodes',unit:'Episode',Icon:Clapperboard,empty:'Plan episodes as ordered scenes and bring them to life with generated video.'},
  {id:'assets',key:'assets',label:'Assets',unit:'Asset',Icon:Folder,empty:'Images, maps, videos, audio and other files you upload or generate for your game.'},
];
const plainClick = event => !(event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey);

export function DashboardCards({gameId,data,onNavigate,onPreview,request}) {
  async function thumbnail(asset) {
    if(asset.contentType?.startsWith('image/'))return (await request('/image-links',{}, {body:{gameId,keys:[asset.key]}})).images?.[asset.key]?.url||'';
    if(asset.contentType?.startsWith('video/')&&asset.thumbnailKey?.startsWith(`games/${gameId}/`))return (await request('/object-url',{key:asset.thumbnailKey})).url||'';
    return '';
  }
  const base=`/games/${encodeURIComponent(gameId)}`;
  const navigate = event => {if(plainClick(event)){event.preventDefault();onNavigate(event.currentTarget.getAttribute('href'));}};
  function itemHref(section,item) {
    if(section.id==='characters')return `${base}/characters/${encodeURIComponent(item.id)}`;
    if(section.id==='novel')return `${base}/novel/${encodeURIComponent(item.id)}`;
    if(section.id==='videos'&&item.id)return `${base}/episodes/${encodeURIComponent(item.id)}`;
    return `${base}/assets?asset=${encodeURIComponent(item.key)}`;
  }
  return sections.map(section=>{
    const {Icon}=section;
    const key=data?.groups?.[section.key]?section.key:section.fallback||section.key;
    const items=data?.groups?.[key]||[];
    const visible=items.slice(0,section.id==='assets'?6:5);
    const count=data?.counts?.[key];
    return <section key={section.id} className="dashboard-card" data-section={section.id}>
      <h2><a className="dashboard-card-link flex items-center gap-3 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" href={`${base}/${section.id==='videos'?'episodes':section.id}`} onClick={navigate}>
        <Icon className="shrink-0 text-primary" size={22} aria-hidden="true"/>
        <span>{count>0?`${count} ${section.id==='novel'?(count===1?'Chapter':'Chapters'):(count===1?section.unit:section.label)}`:section.label}</span>
        <ChevronRight className="ml-auto shrink-0 text-muted-foreground" size={22} aria-hidden="true"/>
      </a></h2>
      {!data?<div className="h-16 animate-pulse rounded bg-muted/30" aria-label="Loading recent records"/>:count===0?<p>{section.empty}</p>:<>
        <ul className={`dashboard-recent-links ${section.id==='assets'?'grid grid-cols-3 gap-2':''}`} aria-label={`Recent ${section.label.toLowerCase()}`}>
          {visible.map(item=>{
            const title=item.title||item.metadata?.title||item.name;
            return <li key={item.id||item.key}><a className={section.id==='assets'?'block rounded-md outline outline-2 outline-transparent outline-offset-2 hover:outline-primary focus-visible:outline-primary':undefined} href={itemHref(section,item)} onClick={event=>{if(!plainClick(event))return;event.preventDefault();if(item.key)onPreview(item);else onNavigate(itemHref(section,item));}} aria-label={title} title={title}>
              {section.id==='assets'?<AssetThumbnail asset={item} gameId={gameId} onThumbnail={thumbnail} className="dashboard-asset-thumbnail"/>:title}
            </a></li>;
          })}
        </ul>
        {count>visible.length&&<a className="dashboard-more mt-2 block text-sm text-muted-foreground hover:text-primary" href={`${base}/${section.id==='videos'?'episodes':section.id}`} onClick={navigate}>and {count-visible.length} more</a>}
      </>}
    </section>;
  });
}
