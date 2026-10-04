import React, {useId, useState} from 'react';
import {Pencil, Plus, ThumbsUp, ThumbsDown} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {Input} from './components/ui/input.jsx';
import {Textarea} from './components/ui/textarea.jsx';
import {Field, FieldGroup, FieldLabel} from './components/ui/field.jsx';
import {Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter} from './components/ui/dialog.jsx';
import {useQuery} from '@tanstack/react-query';

export function SceneStoryboard({scene, scope, onSave, onLoadFrames, onOpenFrame}) {
  const board=scene.storyboard;
  const keys=(board?.shots||[]).map(shot=>shot.frameKey).filter(Boolean);
  const frames=useQuery({queryKey:['storyboard-frames',scope,scene.gameId,keys],queryFn:()=>onLoadFrames(keys),enabled:keys.length>0,staleTime:240000,retry:1});
  const [editing,setEditing]=useState(false),[draft,setDraft]=useState([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const prefix=useId();
  const needsReview=board?.origin==='ai'&&(!board.decision||board.decision.revision!==board.revision||board.decision.action!=='approved');
  const edit=()=>{setError('');setDraft(structuredClone(board?.shots||[{shotId:'shot-'+crypto.randomUUID().slice(0,8),description:'',camera:'',durationSeconds:8,frameKey:null,narration:''}]));setEditing(true);};
  const save=async body=>{setBusy(true);setError('');try{await onSave(body);setEditing(false);}catch(cause){setError(cause.message||'The storyboard could not be saved.');}finally{setBusy(false);}};
  const field=(index,key,value)=>setDraft(items=>items.map((shot,i)=>i===index?{...shot,[key]:value}:shot));
  return <section aria-label="Scene storyboard" className="flex flex-col gap-4 border-t pt-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h4 className="text-base font-semibold">Storyboard</h4>
      <div className="flex flex-wrap items-center gap-2">
        {needsReview&&<span className="text-sm text-muted-foreground">{board.decision?.action==='changes-requested'?'Changes requested':'Needs approval'}</span>}
        <Button variant="outline" size="sm" onClick={edit} disabled={busy}><Pencil/> {board?'Edit storyboard':'Create storyboard'}</Button>
        {needsReview&&<><Button variant="outline" size="sm" disabled={busy} onClick={()=>save({storyboardDecision:{revision:board.revision,action:'changes-requested'}})}><ThumbsDown/>Request changes</Button><Button size="sm" disabled={busy} onClick={()=>save({storyboardDecision:{revision:board.revision,action:'approved'}})}><ThumbsUp/>Approve</Button></>}
      </div>
    </div>
    {board&&<ol className="grid gap-4 sm:grid-cols-2">{board.shots.map((shot,index)=><li key={shot.shotId} className="flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-4">
      {shot.frameKey&&<button type="button" className="aspect-video w-full overflow-hidden rounded-md border transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-ring" aria-label={`Open storyboard frame for shot ${index+1}`} onClick={()=>onOpenFrame(shot.frameKey)}>{frames.data?.images?.[shot.frameKey]?.url?<img className="h-full w-full object-contain" src={frames.data.images[shot.frameKey].url} alt={shot.description}/>:<span className="text-sm text-muted-foreground">{frames.isPending?'Loading frame…':'Open frame'}</span>}</button>}
      <p className="text-sm font-medium">Shot {index+1} · {shot.durationSeconds}s</p>
      <p>{shot.description}</p>
      {shot.camera&&<p className="text-sm text-muted-foreground">{shot.camera}</p>}
      {shot.narration&&<p className="text-sm">{shot.narration}</p>}
    </li>)}</ol>}
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
