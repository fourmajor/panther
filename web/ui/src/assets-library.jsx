import {createPortal} from 'react-dom';
import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {FolderOpen, File, FileAudio, FileCode, FileText, FileVideo, Image, Trash2, Search, Sparkles, Upload} from 'lucide-react';
import {useQuery,useInfiniteQuery} from '@tanstack/react-query';
import {Button} from './components/ui/button.jsx';
import {MultiSelect} from './components/ui/multi-select.jsx';
import {Input} from './components/ui/input.jsx';
import {assetLibraryType,assetFileFormat,assetIsImage,assetTypeLabel,ordinaryLibraryAsset} from './assets-library-data.js';
import {Dialog,DialogContent,DialogTitle,DialogDescription} from './components/ui/dialog.jsx';
import {AssetCreateForm} from './asset-create-form.jsx';
import {AssetGenerationStatus} from './asset-generation-status.jsx';

const emptyJobs=[];
const baseFilters=[['all','All'],['map','Maps'],['blueprint','Blueprints'],['location','Locations'],['portrait','Portraits'],['artwork','Artwork'],['video','Videos'],['audio','Audio'],['document','Documents'],['model-3d','3D'],['other','Other']];

function AssetThumbnail({asset,onThumbnail,gameId}) {
  const host=useRef(null);
  const [visible,setVisible]=useState(false),[failedUrl,setFailedUrl]=useState('');
  const image=assetIsImage(asset);
  const format=assetFileFormat(asset);
  const video=asset.contentType?.startsWith('video/')||['MP4','WEBM','MOV','M4V'].includes(format);
  const Icon=image?Image:asset.contentType?.startsWith('audio/')||['WAV','MP3','OGG','FLAC','M4A'].includes(format)?FileAudio:asset.contentType?.startsWith('video/')||['MP4','WEBM','MOV'].includes(format)?FileVideo:['JSON','XML','YAML','YML'].includes(format)?FileCode:['TXT','MD','PDF','DOCX'].includes(format)?FileText:File;
  useEffect(()=>{
    setFailedUrl('');
    if(!image&&!video)return;
    if(typeof IntersectionObserver==='undefined'){setVisible(true);return;}
    const observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:'160px'});
    observer.observe(host.current);
    return()=>observer.disconnect();
  },[asset.key,image,video]);
  const preview=useQuery({queryKey:['asset-thumbnail',gameId,asset.key],queryFn:()=>onThumbnail(asset),enabled:(image||video)&&visible&&!asset.previewUrl&&Boolean(onThumbnail),staleTime:240000,retry:false,refetchInterval:query=>video&&!query.state.data&&!query.state.error?3000:false});
  const url=asset.previewUrl||preview.data||'';
  return <span ref={host} className="assets-card-image">{url&&url!==failedUrl?<img src={url} alt="" loading="lazy" onError={()=>setFailedUrl(url)}/>:<Icon size={32} aria-hidden="true"/>}</span>;
}
export function AssetsLibrary({gameId,assets=[],loading=false,error='',hasMore=false,onMore,onOpen,onUpload,onGenerate,onThumbnail,onGenerationStatus,initialJobs=emptyJobs,browseFilesHref,onBrowseFiles,onCapabilities,actionsHost,onDelete,characters=[],onCharacters,onTags}) {
  const [deletion,setDeletion]=useState(null),[deletePending,setDeletePending]=useState(false),[deleteError,setDeleteError]=useState('');
  const deleteAsset=async()=>{setDeletePending(true);setDeleteError('');try{await onDelete(deletion.asset,deletion.operationId);setCreated(items=>items.filter(item=>item.key!==deletion.asset.key));setDeletion(null);}catch(error){setDeleteError(error.message||'The asset could not be deleted.');}finally{setDeletePending(false);}};
  const capabilities=useQuery({queryKey:['generation-capabilities'],queryFn:onCapabilities,enabled:Boolean(onCapabilities),staleTime:10000,refetchInterval:15000,retry:false});
  const generationUnavailable=Boolean(onCapabilities)&&(capabilities.isPending||capabilities.isError||capabilities.data?.images!==true);
  const [selectedTags,setSelectedTags]=useState([]),[selectedCharacters,setSelectedCharacters]=useState([]);
  const tagsQuery=useQuery({queryKey:['asset-filter-tags',gameId],queryFn:onTags,enabled:Boolean(onTags),staleTime:30000,retry:false});
  const charactersQuery=useInfiniteQuery({queryKey:['asset-filter-characters',gameId],queryFn:({pageParam})=>onCharacters(pageParam),initialPageParam:undefined,getNextPageParam:page=>page.cursor||undefined,enabled:Boolean(onCharacters),staleTime:30000,retry:false});
  const [type,setType]=useState('all'),[search,setSearch]=useState(''),[form,setForm]=useState(null),[jobs,setJobs]=useState([]),[created,setCreated]=useState([]);
  useEffect(()=>{setJobs(previous=>[...initialJobs,...previous.filter(job=>!initialJobs.some(incoming=>incoming.jobId===job.jobId))]);},[initialJobs]);
  const published=useCallback(job=>{setCreated(previous=>previous.some(asset=>asset.key===job.assetKey)?previous:[...previous,job.asset||{key:job.assetKey,title:job.name,kind:job.type}]);},[]);
  const allAssets=useMemo(()=>[...assets,...created.filter(asset=>!assets.some(existing=>existing.key===asset.key))].filter(ordinaryLibraryAsset),[assets,created]);
  const filters=useMemo(()=>[...baseFilters,...[...new Set(allAssets.map(assetLibraryType))].filter(type=>!baseFilters.some(([known])=>known===type)).sort().map(type=>[type,assetTypeLabel(type)])],[allAssets]);
  const completed=(result,payload)=>{if(form.mode==='upload'){setCreated(previous=>[...previous,result.asset||result]);}else {setJobs(previous=>[{...result,name:result.name||payload.name,type:result.type||payload.type,openDetails:true},...previous.filter(job=>job.jobId!==result.jobId)]);}setForm(null);};
  useEffect(()=>{setType('all');setSearch('');setSelectedTags([]);setSelectedCharacters([]);setForm(null);setCreated([]);setJobs(initialJobs);},[gameId]);
  const tagOptions=useMemo(()=>[...new Set([...(tagsQuery.data?.tags||[]),...allAssets.flatMap(asset=>Array.isArray(asset.tags)?asset.tags:asset.metadata?.tags||[])])].sort().map(name=>({id:name,name})),[tagsQuery.data,allAssets]);
  const castOptions=charactersQuery.data?charactersQuery.data.pages.flatMap(page=>page.characters||[]):characters;
  const visible=useMemo(()=>allAssets.filter(asset=>{
    const tags=Array.isArray(asset.tags)?asset.tags:asset.metadata?.tags||[],cast=Array.isArray(asset.metadata?.characterIds)?asset.metadata.characterIds:[];
    return (type==='all'||assetLibraryType(asset)===type)&&selectedTags.every(tag=>tags.includes(tag))&&selectedCharacters.every(id=>cast.includes(id))&&(!search||[asset.title,asset.name,...tags].filter(Boolean).join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  }),[allAssets,type,search,selectedTags,selectedCharacters]);
  const actions=<div className="assets-actions">{browseFilesHref&&<a className="assets-browse-files" aria-label="Browse files" title="Browse files" href={browseFilesHref} onClick={onBrowseFiles}><FolderOpen size={16} aria-hidden="true"/><span>Browse files</span></a>}{onUpload&&<Button data-action-role="upload" className="ui-action-button" variant="outline" disabled={Boolean(form)} onClick={()=>setForm({mode:'upload',type})}><Upload size={16} aria-hidden="true"/>Upload</Button>}{onGenerate&&<Button data-action-role="generate" className="ui-action-button" disabled={Boolean(form)||generationUnavailable} title={generationUnavailable?'Image generation is unavailable':undefined} onClick={()=>setForm({mode:'generate',type})}><Sparkles size={16} aria-hidden="true"/>Generate</Button>}</div>;
  return <section className="assets-library" aria-label="Assets">
    {actionsHost&&createPortal(actions,actionsHost)}
    <div className="assets-toolbar"><label className="assets-search"><Search size={18} aria-hidden="true"/><span className="sr-only">Search assets</span><Input type="search" placeholder="Search assets" value={search} onChange={event=>setSearch(event.target.value)}/></label>{!actionsHost&&actions}</div>
    <div className="assets-metadata-filters"><MultiSelect label="Tags" options={tagOptions} value={selectedTags} onChange={setSelectedTags} placeholder="Add tag…"/><MultiSelect label="Characters" options={castOptions.map(character=>({id:character.id||character.characterId,name:character.name}))} value={selectedCharacters} onChange={setSelectedCharacters} placeholder="Add character…"/></div>
    {charactersQuery.hasNextPage&&<Button variant="ghost" className="assets-more-character-options" disabled={charactersQuery.isFetchingNextPage} onClick={()=>void charactersQuery.fetchNextPage()}>More character options</Button>}
    {(tagsQuery.error||charactersQuery.error)&&<p role="alert">Some filter options could not be loaded.</p>}
    {form&&<AssetCreateForm key={`${gameId}:${form.mode}`} gameId={gameId} mode={form.mode} characters={characters} onCharacters={onCharacters} uploadTypes={filters.filter(([value])=>value!=='all').map(([value])=>value)} initialType={form.type} initialName={form.name} initialPrompt={form.prompt} onUpload={onUpload} onGenerate={onGenerate} onComplete={completed} onClose={()=>setForm(null)}/>}
    {jobs.length>0&&<div className="assets-generation-jobs" aria-label="Generation progress">{jobs.map(job=><AssetGenerationStatus key={job.jobId} gameId={gameId} job={job} onGenerationStatus={onGenerationStatus} onOpen={onOpen} onPublished={published} onRetry={job=>setForm({mode:'generate',type:job.type,name:job.name,prompt:job.prompt})}/>)}</div>}
    <div className="assets-filters" role="group" aria-label="Asset type">{filters.map(([value,label])=><Button key={value} variant={type===value?'secondary':'ghost'} className="assets-filter" aria-pressed={type===value} onClick={()=>setType(value)}>{label}</Button>)}</div>
    {error&&<p role="alert" className="assets-error">{error}</p>}
    <div className="assets-grid" aria-busy={loading}>
      {loading&&!allAssets.length?Array.from({length:6},(_,i)=><div key={i} className="assets-card assets-card-placeholder" aria-hidden="true"><span className="assets-card-image ui-skeleton"/><span className="ui-skeleton assets-title-skeleton"/></div>):visible.map(asset=><article className="assets-card-shell" key={asset.key}><Button variant="secondary" className="assets-card" onClick={()=>onOpen?.(asset)}><AssetThumbnail asset={asset} gameId={gameId} onThumbnail={onThumbnail}/><span className="assets-card-body"><span className="assets-card-title">{asset.title||asset.name||asset.key.split('/').at(-1)}</span><span className="assets-card-type">{assetTypeLabel(assetLibraryType(asset))} · <span className="assets-card-format">{assetFileFormat(asset)}</span></span></span></Button>{onDelete&&<Button variant="ghost" className="assets-delete" aria-label={`Delete ${asset.title||asset.name||asset.key.split('/').at(-1)}`} title="Delete asset" onClick={()=>{setDeleteError('');setDeletion({asset,operationId:crypto.randomUUID().replaceAll('-','')});}}><Trash2 size={16} aria-hidden="true"/></Button>}</article>)}
    </div>
    {!loading&&!visible.length&&!error&&<p className="assets-empty">{search||selectedTags.length||selectedCharacters.length?'No matching assets.':type==='all'?'No assets yet.':`No ${filters.find(([value])=>value===type)[1].toLowerCase()} yet.`}</p>}
    {deletion&&<Dialog open onOpenChange={open=>{if(!open&&!deletePending)setDeletion(null);}}><DialogContent className="asset-delete-dialog"><DialogTitle>Delete asset?</DialogTitle><DialogDescription>Remove this asset from the library?</DialogDescription><p className="asset-delete-name">{deletion.asset.title||deletion.asset.name||deletion.asset.key.split('/').at(-1)}</p>{deleteError&&<p role="alert" className="asset-progress-error">{deleteError}</p>}<div className="assets-form-actions"><Button variant="secondary" disabled={deletePending} onClick={()=>setDeletion(null)}>Cancel</Button><Button disabled={deletePending} onClick={()=>void deleteAsset()}>{deletePending?'Deleting…':'Delete'}</Button></div></DialogContent></Dialog>}
    {hasMore&&(selectedTags.length>0||selectedCharacters.length>0||search||type!=='all')&&<p className="assets-filter-scope">Filtering loaded assets. Load more to include the remaining assets.</p>}
    {hasMore&&<Button variant="secondary" disabled={loading} className="assets-more" onClick={onMore}>{loading?'Loading…':'Load more'}</Button>}
  </section>;
}
