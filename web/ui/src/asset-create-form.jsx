import {Upload,Sparkles} from 'lucide-react';
import React,{useId,useRef,useState} from 'react';
import {useMutation,useQueryClient,useQuery} from '@tanstack/react-query';
import {Button} from './components/ui/button.jsx';
import {Input} from './components/ui/input.jsx';
import {Textarea} from './components/ui/textarea.jsx';
import {Dialog,DialogContent,DialogTitle,DialogDescription} from './components/ui/dialog.jsx';
import {GameSelect} from './components/ui/select.jsx';
import {definitiveValidationError,newAssetOperationId,assetUploadTypes,assetTypeLabel} from './assets-library-data.js';

export function AssetCreateForm({gameId,mode,initialType,initialName,initialPrompt,onUpload,onGenerate,onComplete,onClose,characters=[],onCharacters,uploadTypes=assetUploadTypes}) {
  const upload=mode==='upload';
  const fieldId=useId();
  const client=useQueryClient();
  const cacheKey=['asset-submission',gameId,mode];
  const retained=client.getQueryData(cacheKey);
  const [type,setType]=useState(retained?.type||((upload?uploadTypes:['map','blueprint','location','portrait']).includes(initialType)?initialType:upload?'other':'map'));
  const [name,setName]=useState(retained?.name||initialName||''),[prompt,setPrompt]=useState(retained?.prompt||initialPrompt||''),[file,setFile]=useState(retained?.file||null);
  const [characterId,setCharacterId]=useState(retained?.characterId||'');
  const submission=useRef(retained||null);
  const mutation=useMutation({retry:false,mutationFn:payload=>upload?onUpload(payload):onGenerate(payload),onSuccess:result=>{client.removeQueries({queryKey:cacheKey,exact:true});onComplete(result,submission.current);},onError:error=>{if(definitiveValidationError(error)){submission.current=null;client.removeQueries({queryKey:cacheKey,exact:true});}}});
  const characterQuery=useQuery({queryKey:['asset-portrait-characters',gameId],queryFn:()=>onCharacters(),enabled:!upload&&type==='portrait'&&Boolean(onCharacters),retry:false,staleTime:30000});
  const choices=characterQuery.data?.characters||characters;
  const frozen=mutation.isPending||Boolean(submission.current);
  const submit=event=>{
    event.preventDefault();
    if(!submission.current)submission.current={type,name:name.trim()||(upload?file?.name:''),...(upload?{file}:{prompt:prompt.trim(),...(type==='portrait'?{characterId}:{})}),operationId:newAssetOperationId()};
    client.setQueryData(cacheKey,submission.current);
    mutation.mutate(submission.current);
  };
  return <Dialog open onOpenChange={open=>{if(!open&&!mutation.isPending)onClose();}}><DialogContent className="asset-composer-dialog" onEscapeKeyDown={event=>{if(mutation.isPending)event.preventDefault();}} onInteractOutside={event=>event.preventDefault()}><form className="assets-create-form" onSubmit={submit} aria-label={upload?'Upload asset':'Generate asset'}>
    <div className="assets-form-heading"><DialogTitle>{upload?'Upload asset':'Generate asset'}</DialogTitle></div><DialogDescription className="sr-only">{upload?'Choose a file and its asset type.':'Describe the image to create.'}</DialogDescription>
    <div className="assets-form-fields"><label><span>Type</span><GameSelect id={null} label="Asset type" games={(upload?uploadTypes:['map','blueprint','location',...((characters.length||onCharacters)?['portrait']:[])]).map(id=>({id:id==='other'?'unknown':id,name:assetTypeLabel(id)}))} value={type==='other'?'unknown':type} disabled={frozen} onChange={setType}/></label><div className="assets-form-field"><label htmlFor={`${fieldId}-name`}>Name{upload?' (optional)':''}</label><Input id={`${fieldId}-name`} value={name} required={!upload} maxLength={160} disabled={frozen} onChange={event=>setName(event.target.value)}/></div></div>
    {!upload&&type==='portrait'&&<label><span>Character</span><GameSelect label="Character" games={choices.map(character=>({id:character.id||character.characterId,name:character.name}))} value={characterId} disabled={frozen} onChange={setCharacterId}/></label>}
    {characterQuery.error&&type==='portrait'&&<p role="alert">{characterQuery.error.message||'Characters are unavailable.'}</p>}
    {upload?<div className="assets-form-field"><label htmlFor={`${fieldId}-file`}>File</label><Input id={`${fieldId}-file`} type="file" required disabled={frozen} onChange={event=>setFile(event.target.files?.[0]||null)}/></div>:<div className="assets-form-field"><label htmlFor={`${fieldId}-prompt`}>Prompt</label><Textarea id={`${fieldId}-prompt`} value={prompt} required rows={4} disabled={frozen} onChange={event=>setPrompt(event.target.value)}/></div>}
    {!mutation.error&&!mutation.isPending&&retained&&<p role="status">Submission not confirmed. Retry the same request.</p>}
    {mutation.error&&<p role="alert">{mutation.error.message||'Could not submit. Try again.'}</p>}
    <div className="assets-form-actions"><Button variant="secondary" disabled={mutation.isPending} onClick={onClose}>Cancel</Button><Button data-action-role={upload?'upload':'generate'} variant={upload?'outline':'default'} type="submit" className="assets-form-submit ui-action-button" disabled={mutation.isPending||(!submission.current&&(upload?!file:!name.trim()||!prompt.trim()||(type==='portrait'&&!characterId)))}>{upload?<Upload size={16} aria-hidden="true"/>:<Sparkles size={16} aria-hidden="true"/>}{mutation.isPending?(upload?'Uploading…':'Submitting…'):mutation.isError||Boolean(retained)?'Retry':upload?'Upload asset':'Generate asset'}</Button>
  </div></form></DialogContent></Dialog>;
}
