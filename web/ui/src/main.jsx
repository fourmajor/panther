import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient as client } from "./data-layer.js";
import { GameSelect } from "./components/ui/select.jsx";
import { MediaBrowser } from "./media-browser.jsx";
import { AssetsLibrary } from "./assets-library.jsx";
import { MultiSelect } from "./components/ui/multi-select.jsx";
import { Users, Mic, BookOpen, Clapperboard, Folder, ArrowUpRight } from "lucide-react";
import "./styles.css";

const iconRoots=new WeakMap();
export function mountIcon(host,name){const Icon={characters:Users,sessions:Mic,novel:BookOpen,videos:Clapperboard,assets:Folder,arrow:ArrowUpRight}[name];if(!Icon)return;let root=iconRoots.get(host);if(!root){root=createRoot(host);iconRoots.set(host,root);}root.render(<Icon size={22} strokeWidth={1.7} aria-hidden="true"/>);}
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
  multiSelectRoots.get(host).render(<MultiSelect {...props} />);
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
const enhancedSelects = new WeakMap();
export function destroySelect(native) { enhancedSelects.get(native)?.(); }
export function enhanceSelect(native, label) {
  if (enhancedSelects.has(native)) return enhancedSelects.get(native);
  native.dataset.reactSelect="true";native.hidden=true;
  const host=document.createElement("span");host.className="panther-select-field";native.after(host);
  const selectRoot=createRoot(host);
  const render=()=>selectRoot.render(<QueryClientProvider client={client}><GameSelect portalContainer={()=>native.closest("dialog")||undefined} label={label} id={null} placeholder="Choose" games={[...native.options].map(option=>({id:option.value,name:option.textContent}))} value={native.value} disabled={native.disabled} onChange={value=>{native.value=value;render();native.dispatchEvent(new Event("change",{bubbles:true}));}} /></QueryClientProvider>);
  render();const observer=new MutationObserver(render);observer.observe(native,{childList:true,subtree:true,attributes:true,characterData:true});native.addEventListener("change",render);
  const cleanup=()=>{observer.disconnect();native.removeEventListener("change",render);selectRoot.unmount();host.remove();native.hidden=false;delete native.dataset.reactSelect;enhancedSelects.delete(native);};enhancedSelects.set(native,cleanup);return cleanup;
}
document.addEventListener("DOMContentLoaded", () => {
  syncGameSelector();
  const native = document.getElementById("game-selector");
  if (native) new MutationObserver(syncGameSelector).observe(native, { childList: true, subtree: true, characterData: true, attributes: true });
});
