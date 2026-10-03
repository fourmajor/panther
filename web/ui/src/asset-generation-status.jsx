import React,{useEffect,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Sparkles,AlertCircle,Check} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {Dialog,DialogContent,DialogTitle,DialogDescription} from './components/ui/dialog.jsx';
import {generationTerminal} from './assets-library-data.js';
const labels={QUEUED:'Queued',RUNNING:'Generating',GENERATING:'Generating',PUBLISHED:'Ready',FAILED:'Failed',UNKNOWN:'Could not confirm',ATTENTION:'Needs attention',BLOCKED:'Unavailable',DEFERRED:'Paused',PENDING:'Queued'};
const polling=current=>!generationTerminal(current?.status)||current?.recoverableWaiting;
export function AssetGenerationStatus({gameId,job,onGenerationStatus,onOpen,onPublished,onRetry}) {
  const [foreground,setForeground]=useState(document.visibilityState!=='hidden'),[details,setDetails]=useState(Boolean(job.openDetails));
  useEffect(()=>{const change=()=>setForeground(document.visibilityState!=='hidden');document.addEventListener('visibilitychange',change);return()=>document.removeEventListener('visibilitychange',change);},[]);
  const query=useQuery({queryKey:['asset-generation',gameId,job.jobId],queryFn:async()=>{let timer;try{return await Promise.race([onGenerationStatus(job),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Could not check generation progress. Checking will continue automatically.')),15000);})]);}finally{clearTimeout(timer);}},initialData:job,staleTime:0,retry:false,enabled:query=>Boolean(onGenerationStatus)&&foreground&&polling(query.state.data||job),refetchInterval:query=>foreground&&polling(query.state.data)?5000:false,refetchIntervalInBackground:false});
  const current=query.data||job;
  useEffect(()=>{if(current.status==='PUBLISHED'&&current.assetKey)onPublished(current);},[current,onPublished]);
  const active=polling(current),queued=['QUEUED','PENDING'].includes(current.status),ready=current.status==='PUBLISHED';
  const title=current.name||job.name||'Asset';
  const failed=!active&&!ready,Icon=ready?Check:failed?AlertCircle:Sparkles;
  const error=query.error?.message||current.error?.message||(typeof current.error==='string'?current.error:null)||current.message;
  const view=()=>{setDetails(false);onOpen?.(current.asset||{key:current.assetKey,title,kind:current.type||job.type});};
  if(ready&&!details)return null;
  return <><div className="assets-generation-job"><Icon size={20} aria-hidden="true" className={active?'generation-active':''}/><div><strong>{title}</strong><span role="status">{query.error?'Progress unavailable':labels[current.status]||'Processing'}</span></div><Button variant="secondary" onClick={()=>setDetails(true)}>View progress</Button></div><Dialog open={details} onOpenChange={setDetails}><DialogContent className="asset-progress-dialog"><DialogTitle>{title}</DialogTitle><DialogDescription className="sr-only">Image generation progress</DialogDescription><p className="asset-progress-state" role="status">{query.error?'Progress unavailable':labels[current.status]||'Processing'}</p>{active&&!query.error&&<><progress className="editorial-stage-progress" data-active="true" aria-label={queued?'Waiting for image worker':'Generating image'}/><p className="asset-progress-caption">{queued?'Waiting to start':'Creating your image'}</p></>}{error&&<p role="alert" className="asset-progress-error">{error}</p>}{current.prompt&&<div className="asset-progress-prompt"><h3>Prompt</h3><p>{current.prompt}</p></div>}{failed&&!current.outcomeUnknown&&[400,401,403,422,429].includes(current.errorCode)&&onRetry&&<div className="assets-form-actions"><Button onClick={()=>{setDetails(false);onRetry(current);}}>Try again</Button></div>}{ready&&current.assetKey&&<div className="assets-form-actions"><Button onClick={view}>Open asset</Button></div>}</DialogContent></Dialog></>;
}
