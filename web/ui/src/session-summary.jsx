import React,{useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {Download} from 'lucide-react';
import {Button} from './components/ui/button.jsx';
export function SessionSummary({scope,gameId,sourceKey,onLoad}){
 const [expanded,setExpanded]=useState(false);
 const query=useQuery({queryKey:['session-summary',scope,gameId,sourceKey],queryFn:({signal})=>onLoad({signal}),staleTime:60000,refetchInterval:query=>['QUEUED','GENERATING'].includes(query.state.data?.status)?5000:false});
 const text=query.data?.summary?.summary;
 if(query.isPending)return <div className="session-summary-loading" aria-label="Loading summary"/>;
 if(query.error)return <p className="session-summary-error">Summary unavailable.</p>;
 if(!text)return null;
 const shortened=text.length>220;
 return <p className="session-summary-text">{expanded||!shortened?text:`${text.slice(0,220).replace(/\s+\S*$/,'')}…`}{shortened&&<Button variant="link" size="sm" className="session-summary-more" onClick={()=>setExpanded(!expanded)} aria-expanded={expanded}>{expanded?'Less':'More'}</Button>}</p>;
}
export function SessionDownload({onDownload}){
 const [pending,setPending]=useState(false),[error,setError]=useState('');
 return <><Button variant="ghost" size="icon" aria-label="Download audio" title="Download audio" disabled={pending} onClick={async()=>{setPending(true);setError('');try{await onDownload();}catch{setError('Audio could not be downloaded. Try again.');}finally{setPending(false);}}}><Download size={18}/></Button>{error&&<p role="alert" className="session-download-error">{error}</p>}</>;
}
