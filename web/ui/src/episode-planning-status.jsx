import React, {useEffect, useRef} from 'react';
import {useMutation, useQuery} from '@tanstack/react-query';
import {Button} from './components/ui/button.jsx';

const terminal = new Set(['FAILED','BLOCKED','ATTENTION','DEFERRED','NOVEL_READY','READY_FOR_VIDEO_DISCUSSION']);
export function EpisodePlanningStatus({scope,gameId,jobId,onLoad,onReady}) {
  const notified = useRef(false);
  const result = useQuery({queryKey:['episode-planning',scope,gameId,jobId],queryFn:onLoad,staleTime:1000,
    refetchInterval:query=>terminal.has(query.state.data?.job?.status)?false:3000,retry:1});
  const publication = useMutation({mutationFn:onReady});
  const job = result.data?.job;
  const ready = job?.status==='READY_FOR_VIDEO_DISCUSSION'||Boolean(job?.artifacts?.['video-generation-packets'])||result.data?.tasks?.some(task=>task.stage==='video-generation-packets'&&task.status==='DONE');
  useEffect(()=>{if(ready&&!notified.current){notified.current=true;publication.mutate();}},[ready]);
  const failed = job&&terminal.has(job.status)&&!ready;
  return <section aria-label="Episode preparation" className="flex flex-col gap-4 rounded-lg border bg-card p-6">
    <p role="status" className="font-medium">{result.isError?'Episode preparation status is unavailable.':failed?'Episode preparation stopped.':ready?'Opening episode plan…':'Preparing episode…'}</p>
    {!failed&&!result.isError&&!publication.isError&&<div className="grid gap-3" aria-hidden="true"><div className="h-4 w-2/3 animate-pulse rounded bg-muted"/><div className="h-4 w-full animate-pulse rounded bg-muted"/><div className="h-4 w-5/6 animate-pulse rounded bg-muted"/></div>}
    {failed&&<><p className="text-sm text-muted-foreground">Your chapter and completed planning steps are saved. Review the failure before submitting another request.</p><a className="text-sm underline underline-offset-4" href={`/games/${encodeURIComponent(gameId)}/workflows/editorial/editorial~${encodeURIComponent(jobId)}`}>Open workflow</a></>}
    {publication.isError&&<><p role="alert" className="text-sm text-destructive">{publication.error.message||'The episode plan could not be opened.'}</p><Button variant="outline" className="self-start" onClick={()=>publication.mutate()}>Open episode plan</Button></>}
    {result.isError&&<Button variant="outline" className="self-start" onClick={()=>void result.refetch()}>Check preparation status</Button>}
  </section>;
}
