import React,{useId,useRef,useState} from 'react';
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription,DialogFooter} from './components/ui/dialog.jsx';
import {Button} from './components/ui/button.jsx';
import {Field,FieldGroup,FieldLabel} from './components/ui/field.jsx';
import {Input} from './components/ui/input.jsx';
import {GameSystemPicker} from './game-system-picker.jsx';
export function CreateGameDialog({onCreate,onComplete,onClose}){
  const prefix=useId(),[name,setName]=useState(''),[system,setSystem]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const identity=useRef(null),suffix=useRef(crypto.randomUUID().slice(0,8));
  const submit=async event=>{event.preventDefault();if(!name.trim()||busy)return;identity.current||=(name.trim().toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,65)||'game')+'-'+suffix.current;setBusy(true);setError('');try{await onCreate({id:identity.current,name:name.trim(),purpose:'campaign',players:[],characters:[],memberships:[],...(system.trim()?{ruleset:system.trim()}:{})});onComplete(identity.current);}catch{setError('Could not create the game. Your details are saved here; try again.');}finally{setBusy(false);}};
  return <Dialog open onOpenChange={open=>{if(!open&&!busy)onClose();}}><DialogContent className="create-game-dialog" aria-label="Create Game" onEscapeKeyDown={event=>{if(busy)event.preventDefault();}} onInteractOutside={event=>event.preventDefault()}><DialogHeader><DialogTitle>Create Game</DialogTitle><DialogDescription className="sr-only">Name your game and optionally choose its system.</DialogDescription></DialogHeader><form onSubmit={submit} className="assets-create-form"><FieldGroup><Field><FieldLabel htmlFor={`${prefix}-name`}>Name</FieldLabel><Input id={`${prefix}-name`} required maxLength={120} autoFocus disabled={busy} value={name} onChange={event=>setName(event.target.value)}/></Field><GameSystemPicker value={system} onChange={setSystem} disabled={busy}/>{error&&<p role="alert">{error}</p>}</FieldGroup><DialogFooter className="assets-form-actions"><Button variant="outline" disabled={busy} onClick={onClose}>Cancel</Button><Button type="submit" disabled={busy||!name.trim()}>{busy?'Creating…':'Create Game'}</Button></DialogFooter></form></DialogContent></Dialog>;
}
