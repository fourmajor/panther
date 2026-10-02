import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient as client } from "./data-layer.js";
import { GameSelect } from "./components/ui/select.jsx";
import { MediaBrowser } from "./media-browser.jsx";
import "./styles.css";

let root;
const mediaRoots = new WeakMap();
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
document.addEventListener("DOMContentLoaded", () => {
  syncGameSelector();
  const native = document.getElementById("game-selector");
  if (native) new MutationObserver(syncGameSelector).observe(native, { childList: true, subtree: true, characterData: true, attributes: true });
});
