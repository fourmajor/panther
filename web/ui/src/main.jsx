import {TranscriptSources} from './transcript-sources.jsx';
import {GameSystemPicker} from './game-system-picker.jsx';
import React from "react";
import {flushSync} from "react-dom";
import { DOMDialog } from "./dom-dialog.jsx";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient as client } from "./data-layer.js";
import { GameSelect } from "./components/ui/select.jsx";
import { MediaBrowser } from "./media-browser.jsx";
import { CreateGameDialog } from "./create-game-dialog.jsx";
import { AssetsLibrary } from "./assets-library.jsx";
import { SortableScenes } from "./sortable-scenes.jsx";
import { MultiSelect } from "./components/ui/multi-select.jsx";
import { buttonVariants } from "./components/ui/button.jsx";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "./components/ui/accordion.jsx";
import { Users, Mic, BookOpen, Clapperboard, Folder, ArrowUpRight, Upload, Sparkles } from "lucide-react";
import "./styles.css";

export function enhanceDialog(node,{onDismiss}={}){
  if(node.dataset.pantherDialog)return node;
  node.dataset.pantherDialog='true';node.hidden=true;
  let root=null,marker=null,parent=null,open=false,opener=null;
  Object.defineProperty(node,'open',{get:()=>open});
  node.showModal=()=>{
    if(open)return;
    open=true;node.hidden=false;node.setAttribute('open','');opener=document.activeElement;parent=node.parentElement||document.body;
    if(!node.parentElement)parent.append(node);
    marker=document.createElement('span');marker.hidden=true;node.before(marker);root=createRoot(marker);
    const labelled=node.getAttribute('aria-labelledby'),title=node.getAttribute('aria-label')||(labelled?document.getElementById(labelled)?.textContent:null)||node.querySelector('h1,h2,h3')?.textContent||'Details';
    flushSync(()=>root.render(<DOMDialog node={node} container={parent} title={title} onClose={()=>onDismiss?onDismiss():node.close()} opener={opener}/>));
  };
  node.close=()=>{
    if(!open)return;
    open=false;node.removeAttribute('open');flushSync(()=>root.unmount());root=null;marker.remove();marker=null;node.hidden=true;
    node.dispatchEvent(new Event('close'));
  };
  const remove=node.remove.bind(node);
  node.remove=()=>{if(open)node.close();remove();};
  return node;
}
export function createDialog(){return enhanceDialog(document.createElement('div'));}
export function openCreateGameDialog(props){
  const host=document.createElement('div');document.body.append(host);const root=createRoot(host);let closed=false;
  const close=()=>{if(closed)return;closed=true;queueMicrotask(()=>{root.unmount();host.remove();props.onClose?.();});};
  root.render(<CreateGameDialog {...props} onClose={close} onComplete={id=>{close();props.onComplete(id);}}/>);return close;
}
const iconRoots=new WeakMap();
const generationRoots=new WeakMap();
export function clearGenerationDetails(host){generationRoots.get(host)?.unmount();generationRoots.delete(host);host.replaceChildren();}
export function mountGenerationDetails(host,rows){clearGenerationDetails(host);const root=createRoot(host);generationRoots.set(host,root);root.render(<Accordion type="single" collapsible><AccordionItem value="generation"><AccordionTrigger>Generation details</AccordionTrigger><AccordionContent><dl>{rows.map(([label,value])=><React.Fragment key={label}><dt>{label}</dt><dd>{value}</dd></React.Fragment>)}</dl></AccordionContent></AccordionItem></Accordion>);}
export function mountIcon(host,name){const Icon={characters:Users,sessions:Mic,novel:BookOpen,videos:Clapperboard,assets:Folder,arrow:ArrowUpRight}[name];if(!Icon)return;let root=iconRoots.get(host);if(!root){root=createRoot(host);iconRoots.set(host,root);}root.render(<Icon size={22} strokeWidth={1.7} aria-hidden="true"/>);}
// Imperative controllers compose the same registry Button variants and Lucide
// icons as React forms. Observe label replacement so pending/retry updates keep
// their existing icon without rebuilding the application's event handlers.
const actionIcons=new WeakMap();
export function enhanceActionButton(button){
  const label=button.textContent.trim();
  const previous=actionIcons.get(button);
  const role=/^Upload(?:\s|$)/i.test(label)?'upload':/^Generate(?:\s|$)/i.test(label)?'generate':previous?.role;
  if(!role||(!previous&&button.querySelector('svg')))return;
  if(!previous){
    button.classList.add(...buttonVariants({variant:role==='upload'?'outline':'default'}).split(/\s+/),'ui-action-button');
    button.dataset.actionRole=role;
  }
  if(previous?.host.parentNode===button)return;
  previous?.iconRoot.unmount();
  const host=document.createElement('span');host.className='action-icon';host.setAttribute('aria-hidden','true');button.prepend(host);
  const iconRoot=createRoot(host),Icon=role==='upload'?Upload:Sparkles;
  actionIcons.set(button,{role,host,iconRoot});iconRoot.render(<Icon size={16} aria-hidden="true"/>);
}
function enhanceActionButtons(){
  document.querySelectorAll('button').forEach(enhanceActionButton);
  new MutationObserver(records=>{
    const buttons=new Set();
    for(const record of records){const owner=record.target.nodeType===1?record.target:record.target.parentElement;const button=owner?.closest('button');if(button)buttons.add(button);for(const added of record.addedNodes){if(added.nodeType!==1)continue;if(added.matches('button'))buttons.add(added);added.querySelectorAll('button').forEach(button=>buttons.add(button));}}
    buttons.forEach(enhanceActionButton);
  }).observe(document.body,{childList:true,subtree:true,characterData:true});
}
export function unmountIcon(host){iconRoots.get(host)?.unmount();iconRoots.delete(host);}
let root;
const mediaRoots = new WeakMap();
const assetsRoots = new WeakMap();
const multiSelectRoots = new WeakMap();
export function unmountMultiSelect(host) {
  multiSelectRoots.get(host)?.unmount();
  multiSelectRoots.delete(host);
}
export function mountMultiSelect(host, props) {
  if (!multiSelectRoots.has(host)) multiSelectRoots.set(host, createRoot(host));
  multiSelectRoots.get(host).render(<MultiSelect {...props} modal={Boolean(host.closest('[role="dialog"]'))} />);
}
const transcriptSourceRoots=new WeakMap();
export function mountTranscriptSources(host,props){
  if(!transcriptSourceRoots.has(host))transcriptSourceRoots.set(host,createRoot(host));
  flushSync(()=>transcriptSourceRoots.get(host).render(<TranscriptSources {...props}/>));
}
const gameSystemRoots=new WeakMap();
export function mountGameSystemPicker(host,props){
  if(!gameSystemRoots.has(host))gameSystemRoots.set(host,createRoot(host));
  gameSystemRoots.get(host).render(<GameSystemPicker key={props.gameId} {...props}/>);
}
export function unmountAssetsLibrary(host) {
  assetsRoots.get(host)?.unmount();
  assetsRoots.delete(host);
}
export function mountAssetsLibrary(host, props) {
  if (!assetsRoots.has(host)) assetsRoots.set(host, createRoot(host));
  assetsRoots.get(host).render(<QueryClientProvider client={client}><AssetsLibrary {...props} /></QueryClientProvider>);
}
export function unmountMediaBrowser(host) {
  mediaRoots.get(host)?.unmount();
  mediaRoots.delete(host);
}
export function mountMediaBrowser(host, props) {
  if (!mediaRoots.has(host)) mediaRoots.set(host, createRoot(host));
  mediaRoots.get(host).render(<QueryClientProvider client={client}><MediaBrowser {...props} /></QueryClientProvider>);
}
export { queryClient, query, invalidate, revalidate, clear } from "./data-layer.js";
export function syncGameSelector() {
  const native = document.getElementById("game-selector");
  const host = document.getElementById("game-select-root");
  if (!native || !host) return;
  root ||= createRoot(host);
  const games = Array.from(native.options, option => ({ id: option.value, name: option.textContent }));
  root.render(<QueryClientProvider client={client}><GameSelect games={games} value={native.value} disabled={native.disabled} onChange={value => {
    native.value = value; syncGameSelector(); native.dispatchEvent(new Event("change", { bubbles: true }));
  }} /></QueryClientProvider>);
}
const sceneRoots=new WeakMap();
export function mountSortableScenes(host,props){if(!sceneRoots.has(host))sceneRoots.set(host,createRoot(host));sceneRoots.get(host).render(<SortableScenes {...props}/>);}
export function unmountSortableScenes(host){sceneRoots.get(host)?.unmount();sceneRoots.delete(host);}
const enhancedSelects = new WeakMap();
export function destroySelect(native) { enhancedSelects.get(native)?.(); }
export function enhanceSelect(native, label) {
  if (enhancedSelects.has(native)) return enhancedSelects.get(native);
  native.dataset.reactSelect="true";native.hidden=true;
  const host=document.createElement("span");host.className="panther-select-field";native.after(host);
  const selectRoot=createRoot(host);
  const render=()=>selectRoot.render(<QueryClientProvider client={client}><GameSelect label={label} id={null} placeholder="Choose" games={[...native.options].map(option=>({id:option.value,name:option.textContent}))} value={native.value} disabled={native.disabled} onChange={value=>{native.value=value;render();native.dispatchEvent(new Event("change",{bubbles:true}));}} /></QueryClientProvider>);
  render();const observer=new MutationObserver(render);observer.observe(native,{childList:true,subtree:true,attributes:true,characterData:true});native.addEventListener("change",render);
  const cleanup=()=>{observer.disconnect();native.removeEventListener("change",render);selectRoot.unmount();host.remove();native.hidden=false;delete native.dataset.reactSelect;enhancedSelects.delete(native);};enhancedSelects.set(native,cleanup);return cleanup;
}
document.addEventListener("DOMContentLoaded", () => {
  syncGameSelector();
  enhanceActionButtons();
  const native = document.getElementById("game-selector");
  if (native) new MutationObserver(syncGameSelector).observe(native, { childList: true, subtree: true, characterData: true, attributes: true });
});
