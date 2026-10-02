import React,{useId,useRef,useState} from 'react';
import {useMutation,useQueryClient} from '@tanstack/react-query';
import {Button} from './components/ui/button.jsx';
import {Input} from './components/ui/input.jsx';
import {Textarea} from './components/ui/textarea.jsx';
import {GameSelect} from './components/ui/select.jsx';
import {definitiveValidationError,newAssetOperationId} from './assets-library-data.js';

export function AssetCreateForm({gameId,mode,initialType,onUpload,onGenerate,onComplete,onClose}) {
  const upload=mode==='upload';
  const fieldId=useId();
  const client=useQueryClient();
  const cacheKey=['asset-submission',gameId,mode];
  const retained=client.getQueryData(cacheKey);
  const [type,setType]=useState(retained?.type||(['map','blueprint','location'].includes(initialType)?initialType:upload?'unknown':'map'));
  const [name,setName]=useState(retained?.name||''),[prompt,setPrompt]=useState(retained?.prompt||''),[file,setFile]=useState(retained?.file||null);
  const submission=useRef(retained||null);
  const mutation=useMutation({retry:false,mutationFn:payload=>upload?onUpload(payload):onGenerate(payload),onSuccess:result=>{client.removeQueries({queryKey:cacheKey,exact:true});onComplete(result,submission.current);},onError:error=>{if(definitiveValidationError(error)){submission.current=null;client.removeQueries({queryKey:cacheKey,exact:true});}}});
  const frozen=mutation.isPending||Boolean(submission.current);
  const submit=event=>{
    event.preventDefault();
    if(!submission.current)submission.current={type,name:name.trim()||(upload?file?.name:''),...(upload?{file}:{prompt:prompt.trim()}),operationId:newAssetOperationId()};
    client.setQueryData(cacheKey,submission.current);
    mutation.mutate(submission.current);
  };
  return <form className="assets-create-form" onSubmit={submit} aria-label={upload?'Upload asset':'Generate asset'}>
    <div className="assets-form-heading"><h2>{upload?'Upload asset':'Generate asset'}</h2><Button variant="ghost" disabled={mutation.isPending||Boolean(submission.current)} onClick={onClose}>Cancel</Button></div>
    <div className="assets-form-fields"><label><span>Type</span><GameSelect id={null} label="Asset type" games={[{id:'map',name:'Map'},{id:'blueprint',name:'Blueprint'},{id:'location',name:'Location'},...(upload?[{id:'unknown',name:'Other'}]:[])]} value={type} disabled={frozen} onChange={setType}/></label><div className="assets-form-field"><label htmlFor={`${fieldId}-name`}>Name{upload?' (optional)':''}</label><Input id={`${fieldId}-name`} value={name} required={!upload} maxLength={160} disabled={frozen} onChange={event=>setName(event.target.value)}/></div></div>
    {upload?<div className="assets-form-field"><label htmlFor={`${fieldId}-file`}>File</label><Input id={`${fieldId}-file`} type="file" required disabled={frozen} onChange={event=>setFile(event.target.files?.[0]||null)}/></div>:<div className="assets-form-field"><label htmlFor={`${fieldId}-prompt`}>Prompt</label><Textarea id={`${fieldId}-prompt`} value={prompt} required rows={4} disabled={frozen} onChange={event=>setPrompt(event.target.value)}/></div>}
    {!mutation.error&&!mutation.isPending&&retained&&<p role="status">Submission not confirmed. Retry the same request.</p>}
    {mutation.error&&<p role="alert">{mutation.error.message||'Could not submit. Try again.'}</p>}
    <Button type="submit" className="assets-form-submit" disabled={mutation.isPending||(!submission.current&&(upload?!file:!name.trim()||!prompt.trim()))}>{mutation.isPending?(upload?'Uploading…':'Submitting…'):mutation.isError||Boolean(retained)?'Retry':upload?'Upload asset':'Generate asset'}</Button>
  </form>;
}
