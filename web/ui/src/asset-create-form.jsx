import {Upload,Sparkles} from 'lucide-react';
import React,{useId,useRef,useState,useEffect} from 'react';
import {useMutation,useQueryClient,useQuery} from '@tanstack/react-query';
import {Button} from './components/ui/button.jsx';
import {Input} from './components/ui/input.jsx';
import {Textarea} from './components/ui/textarea.jsx';
import {Dialog,DialogContent,DialogTitle,DialogDescription} from './components/ui/dialog.jsx';
import {MultiSelect} from './components/ui/multi-select.jsx';
import {GameSelect} from './components/ui/select.jsx';
import {ModelSelect,modelPrice} from './components/ui/model-select.jsx';
import {definitiveValidationError,newAssetOperationId,assetUploadTypes,assetTypeLabel} from './assets-library-data.js';

export function AssetCreateForm({gameId,mode,initialType,initialName,initialPrompt,initialCharacterId,submissionScope,onUpload,onGenerate,onComplete,onClose,characters=[],onCharacters,uploadTypes=assetUploadTypes,generationTypes=[],imageAssets=[],hasMoreAssets=false,onMoreAssets,loadingAssets=false}) {
  const upload=mode==='upload';
  const fieldId=useId();
  const client=useQueryClient();
  const cacheKey=['asset-submission',gameId,mode,initialCharacterId||'game',submissionScope||'library'];
  const retained=client.getQueryData(cacheKey);
  const availableTypes=generationTypes.map(item=>item.id);
  const [type,setType]=useState(retained?.type||((upload?uploadTypes:availableTypes).includes(initialType)?initialType:upload?'other':availableTypes[0]));
  const capability=generationTypes.find(item=>item.id===type);
  const [model,setModel]=useState(retained?.model||capability?.defaultModel||''),[style,setStyle]=useState(retained?.style||capability?.defaultStyle||'');
  const [name,setName]=useState(retained?.name||initialName||''),[prompt,setPrompt]=useState(retained?.prompt||initialPrompt||''),[file,setFile]=useState(retained?.file||null);
  const [characterId,setCharacterId]=useState(retained?.characterId||initialCharacterId||''),[initialImageKey,setInitialImageKey]=useState(retained?.inputs?.initialImageKey||''),[voiceId,setVoiceId]=useState(retained?.inputs?.voiceId||''),[direction,setDirection]=useState(retained?.inputs?.direction||''),[cast,setCast]=useState(retained?.inputs?.characterIds||(initialCharacterId?[initialCharacterId]:[]));
  const selectedModel=capability?.models?.find(item=>item.id===model);
  const imageRequired=Boolean(selectedModel?.inputs?.requiresInitialImage);
  const mediaInputs=type==='video'?{duration:8,aspectRatio:'16:9',...(imageRequired&&initialImageKey?{initialImageKey}:{}),...(cast.length?{characterIds:cast}:{})}:type==='narration'?{voiceId,...(direction.trim()?{direction:direction.trim()}:{})}:null;
  const submission=useRef(retained||null);
  const mutation=useMutation({retry:false,mutationFn:payload=>upload?onUpload(payload):onGenerate(payload),onSuccess:result=>{client.removeQueries({queryKey:cacheKey,exact:true});onComplete(result,submission.current);},onError:error=>{if(definitiveValidationError(error)){submission.current=null;client.removeQueries({queryKey:cacheKey,exact:true});}}});
  const characterQuery=useQuery({queryKey:['asset-portrait-characters',gameId],queryFn:()=>onCharacters(),enabled:!upload&&['portrait','video'].includes(type)&&Boolean(onCharacters),retry:false,staleTime:30000});
  const choices=characterQuery.data?.characters||characters;
  useEffect(()=>{if(!submission.current){setModel(capability?.defaultModel||capability?.models?.[0]?.id||'');setStyle(capability?.defaultStyle||'');}},[type]);
  useEffect(()=>{if(!imageRequired&&!submission.current)setInitialImageKey('');},[model,type]);
  const frozen=mutation.isPending||Boolean(submission.current);
  const submit=event=>{
    event.preventDefault();
    if(!submission.current)submission.current={type,...(upload?{name:name.trim()||file?.name,file}:{prompt:prompt.trim(),...(model?{model}:{}),...(style&&capability?.styles?.some(item=>item.id===style)?{style}:{}),...(mediaInputs?{inputs:mediaInputs}:{}),...((initialCharacterId||type==='portrait')?{characterId:initialCharacterId||characterId}:{})}),operationId:newAssetOperationId()};
    client.setQueryData(cacheKey,submission.current);
    mutation.mutate(submission.current);
  };
  return <Dialog open onOpenChange={open=>{if(!open&&!mutation.isPending)onClose();}}><DialogContent className="asset-composer-dialog" onEscapeKeyDown={event=>{if(mutation.isPending)event.preventDefault();}} onInteractOutside={event=>event.preventDefault()}><form className="assets-create-form" onSubmit={submit} aria-label={upload?'Upload asset':'Generate asset'}>
    <div className="assets-form-heading"><DialogTitle>{upload?'Upload asset':'Generate asset'}</DialogTitle></div><DialogDescription className="sr-only">{upload?'Choose a file and its asset type.':'Choose what to create and describe it.'}</DialogDescription>
    <div className={upload?"assets-form-fields":"assets-form-field"}><label><span>Type</span><GameSelect id={null} label="Asset type" games={upload?uploadTypes.map(id=>({id:id==='other'?'unknown':id,name:assetTypeLabel(id)})):generationTypes.map(item=>({id:item.id,name:item.name||assetTypeLabel(item.id)}))} value={type==='other'?'unknown':type} disabled={frozen} onChange={setType}/></label><>{upload&&<div className="assets-form-field"><label htmlFor={`${fieldId}-name`}>Name (optional)</label><Input id={`${fieldId}-name`} value={name} maxLength={160} disabled={frozen} onChange={event=>setName(event.target.value)}/></div>}</></div>
    {!upload&&capability?.models?.length>0&&(capability.models.length>20?<ModelSelect models={capability.models} value={model} disabled={frozen} onChange={setModel}/>:<label><span>Model</span><GameSelect id={null} label="Model" games={capability.models} value={model} disabled={frozen} onChange={setModel}/></label>)}
    {!upload&&modelPrice(selectedModel)&&<p className="text-sm text-muted-foreground" role="status" title={selectedModel.priceEstimate.scope}>{modelPrice(selectedModel)}{type==='video'?' / 8 seconds':''}{selectedModel.provider?` · ${selectedModel.provider}`:''}{selectedModel.priceEstimate.checkedAt?` · Checked ${selectedModel.priceEstimate.checkedAt.slice(0,10)}`:selectedModel.priceEstimate.rateAsOf?` · Rates ${selectedModel.priceEstimate.rateAsOf}`:''}</p>}
    {!upload&&capability?.styles?.length>0&&<label><span>Style</span><GameSelect id={null} label="Style" games={[{id:'',name:'Game default'},...capability.styles]} value={style} disabled={frozen} onChange={setStyle}/></label>}
    {!upload&&capability?.available===false&&<p role="status">{capability.message||'Generation is currently unavailable for this type.'}</p>}
    {!upload&&type==='portrait'&&<label><span>Character</span><GameSelect id={null} label="Character" games={choices.map(character=>({id:character.id||character.characterId,name:character.name}))} value={characterId} disabled={frozen||Boolean(initialCharacterId)} onChange={setCharacterId}/></label>}
    {characterQuery.error&&['portrait','video'].includes(type)&&<p role="alert">Characters are unavailable.</p>}
    {!upload&&type==='video'&&imageRequired&&<label><span>Starting image{imageRequired?'':' (optional)'}</span><GameSelect id={null} label="Starting image" placeholder="Choose image" games={[...(!imageRequired?[{id:'',name:'None'}]:[]),...imageAssets.map(asset=>({id:asset.key,name:asset.title||asset.metadata?.title||asset.name||asset.key.split('/').at(-1)}))]} value={initialImageKey} disabled={frozen} onChange={setInitialImageKey}/></label>}
    {!upload&&type==='video'&&<>{hasMoreAssets&&onMoreAssets&&<Button variant="ghost" disabled={frozen||loadingAssets} onClick={onMoreAssets}>{loadingAssets?'Loading…':'Load more assets'}</Button>}<MultiSelect label="Characters (optional)" options={choices.map(character=>({id:character.id||character.characterId,name:character.name}))} value={cast} onChange={setCast} disabled={frozen} modal/></>}
    {!upload&&type==='narration'&&<><label><span>Voice</span><GameSelect id={null} label="Voice" placeholder="Choose voice" games={capability?.voices||[]} value={voiceId} disabled={frozen} onChange={setVoiceId}/></label><div className="assets-form-field"><label htmlFor={`${fieldId}-direction`}>Performance (optional)</label><Textarea id={`${fieldId}-direction`} value={direction} rows={2} disabled={frozen} onChange={event=>setDirection(event.target.value)}/></div></>}
    {upload?<div className="assets-form-field"><label htmlFor={`${fieldId}-file`}>File</label><Input id={`${fieldId}-file`} type="file" required disabled={frozen} onChange={event=>setFile(event.target.files?.[0]||null)}/></div>:<div className="assets-form-field"><label htmlFor={`${fieldId}-prompt`}>Prompt</label><Textarea id={`${fieldId}-prompt`} value={prompt} required maxLength={4000} placeholder={type==='narration'?'Words to speak…':'Describe what you want to create…'} rows={4} disabled={frozen} onChange={event=>setPrompt(event.target.value)}/></div>}
    {!mutation.error&&!mutation.isPending&&retained&&<p role="status">Submission not confirmed. Retry the same request.</p>}
    {mutation.error&&<p role="alert">{mutation.error.message||'Could not submit. Try again.'}</p>}
    <div className="assets-form-actions"><Button variant="secondary" disabled={mutation.isPending} onClick={onClose}>Cancel</Button><Button data-action-role={upload?'upload':'generate'} variant={upload?'outline':'default'} type="submit" className="assets-form-submit ui-action-button" disabled={mutation.isPending||(!submission.current&&(upload?!file:!capability||capability.available===false||!selectedModel||!prompt.trim()||(type==='portrait'&&!characterId)||(type==='video'&&imageRequired&&!initialImageKey)||(type==='narration'&&!voiceId)))}>{upload?<Upload size={16} aria-hidden="true"/>:<Sparkles size={16} aria-hidden="true"/>}{mutation.isPending?(upload?'Uploading…':'Submitting…'):mutation.isError||Boolean(retained)?'Retry':upload?'Upload asset':'Generate asset'}</Button>
  </div></form></DialogContent></Dialog>;
}
