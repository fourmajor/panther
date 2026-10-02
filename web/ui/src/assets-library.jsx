import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {File, FileAudio, FileCode, FileText, FileVideo, Image, Search, Sparkles, Upload} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {Input} from './components/ui/input.jsx';
import {assetLibraryType,assetFileFormat} from './assets-library-data.js';
import {AssetCreateForm} from './asset-create-form.jsx';
import {AssetGenerationStatus} from './asset-generation-status.jsx';

const emptyJobs=[];
const filters=[['all','All'],['map','Maps'],['blueprint','Blueprints'],['location','Locations'],['other','Other']];
const typeNames={map:'Map',blueprint:'Blueprint',location:'Location',other:'Other'};
function AssetThumbnail({asset,onThumbnail}) {
  const host=useRef(null);
  const [url,setUrl]=useState(asset.previewUrl || '');
  const image=asset.contentType?.startsWith('image/');
  const format=assetFileFormat(asset);
  const Icon=image?Image:asset.contentType?.startsWith('audio/')||['WAV','MP3','OGG','FLAC','M4A'].includes(format)?FileAudio:asset.contentType?.startsWith('video/')||['MP4','WEBM','MOV'].includes(format)?FileVideo:['JSON','XML','YAML','YML'].includes(format)?FileCode:['TXT','MD','PDF','DOCX'].includes(format)?FileText:File;
  useEffect(()=>{
    setUrl(asset.previewUrl || '');
    if(!image||asset.previewUrl||!onThumbnail)return;
    let active=true, observer;
    const load=()=>Promise.resolve().then(()=>onThumbnail(asset)).then(value=>{if(active)setUrl(value || '');}).catch(()=>{});
    if(typeof IntersectionObserver==='undefined')load();
    else {observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){observer.disconnect();load();}},{rootMargin:'160px'});observer.observe(host.current);}
    return()=>{active=false;observer?.disconnect();};
  },[asset.key,asset.previewUrl,image,onThumbnail]);
  return <span ref={host} className="assets-card-image">{url?<img src={url} alt="" loading="lazy" onError={()=>setUrl('')}/>:<Icon size={32} aria-hidden="true"/>}</span>;
}
export function AssetsLibrary({gameId,assets=[],loading=false,error='',hasMore=false,onMore,onOpen,onUpload,onGenerate,onThumbnail,onGenerationStatus,initialJobs=emptyJobs,browseFilesHref,onBrowseFiles}) {
  const [type,setType]=useState('all'),[search,setSearch]=useState(''),[form,setForm]=useState(null),[jobs,setJobs]=useState([]),[created,setCreated]=useState([]);
  useEffect(()=>{setJobs(previous=>[...initialJobs,...previous.filter(job=>!initialJobs.some(incoming=>incoming.jobId===job.jobId))]);},[initialJobs]);
  const published=useCallback(job=>{setCreated(previous=>previous.some(asset=>asset.key===job.assetKey)?previous:[...previous,job.asset||{key:job.assetKey,title:job.name,kind:job.type}]);},[]);
  const allAssets=useMemo(()=>[...assets,...created.filter(asset=>!assets.some(existing=>existing.key===asset.key))],[assets,created]);
  const completed=(result,payload)=>{if(form.mode==='upload'){setCreated(previous=>[...previous,result.asset||result]);}else {setJobs(previous=>[{...result,name:result.name||payload.name,type:result.type||payload.type},...previous.filter(job=>job.jobId!==result.jobId)]);}setForm(null);};
  useEffect(()=>{setType('all');setSearch('');setForm(null);setCreated([]);setJobs(initialJobs);},[gameId]);
  const visible=useMemo(()=>allAssets.filter(asset=>(type==='all'||assetLibraryType(asset)===type)&&(!search||[asset.title,asset.name,...(Array.isArray(asset.tags)?asset.tags:[])].filter(Boolean).join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase()))),[allAssets,type,search]);
  return <section className="assets-library" aria-label="Assets">
    {browseFilesHref&&<a className="assets-browse-files" href={browseFilesHref} onClick={onBrowseFiles}>Browse files</a>}
    <div className="assets-toolbar"><label className="assets-search"><Search size={18} aria-hidden="true"/><span className="sr-only">Search assets</span><Input type="search" placeholder="Search assets" value={search} onChange={event=>setSearch(event.target.value)}/></label><div className="assets-actions">{onUpload&&<Button variant="secondary" disabled={Boolean(form)} onClick={()=>setForm({mode:'upload',type})}><Upload size={16} aria-hidden="true"/>Upload</Button>}{onGenerate&&<Button disabled={Boolean(form)} onClick={()=>setForm({mode:'generate',type})}><Sparkles size={16} aria-hidden="true"/>Generate</Button>}</div></div>
    {form&&<AssetCreateForm key={`${gameId}:${form.mode}`} gameId={gameId} mode={form.mode} initialType={form.type} onUpload={onUpload} onGenerate={onGenerate} onComplete={completed} onClose={()=>setForm(null)}/>}
    {jobs.length>0&&<div className="assets-generation-jobs" aria-label="Generation progress">{jobs.map(job=><AssetGenerationStatus key={job.jobId} gameId={gameId} job={job} onGenerationStatus={onGenerationStatus} onOpen={onOpen} onPublished={published}/>)}</div>}
    <div className="assets-filters" role="group" aria-label="Asset type">{filters.map(([value,label])=><Button key={value} variant={type===value?'secondary':'ghost'} className="assets-filter" aria-pressed={type===value} onClick={()=>setType(value)}>{label}</Button>)}</div>
    {error&&<p role="alert" className="assets-error">{error}</p>}
    <div className="assets-grid" aria-busy={loading}>
      {loading&&!allAssets.length?Array.from({length:6},(_,i)=><div key={i} className="assets-card assets-card-placeholder" aria-hidden="true"><span className="assets-card-image ui-skeleton"/><span className="ui-skeleton assets-title-skeleton"/></div>):visible.map(asset=><Button variant="secondary" key={asset.key} className="assets-card" onClick={()=>onOpen?.(asset)}><AssetThumbnail asset={asset} onThumbnail={onThumbnail}/><span className="assets-card-body"><span className="assets-card-title">{asset.title||asset.name||asset.key.split('/').at(-1)}</span><span className="assets-card-type">{typeNames[assetLibraryType(asset)]} · <span className="assets-card-format">{assetFileFormat(asset)}</span></span></span></Button>)}
    </div>
    {!loading&&!visible.length&&!error&&<p className="assets-empty">{search?'No matching assets.':type==='all'?'No assets yet.':`No ${filters.find(([value])=>value===type)[1].toLowerCase()} yet.`}</p>}
    {hasMore&&<Button variant="secondary" disabled={loading} className="assets-more" onClick={onMore}>{loading?'Loading…':'Load more'}</Button>}
  </section>;
}
