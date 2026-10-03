import React,{useLayoutEffect,useRef} from 'react';
import {Dialog,DialogContent,DialogTitle,DialogDescription} from './components/ui/dialog.jsx';
// Mount existing application form content in the standard Dialog. Radix owns
// modality, keyboard dismissal, portal rendering and the focus scope.
function DOMContents({node,container}) {
  const content=useRef(null);
  useLayoutEffect(()=>{content.current.append(node);return()=>{if(node.parentNode)container.append(node);};},[node,container]);
  return <div ref={content} style={{display:'contents'}}/>;
}
export function DOMDialog({node,container,title,onClose,opener}){
  const hasClose=[...node.querySelectorAll('button')].some(button=>/^Close(?: |$)/.test(button.textContent.trim())||/^Close(?: |$)/.test(button.getAttribute('aria-label')||''));
  return <Dialog open onOpenChange={open=>{if(!open)onClose();}}><DialogContent hideClose={hasClose} className={`panther-dom-dialog ${node.className}`} aria-label={title} onCloseAutoFocus={event=>{event.preventDefault();if(opener?.isConnected&&!opener.closest('[hidden]'))opener.focus({preventScroll:true});}}><DialogTitle asChild><span className="sr-only">{title}</span></DialogTitle><DialogDescription className="sr-only">{title}</DialogDescription><DOMContents node={node} container={container}/></DialogContent></Dialog>;
}
