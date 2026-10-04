import React from 'react';
import {useInfiniteQuery, useQuery} from '@tanstack/react-query';
import {ArrowLeft, ChevronRight, Check, CircleAlert, Workflow, File, Volume2, Film, ZoomIn} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
import {Badge} from './components/ui/badge.jsx';

const labels={done:'Complete',failed:'Failed',running:'Running',queued:'Queued',paused:'Paused',pending:'Pending',unknown:'Unknown'};
function date(value){if(!value)return '—';return new Date(typeof value==='number'?value*1000:value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});}
function Link({href,onNavigate,children,...props}){return <a href={href} {...props} onClick={event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();onNavigate(href);}}>{children}</a>;}
function outputKey(job){return job.outputKey||job.stages?.find(stage=>stage.outputKey)?.outputKey;}
function Output({assetKey,scope,gameId,onLoadOutput,onPreview,compact=false,label='Output'}){
 const query=useQuery({queryKey:['workflow-output',scope,gameId,assetKey],enabled:!!assetKey&&!!onLoadOutput,queryFn:({signal})=>onLoadOutput(assetKey,{signal}),staleTime:60000,retry:false});
 const result=query.data,Icon=result?.kind==='audio'?Volume2:result?.kind==='video'?Film:File;
 const media=result?.kind==='image'||result?.thumbnail?result.url:null;
 const content=<>{media?<img src={media} alt={compact?'':label} loading="lazy"/>:result?.kind==='video'&&result.url?<video src={result.url} preload="metadata" muted aria-hidden="true"/>:<Icon size={compact?22:36}/>}</>;
 if(compact)return <span className="workflow-run-thumbnail" aria-hidden="true">{content}</span>;
 return <Button variant="outline" className="workflow-output" aria-label={`Preview ${label}`} onClick={()=>onPreview(assetKey)}><span className="workflow-output-media">{content}<ZoomIn size={18} className="workflow-output-zoom"/></span><span className="workflow-output-label">{label}</span></Button>;
}
function Loading(){return <div className="workflow-loading" aria-label="Loading workflows"><div/><div/><div/></div>;}
function ErrorNotice({error}){return <p role="alert" className="workflow-error"><CircleAlert size={16}/>{error?.message||'Workflows could not be loaded.'}</p>;}
export function WorkflowBrowser({gameId,scope,type,workflowId,onLoadTypes,onLoadRuns,onLoadWorkflow,onNavigate,onPreview,onLoadOutput}){
 const base=`/games/${encodeURIComponent(gameId)}/workflows`;
 const types=useQuery({queryKey:['workflow-types',scope,gameId],queryFn:({signal})=>onLoadTypes({signal}),refetchInterval:15000});
 const runs=useInfiniteQuery({queryKey:['workflow-runs',scope,gameId,type],enabled:!!type&&!workflowId,initialPageParam:null,queryFn:({pageParam,signal})=>onLoadRuns(type,pageParam,{signal}),getNextPageParam:page=>page.cursor||undefined,refetchInterval:15000});
 const detail=useQuery({queryKey:['workflow-detail',scope,gameId,type,workflowId],enabled:!!workflowId,queryFn:({signal})=>onLoadWorkflow(type,workflowId,{signal}),refetchInterval:query=>['done','failed','paused'].includes(query.state.data?.workflow?.status)?false:5000});
 const name=types.data?.types?.find(item=>item.id===type)?.name||type?.replaceAll('-',' ');
 if(workflowId){
  if(detail.isPending)return <Loading/>;if(detail.error)return <ErrorNotice error={detail.error}/>;
  const job=detail.data.workflow;
  if(job.kind!==type)return <ErrorNotice error={{message:'This run belongs to another workflow type.'}}/>;
  const outputs=[...new Map(job.stages.filter(stage=>stage.outputKey).map(stage=>[stage.outputKey,stage])).values()];
  const active=job.stages.length===1&&['running','queued','pending'].includes(job.status);
  return <section className="workflow-detail"><Link href={`${base}/${type}`} onNavigate={onNavigate} className="workflow-back"><ArrowLeft size={16}/>{name}</Link><header><h2>{job.title}</h2><Badge variant="outline">{labels[job.status]||'Unknown'}</Badge></header><p className="workflow-date">{date(job.createdAt)}</p>{(job.stages.length>1||active)&&<><div className="workflow-stage-meter" aria-label={`${job.completedStages} of ${job.totalStages} stages complete`}>{job.stages.map(stage=><span key={stage.id} data-status={stage.status} title={`${stage.label}: ${labels[stage.status]||'Unknown'}`}/>)}</div><ul className="workflow-stages">{(active?[]:job.stages).map(stage=><li key={stage.id}><span>{stage.label}</span><span className="workflow-stage-status">{labels[stage.status]||'Unknown'}</span></li>)}</ul>{active&&<p className="workflow-current-stage">{job.stages[0].label}</p>}</>}{outputs.length>0&&<div className="workflow-outputs">{outputs.map(stage=><Output key={stage.id} assetKey={stage.outputKey} scope={scope} gameId={gameId} onLoadOutput={onLoadOutput} onPreview={onPreview} label={outputs.length===1?'Output':stage.label}/>)}</div>}</section>;
 }
 if(type){
  return <section><Link href={base} onNavigate={onNavigate} className="workflow-back"><ArrowLeft size={16}/>Workflows</Link><h2>{name}</h2>{runs.isPending?<Loading/>:runs.error?<ErrorNotice error={runs.error}/>:<><div className="workflow-runs">{runs.data.pages.flatMap(page=>page.workflows).map(job=><Link key={job.id} href={`${base}/${type}/${encodeURIComponent(job.id)}`} onNavigate={onNavigate} className="workflow-run"><Output compact assetKey={outputKey(job)} scope={scope} gameId={gameId} onLoadOutput={onLoadOutput}/><span className="workflow-run-description"><strong>{job.title}</strong><small>{date(job.createdAt)}</small></span><Badge variant="outline">{labels[job.status]||'Unknown'}</Badge><ChevronRight size={18} className="workflow-drilldown"/></Link>)}</div>{!runs.data.pages.some(page=>page.workflows.length)&&<p className="workflow-empty">No runs yet.</p>}{runs.hasNextPage&&<Button variant="outline" onClick={()=>runs.fetchNextPage()} disabled={runs.isFetchingNextPage}>Load more</Button>}</>}</section>;
 }
 return <section aria-label="Workflow types"><header className="page-heading"><h1>Workflows</h1></header>{types.isPending?<Loading/>:types.error?<ErrorNotice error={types.error}/>:types.data.types.length?<div className="workflow-types">{types.data.types.map(item=><Link key={item.id} href={`${base}/${item.id}`} onNavigate={onNavigate} className="workflow-type"><Workflow size={20} className="workflow-type-icon"/><div className="workflow-type-info"><h2>{item.name}</h2><div className="workflow-type-counts"><span>{item.total} {item.total===1?'run':'runs'}</span><span><Check size={14}/>{item.successful} Successful</span><span><CircleAlert size={14}/>{item.failed} Failed</span></div></div><time className="workflow-latest" dateTime={typeof item.latestRunAt==='number'?new Date(item.latestRunAt*1000).toISOString():item.latestRunAt||undefined}>{date(item.latestRunAt)}</time><ChevronRight size={18} className="workflow-drilldown"/></Link>)}</div>:<p className="workflow-empty">No workflows yet.</p>}</section>;
}
