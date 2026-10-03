import React,{useEffect,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Button} from './components/ui/button.jsx';
import {generationTerminal} from './assets-library-data.js';
const labels={QUEUED:'Waiting for worker',RUNNING:'Generating',GENERATING:'Generating',PUBLISHED:'Ready',FAILED:'Failed',ATTENTION:'Needs attention',BLOCKED:'Not configured',DEFERRED:'Paused',PENDING:'Waiting for worker'};
export function AssetGenerationStatus({gameId,job,onGenerationStatus,onOpen,onPublished}) {
  const [foreground,setForeground]=useState(document.visibilityState!=='hidden');
  useEffect(()=>{const change=()=>setForeground(document.visibilityState!=='hidden');document.addEventListener('visibilitychange',change);return()=>document.removeEventListener('visibilitychange',change);},[]);
  const query=useQuery({queryKey:['asset-generation',gameId,job.jobId],queryFn:async()=>{let timer;try{return await Promise.race([onGenerationStatus(job),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Progress check timed out. The request is preserved; checking will continue when the service responds.')),15000);})]);}finally{clearTimeout(timer);}},initialData:job,staleTime:0,retry:false,enabled:query=>Boolean(onGenerationStatus)&&foreground&&!generationTerminal(query.state.data?.status||job.status),refetchInterval:query=>foreground&&!generationTerminal(query.state.data?.status)?5000:false,refetchIntervalInBackground:false});
  const current=query.data||job;
  useEffect(()=>{if(current.status==='PUBLISHED'&&current.assetKey)onPublished(current);},[current,onPublished]);
  const active=!generationTerminal(current.status);
  const queued=['QUEUED','PENDING'].includes(current.status);
  const elapsed=current.createdAt?Math.max(0,Math.floor((Date.now()-(typeof current.createdAt==='number'?current.createdAt*1000:Date.parse(current.createdAt)))/60000)):null;
  return <div className="assets-generation-job"><div><strong>{current.name||job.name||'Asset'}</strong><span role="status">{query.error?'Progress unavailable':labels[current.status]||'Processing'}</span>{active&&!query.error&&<progress className="editorial-stage-progress" aria-label={queued?'Waiting for image worker':'Generating image'}/>}</div>{current.status==='PUBLISHED'&&current.assetKey?<Button variant="secondary" onClick={()=>onOpen?.(current.asset||{key:current.assetKey,title:current.name||job.name,kind:current.type||job.type})}>Open asset</Button>:null}{queued&&!query.error&&<p className="assets-worker-help">{elapsed>0?`Waiting ${elapsed} min. `:''}Image generation needs a signed-in laptop running <code>panther assets worker --work-dir /private/path/asset-generation</code>. No completion estimate is available until a worker starts.</p>}{['FAILED','ATTENTION','DEFERRED','BLOCKED'].includes(current.status)&&<p role="alert">{current.error?.message||(typeof current.error==='string'?current.error:null)||current.message||'Generation needs attention.'}</p>}{query.error&&<p role="alert">{query.error.message||'Could not check progress.'}</p>}</div>;
}
