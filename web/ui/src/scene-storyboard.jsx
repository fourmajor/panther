import React, {useId, useState, useEffect} from 'react';
import {createPortal} from 'react-dom';
import {Pencil, Plus, ThumbsUp, ThumbsDown, Sparkles, ChevronDown, Hammer} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {Input} from './components/ui/input.jsx';
import {Textarea} from './components/ui/textarea.jsx';
import {Field, FieldGroup, FieldLabel} from './components/ui/field.jsx';
import {Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter} from './components/ui/dialog.jsx';
import {useQuery,useInfiniteQuery,useQueryClient} from '@tanstack/react-query';
import {Select,SelectTrigger,SelectValue,SelectContent,SelectItem} from './components/ui/select.jsx';
import {DropdownMenu,DropdownMenuTrigger,DropdownMenuContent,DropdownMenuItem} from './components/ui/dropdown-menu.jsx';

export function SceneStoryboard({scene, scope, onSave, onLoadFrames, onOpenFrame, actionHost, onLoadTakes, onLoadVideo, onGenerateShot, onLoadJobs, onAssemble}) {
  const board=scene.storyboard;
  const keys=(board?.shots||[]).map(shot=>shot.frameKey).filter(Boolean);
  const frames=useQuery({queryKey:['storyboard-frames',scope,scene.gameId,keys],queryFn:()=>onLoadFrames(keys),enabled:keys.length>0,staleTime:240000,retry:1});
  const [editing,setEditing]=useState(false),[draft,setDraft]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const prefix=useId();
  const cache=useQueryClient();
  const jobs=useQuery({queryKey:['storyboard-jobs',scope,scene.gameId,scene.episodeId,scene.id],queryFn:onLoadJobs,enabled:Boolean(onLoadJobs),staleTime:10000,refetchInterval:query=>query.state.data?.jobs?.some(job=>['QUEUED','COMPOSING','RUNNING','SUBMITTED','IN_QUEUE','IN_PROGRESS'].includes(job.status))?3000:false});
  const completed=(jobs.data?.jobs||[]).filter(job=>job.status==='DONE').map(job=>job.jobId).join(',');
  useEffect(()=>{if(completed)void cache.invalidateQueries({queryKey:['storyboard-takes',scope,scene.gameId,scene.episodeId,scene.id]});},[completed,cache,scope,scene.gameId,scene.episodeId,scene.id]);
  const takes=useInfiniteQuery({queryKey:['storyboard-takes',scope,scene.gameId,scene.episodeId,scene.id],initialPageParam:null,queryFn:({pageParam})=>onLoadTakes(pageParam),getNextPageParam:page=>page.cursor||undefined,enabled:Boolean(onLoadTakes),staleTime:10000});
  const assets=(takes.data?.pages||[]).flatMap(page=>page.assets||[]).filter(asset=>asset.metadata?.extra?.sceneRef?.episodeId===scene.episodeId&&asset.metadata?.extra?.sceneRef?.sceneId===scene.id&&!asset.metadata?.extra?.sceneAssembly);
  const selectedKeys=Object.values(scene.shotTakes||{}).map(take=>take.assetKey);
  const videos=useQuery({queryKey:['storyboard-videos',scope,selectedKeys],queryFn:async()=>Object.fromEntries(await Promise.all(selectedKeys.map(async key=>[key,await onLoadVideo(key)]))),enabled:Boolean(onLoadVideo)&&selectedKeys.length>0,staleTime:240000});
  const needsReview=board?.origin==='ai'&&(!board.decision||board.decision.revision!==board.revision||board.decision.action!=='approved');
  const edit=()=>{setError('');setDraft(structuredClone(board?.shots||[{shotId:'shot-'+crypto.randomUUID().slice(0,8),description:'',camera:'',durationSeconds:8,frameKey:null,narration:''}]));setEditing(true);};
  const save=async body=>{setBusy(true);setError('');try{await onSave(body);setEditing(false);}catch(cause){setError(cause.message||'The storyboard could not be saved.');}finally{setBusy(false);}};
  const field=(index,key,value)=>setDraft(items=>items.map((shot,i)=>i===index?{...shot,[key]:value}:shot));
  const generate=async shot=>{setBusy(true);setError('');try{await onGenerateShot(shot);await cache.invalidateQueries({queryKey:['storyboard-jobs',scope,scene.gameId,scene.episodeId,scene.id]});}catch(cause){setError(cause.message);}finally{setBusy(false);}};
  const assemble=async()=>{setBusy(true);setError('');try{await onAssemble();}catch(cause){setError(cause.message);}finally{setBusy(false);}};
  return <section aria-label="Scene storyboard" className="flex flex-col gap-4 border-t pt-4">
    {board&&actionHost&&onGenerateShot&&createPortal(<DropdownMenu><DropdownMenuTrigger asChild><Button disabled={busy||needsReview||!board}><Sparkles/>Generate<ChevronDown/></Button></DropdownMenuTrigger><DropdownMenuContent align="end">{board?.shots.map((shot,index)=><DropdownMenuItem key={shot.shotId} disabled={shot.durationSeconds>8} onSelect={()=>void generate(shot)}>Shot {index+1} · {shot.durationSeconds}s{shot.durationSeconds>8?' — split into shorter shots':''}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>,actionHost)}
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h4 className="text-base font-semibold">Storyboard</h4>
      <div role="group" aria-label="Storyboard actions" className="flex flex-wrap items-center gap-2">
        {needsReview&&<span className="text-sm text-muted-foreground">{board.decision?.action==='changes-requested'?'Changes requested':'Needs approval'}</span>}
        <Button variant="outline" size="sm" onClick={edit} disabled={busy}><Pencil/> {board?'Edit':'Create storyboard'}</Button>
        {onAssemble&&board&&<Button size="sm" disabled={busy||needsReview||board.shots.some(shot=>!scene.shotTakes?.[shot.shotId])} onClick={()=>void assemble()}><Hammer/>Assemble</Button>}
        {needsReview&&<><Button variant="outline" size="sm" disabled={busy} onClick={()=>save({storyboardDecision:{revision:board.revision,action:'changes-requested'}})}><ThumbsDown/>Request changes</Button><Button size="sm" disabled={busy} onClick={()=>save({storyboardDecision:{revision:board.revision,action:'approved'}})}><ThumbsUp/>Approve</Button></>}
      </div>
    </div>
    {board&&<ol className="grid items-start gap-4 sm:grid-cols-2">{board.shots.map((shot,index)=>{const take=scene.shotTakes?.[shot.shotId];const job=(jobs.data?.jobs||[]).find(job=>job.storyboardShotRef?.revision===board.revision&&job.storyboardShotRef?.shotId===shot.shotId);const generating=job&&['QUEUED','COMPOSING','RUNNING','SUBMITTED','IN_QUEUE','IN_PROGRESS'].includes(job.status);const candidates=assets.filter(asset=>{const pin=asset.metadata.extra.storyboardShotRef;return pin?pin.revision===board.revision&&pin.shotId===shot.shotId:board.shots.length===1;});return <li key={shot.shotId} className="flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-4">
      {shot.frameKey&&<button type="button" className="aspect-video w-full overflow-hidden rounded-md border transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-ring" aria-label={`Open storyboard frame for shot ${index+1}`} onClick={()=>onOpenFrame(shot.frameKey)}>{frames.data?.images?.[shot.frameKey]?.url?<img className="h-full w-full object-contain" src={frames.data.images[shot.frameKey].url} alt={shot.description}/>:<span className="text-sm text-muted-foreground">{frames.isPending?'Loading frame…':'Open frame'}</span>}</button>}
      <p className="text-sm font-medium">Shot {index+1} · {shot.durationSeconds}s</p>
      <p>{shot.description}</p>
      {shot.camera&&<p className="text-sm text-muted-foreground">{shot.camera}</p>}
      {shot.narration&&<p className="text-sm">{shot.narration}</p>}
      {take&&<video className="aspect-video w-full rounded-md" controls playsInline preload="metadata" aria-label={`Shot ${index+1} video`} src={videos.data?.[take.assetKey]?.url} onLoadedMetadata={event=>{event.currentTarget.currentTime=take.startSeconds;}} onPlay={event=>{const video=event.currentTarget;if(video.currentTime<take.startSeconds||video.currentTime>=take.startSeconds+take.durationSeconds)video.currentTime=take.startSeconds;}} onTimeUpdate={event=>{const video=event.currentTarget;if(video.currentTime>=take.startSeconds+take.durationSeconds){video.pause();video.currentTime=take.startSeconds;}}}/>}
      {onLoadTakes&&<Select value={take?.assetKey||'none'} disabled={busy} onValueChange={key=>void save({shotSelection:{storyboardRevision:board.revision,shotId:shot.shotId,assetKey:key==='none'?null:key,startSeconds:0}})}><SelectTrigger aria-label={`Take for shot ${index+1}`}><SelectValue placeholder="Choose a take"/></SelectTrigger><SelectContent><SelectItem value="none">No selected take</SelectItem>{candidates.map((asset,i)=>{const duration=Number(asset.metadata.extra.mediaProbe?.format?.duration)||0;return <SelectItem key={asset.key} value={asset.key} disabled={duration<shot.durationSeconds}>Take {i+1} · {duration.toFixed(1)}s{duration<shot.durationSeconds?' — too short':''}</SelectItem>;})}</SelectContent></Select>}
      {take&&<Field><FieldLabel htmlFor={`${prefix}-${index}-trim`}>Trim start (seconds)</FieldLabel><Input id={`${prefix}-${index}-trim`} type="number" min={0} step="0.1" defaultValue={take.startSeconds} disabled={busy} onBlur={event=>{const start=Number(event.currentTarget.value);if(start!==take.startSeconds)void save({shotSelection:{storyboardRevision:board.revision,shotId:shot.shotId,assetKey:take.assetKey,startSeconds:start}});}}/></Field>}
      {job&&job.status!=='DONE'&&<p role="status" className="text-sm text-muted-foreground">{generating?'Generating…':job.message||'This take could not be completed.'}</p>}
      {onGenerateShot&&<Button variant="outline" size="sm" className="self-end" disabled={busy||generating||needsReview||shot.durationSeconds>8} onClick={()=>void generate(shot)}><Sparkles/>Generate shot {index+1}</Button>}
      {onGenerateShot&&shot.durationSeconds>8&&<p className="text-sm text-muted-foreground">Split this item into shots of eight seconds or less before generating.</p>}
    </li>;})}</ol>}
    {takes.hasNextPage&&<Button variant="outline" disabled={takes.isFetchingNextPage} onClick={()=>void takes.fetchNextPage()}>More takes</Button>}
    {takes.isError&&<p role="alert" className="text-sm text-destructive">Takes could not be loaded.</p>}
    {!editing&&error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    <Dialog open={editing} onOpenChange={value=>{if(!busy)setEditing(value);}}><DialogContent className="max-w-3xl"><DialogHeader><DialogTitle>{board?'Edit storyboard':'Create storyboard'}</DialogTitle></DialogHeader>
      <form className="flex min-h-0 flex-col gap-6" onSubmit={event=>{event.preventDefault();void save({storyboardShots:draft});}}>
        <FieldGroup data-slot="dialog-body">
          {draft.map((shot,index)=><fieldset key={shot.shotId} className="flex flex-col gap-4 rounded-lg border p-4"><legend className="px-1 text-sm font-medium">Shot {index+1}</legend>
            <Field><FieldLabel htmlFor={`${prefix}-${index}-description`}>Action and composition</FieldLabel><Textarea id={`${prefix}-${index}-description`} required maxLength={5000} value={shot.description} disabled={busy} onChange={e=>field(index,'description',e.target.value)}/></Field>
            <div className="grid gap-4 sm:grid-cols-2"><Field><FieldLabel htmlFor={`${prefix}-${index}-camera`}>Camera</FieldLabel><Input id={`${prefix}-${index}-camera`} maxLength={5000} value={shot.camera} disabled={busy} onChange={e=>field(index,'camera',e.target.value)}/></Field><Field><FieldLabel htmlFor={`${prefix}-${index}-duration`}>Duration (seconds)</FieldLabel><Input id={`${prefix}-${index}-duration`} type="number" min={1} max={120} step="0.1" required value={shot.durationSeconds} disabled={busy} onChange={e=>field(index,'durationSeconds',Number(e.target.value))}/></Field></div>
            <Field><FieldLabel htmlFor={`${prefix}-${index}-narration`}>Narration</FieldLabel><Textarea id={`${prefix}-${index}-narration`} maxLength={5000} value={shot.narration} disabled={busy} onChange={e=>field(index,'narration',e.target.value)}/></Field>
            {draft.length>1&&<Button type="button" variant="ghost" size="sm" className="self-end" disabled={busy} onClick={()=>setDraft(items=>items.filter((_,i)=>i!==index))}>Remove shot</Button>}
          </fieldset>)}
          <Button type="button" variant="outline" className="self-start" disabled={busy||draft.length>=24} onClick={()=>setDraft(items=>[...items,{shotId:'shot-'+crypto.randomUUID().slice(0,8),description:'',camera:'',durationSeconds:8,frameKey:null,narration:''}])}><Plus/>Add shot</Button>
          {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
        </FieldGroup>
        <DialogFooter><Button type="button" variant="outline" disabled={busy} onClick={()=>setEditing(false)}>Cancel</Button><Button type="submit" disabled={busy}>{busy?'Saving…':'Save storyboard'}</Button></DialogFooter>
      </form>
    </DialogContent></Dialog>
  </section>;
}
