import React,{useEffect,useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Button} from './components/ui/button.jsx';
import {generationTerminal} from './assets-library-data.js';
const labels={QUEUED:'Queued',RUNNING:'Generating',GENERATING:'Generating',PUBLISHED:'Ready',FAILED:'Failed',ATTENTION:'Needs attention',DEFERRED:'Paused',PENDING:'Queued'};
export function AssetGenerationStatus({gameId,job,onGenerationStatus,onOpen,onPublished}) {
  const [foreground,setForeground]=useState(document.visibilityState!=='hidden');
  useEffect(()=>{const change=()=>setForeground(document.visibilityState!=='hidden');document.addEventListener('visibilitychange',change);return()=>document.removeEventListener('visibilitychange',change);},[]);
  const query=useQuery({queryKey:['asset-generation',gameId,job.jobId],queryFn:()=>onGenerationStatus(job),initialData:job,staleTime:0,retry:false,enabled:query=>Boolean(onGenerationStatus)&&foreground&&!generationTerminal(query.state.data?.status||job.status),refetchInterval:query=>foreground&&!generationTerminal(query.state.data?.status)?5000:false,refetchIntervalInBackground:false});
  const current=query.data||job;
  useEffect(()=>{if(current.status==='PUBLISHED'&&current.assetKey)onPublished(current);},[current,onPublished]);
  return <div className="assets-generation-job"><div><strong>{current.name||job.name||'Asset'}</strong><span role="status">{labels[current.status]||'Processing'}</span></div>{current.status==='PUBLISHED'&&current.assetKey?<Button variant="secondary" onClick={()=>onOpen?.(current.asset||{key:current.assetKey,title:current.name||job.name,kind:current.type||job.type})}>Open asset</Button>:null}{['FAILED','ATTENTION','DEFERRED'].includes(current.status)&&<p role="alert">{current.error?.message||(typeof current.error==='string'?current.error:null)||current.message||'Generation needs attention.'}</p>}{query.error&&<p role="alert">{query.error.message||'Could not check progress.'}</p>}</div>;
}
