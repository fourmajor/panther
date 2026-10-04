// Shared shadcn-style Field composition for React and imperative dialog controllers.
import React from 'react';
import {inputClasses} from './input.jsx';
import {textareaClasses} from './textarea.jsx';
import {cn} from '../../lib/utils.js';
export const fieldClasses={group:'flex flex-col gap-6',field:'flex w-full min-w-0 flex-col gap-2',label:'text-sm font-medium leading-5'};
export function FieldGroup({className,...props}){return <div data-slot="field-group" className={cn(fieldClasses.group,className)} {...props}/>;}
export function Field({className,...props}){return <div data-slot="field" className={cn(fieldClasses.field,className)} {...props}/>;}
export function FieldLabel({className,...props}){return <label data-slot="field-label" className={cn(fieldClasses.label,className)} {...props}/>;}
// Controllers retain the actual controls and their handlers, while sharing the
// same Field spacing and labels used by React forms.
export function styleFormFields(body){
 body.dataset.slot='dialog-body';body.dataset.fieldGroup='true';body.classList.add(...fieldClasses.group.split(' '));
 for(const label of body.querySelectorAll('label')){
  if(!label.querySelector('input:not([type=checkbox]):not([type=radio]):not([type=hidden]),textarea,select'))continue;
  label.dataset.slot='field';label.classList.add(...fieldClasses.field.split(' '));
  const text=[...label.childNodes].filter(node=>node.nodeType===3&&node.textContent.trim());
  if(text.length){const caption=document.createElement('span');caption.dataset.slot='field-label';caption.className=fieldClasses.label;label.prepend(caption);for(const node of text)caption.append(node);}
  for(const control of label.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=hidden]),textarea'))control.classList.add(...(control.tagName==='TEXTAREA'?textareaClasses:inputClasses).split(' '));
 }
}
