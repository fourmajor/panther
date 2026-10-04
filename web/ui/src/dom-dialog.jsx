import React,{useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {X} from 'lucide-react';
import {Dialog,DialogContent,DialogTitle,DialogDescription} from './components/ui/dialog.jsx';
import {buttonVariants} from './components/ui/button.jsx';
const footerSelector='form > .model-control-row, form > .episode-form-actions, form > .editorial-form-actions, form > .local-generation-actions';
function dedicatedClose(node){return [...node.querySelectorAll('button')].filter(button=>/^Close(?: |$)/.test(button.getAttribute('aria-label')||'')||(/^Close(?: |$)/.test(button.textContent.trim())&&(button.closest('header,.preview-header,.room-dialog-heading')||button.id==='style-preview-close')));}
// Existing controllers keep their handlers; shared slots only provide presentation.
// Radix remains responsible for portals, modality, dismissal and focus restoration.
function DOMContents({node,container,closes}) {
  const content=useRef(null),[icons,setIcons]=useState([]);
  useLayoutEffect(()=>{
    const title=node.querySelector('h1,h2,h3');if(title)title.dataset.slot='dialog-title';
    for(const footer of node.querySelectorAll(footerSelector)){
      footer.dataset.slot='dialog-footer';footer.classList.add('panther-dialog-footer');
      const form=footer.parentElement;
      if(form?.tagName==='FORM'&&!form.querySelector(':scope > [data-slot=dialog-body]')){
        const body=document.createElement('div');body.dataset.slot='dialog-body';body.className=form.className;
        for(const child of [...form.children])if(child!==footer&&!child.matches('header,h1,h2,h3'))body.append(child);
        form.insertBefore(body,footer);
      }
      for(const button of footer.querySelectorAll(':scope > button')){
        const cancel=/^(Cancel|Close)$/.test(button.textContent.trim());
        button.classList.add(...buttonVariants({variant:cancel?'outline':'default'}).split(/\s+/),'ui-action-button');button.dataset.dialogAction=cancel?'cancel':'submit';
      }
    }
    const hosts=closes.map(button=>{const label=button.getAttribute('aria-label')||'Close';button.dataset.slot='dialog-close';button.classList.add('panther-dialog-close');button.setAttribute('aria-label',label);const host=document.createElement('span');host.setAttribute('aria-hidden','true');button.replaceChildren(host);return host;});
    content.current.append(node);setIcons(hosts);
    return()=>{if(node.parentNode)container.append(node);};
  },[node,container]);
  return <><div ref={content} style={{display:'contents'}}/>{icons.map((host,index)=>createPortal(<X size={16} aria-hidden="true"/>,host,String(index)))}</>;
}
export function DOMDialog({node,container,title,onClose,opener}){
  const closes=dedicatedClose(node),variant=node.dataset.dialogVariant||(node.classList.contains('room-recording-dialog')?'recording':node.classList.contains('preview')||node.classList.contains('style-preview-dialog')||node.classList.contains('episode-playback-dialog')?'media':node.querySelector('form')?'form':'content');
  return <Dialog open onOpenChange={open=>{if(!open)onClose();}}><DialogContent variant={variant} hideClose={closes.length>0} className={`panther-dom-dialog ${node.className}`} aria-label={title} onCloseAutoFocus={event=>{event.preventDefault();if(opener?.isConnected&&!opener.closest('[hidden]'))opener.focus({preventScroll:true});}}><DialogTitle asChild><span className="sr-only">{title}</span></DialogTitle><DialogDescription className="sr-only">{title}</DialogDescription><DOMContents node={node} container={container} closes={closes}/></DialogContent></Dialog>;
}
