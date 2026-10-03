const config = window.PANTHER_CONFIG;

// Alternate shells share the exact same live DOM and data layer. Never remount
// editors, media, recording controls or the model viewer just to compare a look.
(() => {
  const designs = [
    {id:"studio", name:"Studio", label:"The original", description:"Quiet dark surfaces, familiar tabs, balanced cards. The original interface remains the default."},
    {id:"chronicle", name:"Chronicle", label:"Turn the campaign’s pages", description:"A two-page campaign book. Choose a chapter from the table of contents, then read its recent entries on the facing page."},
    {id:"cinema", name:"Cinema", label:"Browse a streaming library", description:"A screening-room home with a featured screening, horizontal media shelves and a production doorway."},
    {id:"mission", name:"Production Board", label:"Follow the assembly line", description:"Three working lanes: source material, stories in production, and finished media. Reviews sit above the board."},
    {id:"poster", name:"Pinboard", label:"Explore a wall of evidence", description:"Numbered, oversized notes arranged around a central campaign hub. Follow the connections to your cast and stories."},
    {id:"field", name:"Explorer", label:"Search, select, inspect", description:"A searchable directory and inspector. Pick a collection on the left; inspect its recent contents on the right."},
  ];
  const key = "panther.interface.v1";
  const valid = id => designs.some(design => design.id === id);
  let saved = "studio";
  try { const value = localStorage.getItem(key); if (valid(value)) saved = value; } catch { /* Optional preference storage. */ }
  const requested = new URL(location.href).searchParams.get("ui");
  let candidate = valid(requested) ? requested : saved;
  let comparing = false;
  const root = document.documentElement;
  const dialog = document.getElementById("design-atlas");
  const open = document.getElementById("design-open");
  const tools = document.getElementById("design-preview-tools");
  const feedback = document.getElementById("design-feedback");
  const compare = document.getElementById("design-compare");
  const options = document.getElementById("design-options");
  function render() {
    const showing = comparing ? saved : candidate;
    root.dataset.interface = showing;
    root.dataset.interfacePreview = String(candidate !== saved);
    document.dispatchEvent(new CustomEvent("panther-interface-changed"));
    document.getElementById("design-current").textContent = designs.find(item => item.id === showing).name;
    tools.hidden = candidate === saved;
    compare.setAttribute("aria-pressed", String(comparing));
    compare.textContent = comparing ? "Back to preview" : "Compare saved";
    for (const button of options.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.design === candidate));
      button.querySelector(".atlas-saved").hidden = button.dataset.design !== saved;
    }
  }
  function announce(message) { feedback.textContent = message; }
  function preview(id) {
    candidate = id; comparing = false; render();
    announce(`Previewing ${designs.find(item => item.id === id).name}. Nothing has been saved.`);
  }
  for (const [index, design] of designs.entries()) {
    const button = document.createElement("button");
    button.type = "button"; button.dataset.design = design.id;
    button.className = "atlas-option";
    const sketch = document.createElement("span");
    sketch.className = "atlas-sketch"; sketch.setAttribute("aria-hidden", "true");
    sketch.innerHTML = '<span class="sketch-nav"></span><span class="sketch-title"></span><span class="sketch-tile"></span><span class="sketch-tile"></span><span class="sketch-tile"></span>';
    const number = document.createElement("span"); number.className = "atlas-number"; number.textContent = String(index + 1).padStart(2,"0");
    const title = document.createElement("strong"); title.textContent = design.name;
    const label = document.createElement("span"); label.className = "atlas-label"; label.textContent = design.label;
    const description = document.createElement("span"); description.className = "atlas-description"; description.textContent = design.description;
    const badge = document.createElement("span"); badge.className = "atlas-saved"; badge.textContent = "Saved look";
    button.append(sketch, number, title, label, description, badge);
    button.addEventListener("click", () => { preview(design.id); dialog.close(); });
    options.append(button);
  }
  open.addEventListener("click", () => { render(); dialog.showModal(); });
  document.getElementById("design-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => open.focus({preventScroll:true}));
  document.getElementById("design-previous").addEventListener("click", () => preview(designs[(designs.findIndex(item => item.id === candidate) + 5) % 6].id));
  document.getElementById("design-next").addEventListener("click", () => preview(designs[(designs.findIndex(item => item.id === candidate) + 1) % 6].id));
  compare.addEventListener("click", () => { comparing = !comparing; render(); announce(comparing ? "Showing your saved interface for comparison." : "Back to the preview."); });
  function cancel() { candidate = saved; comparing = false; render(); open.focus({preventScroll:true}); announce("Preview canceled. Your saved interface is restored."); }
  document.getElementById("design-cancel").addEventListener("click", cancel);
  document.getElementById("design-keep").addEventListener("click", () => {
    saved = candidate; comparing = false;
    let stored = true;
    try { localStorage.setItem(key, saved); } catch { stored = false; }
    const url = new URL(location.href);
    if (url.searchParams.has("ui")) { url.searchParams.delete("ui"); history.replaceState(history.state,"",url); }
    render(); open.focus({preventScroll:true});
    announce(stored ? "Interface saved for this browser." : "Interface selected for this visit. Your browser prevented saving the preference.");
  });
  document.addEventListener("keydown", event => {
    if (event.defaultPrevented || event.repeat) return;
    if (event.key === "Escape" && !dialog.open && candidate !== saved && !document.querySelector("dialog[open]")) { cancel(); return; }
    const editing = event.target.closest?.("input,textarea,select,[contenteditable=true],[role=textbox],[role=combobox]");
    if (!editing && event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && event.key.toLowerCase() === "d") {
      event.preventDefault(); if (!dialog.open && !document.querySelector("dialog[open]")) dialog.showModal();
    }
  });
  render();
})();

// One loading treatment everywhere. Counts come from responses, never simulated percentages.
const loadingStates = new WeakMap();
function showLoading(host, message) {
  loadingStates.get(host)?.stop();
  if (host.matches("#characters-status, #novel-status, #library-status, #status")) {
    // Reserve the existing status geometry during refresh/pagination, including
    // empty padded slots. The activity indicator itself stays outside the flow.
    const previousHeight = host.textContent.trim() !== "Loading…"
      ? host.getBoundingClientRect().height : 0;
    host.style.setProperty("--loading-slot-height", `${previousHeight}px`);
  }
  const root = document.createElement("span"), skeleton = document.createElement("span");
  const label = document.createElement("span");
  root.className = "loading-state"; root.setAttribute("role", "status");
  skeleton.className = "loading-skeleton"; skeleton.setAttribute("aria-hidden", "true");
  label.className = "loading-label sr-only"; label.textContent = message;
  root.append(skeleton, label); host.replaceChildren(root);
  const control = {stop() {}, update(text) { if (host.contains(root)) label.textContent = text; }};
  loadingStates.set(host, control); return control;
}

const elements = {
  gameToolbar: document.querySelector("#game-toolbar"),
  gameSelector: document.querySelector("#game-selector"),
  gamePurpose: document.querySelector("#game-purpose"),
  gameRuleset: document.querySelector("#game-ruleset"),
  playerRoster: document.querySelector("#player-roster"),
  account: document.querySelector("#account"),
  authError: document.querySelector("#auth-error"),
  breadcrumbs: document.querySelector("#breadcrumbs"),
  characterBack: document.querySelector("#character-back"),
  characterList: document.querySelector("#character-list"),
  characterModel: document.querySelector("#character-model"),
  characterName: document.querySelector("#character-name"),
  characterPoster: document.querySelector("#character-poster"),
  characterProfile: document.querySelector("#character-profile"),
  characters: document.querySelector("#characters"),
  charactersStatus: document.querySelector("#characters-status"),
  characterSummary: document.querySelector("#character-summary"),
  characterTitle: document.querySelector("#character-title"),
  entries: document.querySelector("#entries"),
  explorer: document.querySelector("#explorer"),
  fallbackPoster: document.querySelector("#fallback-poster"),
  fileTemplate: document.querySelector("#file-template"),
  folderTemplate: document.querySelector("#folder-template"),
  loadMore: document.querySelector("#load-more-button"),
  login: document.querySelector("#login-button"),
  logout: document.querySelector("#logout-button"),
  modelFallback: document.querySelector("#model-fallback"),
  modelFallbackMessage: document.querySelector("#model-fallback-message"),
  modelLoad: document.querySelector("#model-load"),
  modelProgressBar: document.querySelector("#model-progress-bar"),
  modelReset: document.querySelector("#model-reset"),
  modelSize: document.querySelector("#model-size"),
  modelSource: document.querySelector("#model-source"),
  modelStatus: document.querySelector("#model-status"),
  openOriginal: document.querySelector("#open-original"),
  primaryNav: document.querySelector("#primary-nav"),
  previewBody: document.querySelector("#preview-body"),
  previewClose: document.querySelector("#preview-close"),
  previewDetails: document.querySelector("#preview-details"),
  previewDialog: document.querySelector("#preview-dialog"),
  previewTitle: document.querySelector("#preview-title"),
  refresh: document.querySelector("#refresh-button"),
  status: document.querySelector("#status"),
  username: document.querySelector("#username"),
  welcome: document.querySelector("#welcome"),
  novel: document.querySelector("#novel"),
};

const state = {
  games: null,
  gameId: null,
  gameDetail: null,
  charactersLoaded: false,
  currentPrefix: "games/",
  currentCharacter: null,
  currentCharacterFacts: null,
  appearanceVersions: null,
  mediaLoaded: false,
  nextCursor: null,
  tokens: readTokens(),
};
let refreshingSession = null;
let routeEpoch = 0;
let listingEpoch = 0;
let previewEpoch = 0;
let sessionEpoch = 0;
let roomCapture = null;
const LOGOUT_MARKER = "panther.signed-out";

function logoutPending() {
  try { return localStorage.getItem(LOGOUT_MARKER) === "true"; } catch { return false; }
}

function markLogout(pending) {
  try {
    if (pending) localStorage.setItem(LOGOUT_MARKER, "true");
    else localStorage.removeItem(LOGOUT_MARKER);
  } catch { /* Private browsing may disable storage; HttpOnly cookie still works. */ }
}

function withSessionLock(action) {
  // Serialize cookie rotation and logout across tabs where Web Locks is available.
  return navigator.locks ? navigator.locks.request("panther-session", action) : action();
}

async function sessionRequest(path, body = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST", credentials: "same-origin",
      headers: { "content-type": "application/json" }, body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new Error("Could not renew sign-in. Check your connection and try again.");
  }
  if (response.status === 401) {
    clearSession();
    showWelcome("Please sign in again.");
    throw new Error("Session expired");
  }
  if (!response.ok) throw new Error("Sign-in service temporarily unavailable. Please retry.");
  return response.json();
}

async function ensureSession({ force = false } = {}) {
  if (logoutPending()) {
    clearSession();
    throw new Error("Signed out. Sign in to continue.");
  }
  if (!force && tokensAreCurrent(state.tokens) && !state.tokens.refresh_token) return;
  if (refreshingSession) return refreshingSession;
  const epoch = sessionEpoch;
  refreshingSession = withSessionLock(async () => {
    if (logoutPending() || epoch !== sessionEpoch) throw new Error("Session expired");
    // Migrate old per-tab refresh credentials into the HttpOnly cookie once.
    const legacy = state.tokens?.refresh_token;
    const tokens = await sessionRequest(legacy ? "/auth/session" : "/auth/refresh",
      legacy ? { refreshToken: legacy } : {});
    if (epoch !== sessionEpoch || logoutPending()) throw new Error("Session expired");
    if (!tokensAreCurrent(tokens)) throw new Error("Invalid sign-in response. Please retry.");
    storeTokens(tokens);
  }).finally(() => { refreshingSession = null; });
  return refreshingSession;
}

function base64Url(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

function randomValue(length = 32) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

async function sha256(value) {
  return base64Url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))));
}

function readTokens() {
  try {
    return JSON.parse(sessionStorage.getItem("panther.tokens")) || null;
  } catch {
    return null;
  }
}

function decodeToken(token) {
  const encoded = token.split(".")[1].replaceAll("-", "+").replaceAll("_", "/");
  const padded = encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "=");
  const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

function tokensAreCurrent(tokens) {
  if (!tokens?.id_token) return false;
  try {
    return decodeToken(tokens.id_token).exp * 1000 > Date.now() + 30_000;
  } catch {
    return false;
  }
}

function storeTokens(tokens) {
  // Only the short-lived ID credential belongs in page-readable, per-tab storage.
  state.tokens = { id_token: tokens.id_token };
  sessionStorage.setItem("panther.tokens", JSON.stringify(state.tokens));
}

function clearSession() {
  roomCapture?.interrupt();
  assetUploads.clear();assetGenerationJobs.clear();assetListing={gameId:null,assets:[],cursor:null,loading:false,error:'',pages:0};
  window.PantherUI.clear();
  resetLive();
  state.games = null;
  state.gameId = null;
  state.gameDetail = null;
  routeEpoch += 1;
  listingEpoch += 1;
  closePreview();
  sessionEpoch += 1;
  state.tokens = null;
  state.charactersLoaded = false;
  state.mediaLoaded = false;
  state.currentCharacter = null;
  clearNovel();
  clearLibrary();
  elements.characterModel.src = null;
  document.getElementById("character-assets-list").replaceChildren();
  document.getElementById("character-assets-status").textContent = "";
  elements.previewBody.replaceChildren();
  if (elements.previewDialog.open) elements.previewDialog.close();
  elements.username.textContent = "Signed out";
  closeAccountSettings();
  sessionStorage.removeItem("panther.tokens");
  sessionStorage.removeItem("panther.oauth");
}

async function login() {
  const verifier = randomValue(64);
  const oauthState = randomValue(24);
  sessionStorage.setItem(
    "panther.oauth",
    JSON.stringify({ returnPath: window.location.pathname, verifier, state: oauthState }),
  );

  const parameters = new URLSearchParams({
    client_id: config.clientId,
    code_challenge: await sha256(verifier),
    code_challenge_method: "S256",
    redirect_uri: config.redirectUri,
    response_type: "code",
    scope: "openid profile email aws.cognito.signin.user.admin",
    state: oauthState,
  });
  window.location.assign(`${config.cognitoDomain}/oauth2/authorize?${parameters}`);
}

async function completeLogin() {
  const parameters = new URLSearchParams(window.location.search);
  if (parameters.get("error")) {
    throw new Error(parameters.get("error_description") || "Sign-in was not completed.");
  }
  const code = parameters.get("code");
  if (!code) return;

  const saved = JSON.parse(sessionStorage.getItem("panther.oauth") || "null");
  if (!saved || saved.state !== parameters.get("state")) {
    throw new Error("The sign-in response could not be verified. Please try again.");
  }

  // Exchange the code server-side so the refresh credential never reaches JS.
  const tokens = await withSessionLock(() => sessionRequest("/auth/session", {
    code, codeVerifier: saved.verifier,
  }));
  if (!tokensAreCurrent(tokens)) throw new Error("Sign-in did not complete. Please try again.");
  markLogout(false);
  storeTokens(tokens);
  sessionStorage.removeItem("panther.oauth");
  window.history.replaceState({}, "", saved.returnPath || "/dashboard");
}

async function logout() {
  markLogout(true);
  clearSession();
  showWelcome("Signing out…");
  try {
    await withSessionLock(() => sessionRequest("/auth/logout"));
  } catch (error) {
    if (error.message !== "Session expired") {
      showWelcome("Signed out locally. Could not revoke the remembered sign-in; reconnect and retry sign-out.");
      elements.logout.hidden = false;
      elements.account.hidden = false;
      return;
    }
  }
  const parameters = new URLSearchParams({
    client_id: config.clientId,
    logout_uri: config.redirectUri,
  });
  window.location.assign(`${config.cognitoDomain}/logout?${parameters}`);
}

async function apiRequest(path, parameters = {}, options = {}) {
  await ensureSession();
  const url = new URL(path, config.apiUrl);
  for (const [key, value] of Object.entries(parameters)) {
    if (value) url.searchParams.set(key, value);
  }
  const requestSignal = options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(30000)]) : AbortSignal.timeout(30000);
  let response = await fetch(url, {
    signal: requestSignal,
    method: options.body ? "POST" : "GET",
    body: options.body ? JSON.stringify(options.body) : undefined,
    headers: { authorization: `Bearer ${state.tokens.id_token}`, ...(options.body ? {"content-type":"application/json"} : {}) },
  });
  if (response.status === 401) {
    await ensureSession({ force: true });
    response = await fetch(url, { signal: requestSignal, method: options.body ? "POST" : "GET",
      body: options.body ? JSON.stringify(options.body) : undefined,
      headers: { authorization: `Bearer ${state.tokens.id_token}`, ...(options.body ? {"content-type":"application/json"} : {}) } });
  }
  if (response.status === 401) {
    clearSession();
    showWelcome("Your session has expired. Please sign in again.");
    throw new Error("Session expired");
  }
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(body.error || "The media service could not be reached.");
    error.status = response.status; throw error;
  }
  return body;
}

// The React and legacy views share one authenticated TanStack Query cache.
// Catalog reads deduplicate and stay warm between tabs; durable mutations
// invalidate their account scope. Live jobs and signed URLs remain time-sensitive.
function apiScope() {
  const claims = decodeToken(state.tokens.id_token);
  return JSON.stringify([claims.iss || "", claims.sub || claims["cognito:username"] || claims.username || ""]);
}
function mutationReadPaths(path) {
  if (["/image-links", "/uploads", "/browser-transcriptions"].includes(path)) return [];
  if (path.startsWith("/game/") && path !== "/game/characters") return ["/games", "/game", "/dashboard-recent"];
  if (path === "/game/characters" || path.startsWith("/character-")) return ["/game", "/characters", "/character", "/character-details", "/character-details/history", "/character-versions", "/dashboard-recent"];
  if (path === "/novel-chapters") return ["/novel", "/novel-chapter", "/assets", "/objects", "/dashboard-recent"];
  if (["/episodes", "/scenes"].includes(path)) return ["/episodes", "/scenes", "/episode-composition", "/assets", "/dashboard-recent"];
  if (path === "/video-collections") return ["/video-collections", "/dashboard-recent"];
  if (path === "/editorial-jobs") return ["/editorial-jobs"];
  if (path === "/transcript-selection") return ["/transcript-selection", "/assets", "/dashboard-recent"];
  return ["/assets", "/objects", "/asset-document", "/dashboard-recent"];
}
async function api(path, parameters = {}, options = {}) {
  await ensureSession();
  const scope = apiScope();
  if (options.body) {
    const result = await apiRequest(path, parameters, options);
    await window.PantherUI.invalidate(scope, mutationReadPaths(path), options.body.gameId);
    return result;
  }
  const sensitive = /(?:live|transcriptions|transcript-summaries|jobs|asset-generation|workflows|object-url|image-links)/.test(path);
  const sortedParameters = Object.fromEntries(Object.entries(parameters).sort(([a], [b]) => a.localeCompare(b)));
  return window.PantherUI.query({ scope, path, parameters: sortedParameters,
    staleTime: sensitive ? 0 : 60_000, fetcher: () => apiRequest(path, parameters, options) });
}

let foregroundRefresh = null;
function foregroundBlocked() {
  if (!state.tokens || !state.gameId || location.pathname.startsWith("/account") || document.visibilityState === "hidden") return true;
  if (roomCapture?.recording || roomCapture?.stopping || roomCapture?.archiving || elements.previewDialog.open) return true;
  if (document.activeElement?.matches("input, textarea, select, [contenteditable=true]")) return true;
  return [...document.querySelectorAll("form[data-dirty=true]")].some(form => form.getClientRects().length > 0);
}
function foregroundPreservesView(section) {
  const host = ["media","assets"].includes(section) ? elements.explorer : section === "novel" ? elements.novel : document.getElementById("session-library");
  if (["media","assets"].includes(section) && !elements.entries.hidden && mediaListing.loadedPages > 1) return true;
  if(section==='assets'&&elements.entries.hidden&&(assetListing.pages>1||host.querySelector('.assets-filter[aria-pressed=true]:not(:first-child)')))return true;
  if (["sessions", "videos"].includes(section) && host.dataset.paged === "true") return true;
  const visible = element => element.getClientRects().length > 0;
  if ([...host.querySelectorAll('input[type="search"]')].some(input => visible(input) && input.value.trim())) return true;
  if ([...host.querySelectorAll("select")].some(select => visible(select) && select.options.length && select.value !== select.options[0].value)) return true;
  return [...document.querySelectorAll("audio, video")].some(player => visible(player) && (!player.paused || player.currentTime > 0));
}
async function revalidateForeground() {
  if (foregroundRefresh || foregroundBlocked()) return;
  const section = elements.primaryNav.querySelector("[aria-current]")?.dataset.section;
  if (!section || (section === "novel" && !novel.reader.hidden)) return;
  const gameId = state.gameId, epoch = routeEpoch, scope = apiScope();
  const paths = ["/games", "/game"], filters = {};
  if (section === "dashboard") paths.push("/dashboard-recent");
  if (["media","assets"].includes(section) && !elements.entries.hidden) {paths.push("/objects");filters["/objects"] = {prefix:state.currentPrefix};}
  if (section === "assets" && elements.entries.hidden) {paths.push("/assets");filters["/assets"] = {section:"all"};}
  if (section === "characters") {
    if (!elements.characterProfile.hidden && state.currentCharacter) {
      paths.push("/character-details", "/character-details/history");
      for (const path of paths.slice(2)) filters[path] = {characterId:state.currentCharacter.characterId};
    } else paths.push("/characters");
  }
  if (section === "novel") paths.push("/novel", "/novel-stories", "/novel-books");
  if (["sessions", "videos"].includes(section)) {
    paths.push("/assets"); filters["/assets"] = {section};
    if (section === "videos") paths.push("/video-collections", "/episodes", "/scenes", "/episode-composition");
  }
  foregroundRefresh = (async () => {
    const changed = await window.PantherUI.revalidate({scope, paths, gameId, filters});
    if (!changed.length || epoch !== routeEpoch || gameId !== state.gameId || foregroundBlocked()) return;
    const game = changed.find(item => item.path === "/game");
    if (game) applyGameDetail(game.data);
    const games = changed.find(item => item.path === "/games");
    if (games) {
      state.games = games.data.games;
      elements.gameSelector.replaceChildren(...state.games.map(game => new Option(game.name, game.id)));
      elements.gameSelector.value = gameId; window.PantherUI.syncGameSelector();
    }
    if (foregroundPreservesView(section)) {
      if (section === "media") state.mediaLoaded = false;
      return;
    }
    document.dispatchEvent(new CustomEvent("panther-data-updated", {detail:{gameId,section,paths:changed.map(item=>item.path)}}));
    if (["media","assets"].includes(section)&&!elements.entries.hidden) await loadPrefix(state.currentPrefix);
    else if(section === "assets") await loadAssetLibrary(epoch);
    else if (section === "dashboard") {renderDashboard();await loadDashboardRecent(epoch);}
    else if (section === "characters") {
      if (!elements.characterProfile.hidden && state.currentCharacter) await loadCharacterFacts(state.currentCharacter.gameId, state.currentCharacter.characterId, epoch);
      else await loadCharacters();
    } else if (section === "novel") await loadNovel(null, epoch);
    else if (["sessions", "videos"].includes(section)) await loadLibrary(section, epoch);
  })().catch(() => { /* Retain visible content through a temporary refresh failure. */ }).finally(() => {foregroundRefresh = null;});
  return foregroundRefresh;
}
window.addEventListener("focus", () => {void revalidateForeground();});
document.addEventListener("visibilitychange", () => {if (document.visibilityState === "visible") void revalidateForeground();});
document.addEventListener("input", event => {const form = event.target.closest?.("form");if (form) form.dataset.dirty = "true";}, true);

function showWelcome(message = "") {
  closeAccountSettings();
  document.getElementById("page-loading").hidden = true;
  clearLibrary();
  elements.gameToolbar.hidden = true;
  elements.welcome.hidden = false;
  elements.explorer.hidden = true;
  elements.characters.hidden = true;
  elements.novel.hidden = true;
  document.getElementById("dashboard").hidden = true;
  document.getElementById("game-settings").hidden = true;
  workshop.stop();
  document.getElementById("workshop").hidden = true;
  document.getElementById("game-context").hidden = true;
  elements.account.hidden = true;
  elements.primaryNav.hidden = true;
  elements.authError.textContent = message;
  elements.authError.hidden = !message;
}

function showApplicationChrome() {
  const claims = decodeToken(state.tokens.id_token);
  elements.username.textContent = claims["cognito:username"] || claims.username || "Signed in";
  elements.welcome.hidden = true;
  elements.account.hidden = false;
  elements.primaryNav.hidden = false;
}

function setActiveNavigation(section) {
  for (const link of elements.primaryNav.querySelectorAll("a")) {
    const part = link.dataset.section || link.getAttribute("href").split("/").at(-1);
    link.dataset.section = part;
    link.href = gamePath(part);
    const active = part === section;
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  drawLive();
}

function folderName(prefix) {
  const parts = prefix.split("/").filter(Boolean);
  return parts.at(-1) || "games";
}

function renderBreadcrumbs(prefix) {
  elements.breadcrumbs.replaceChildren();
  const segments = prefix.split("/").filter(Boolean);
  let accumulated = "";
  for (const segment of segments) {
    accumulated += `${segment}/`;
    if (accumulated === "games/") continue;
    const destination = accumulated;
    const current = accumulated === segments.join("/") + "/";
    const button = document.createElement(current ? "span" : "button");
    button.className = "crumb";
    if(current)button.setAttribute("aria-current","page");else button.type = "button";
    button.textContent = accumulated === `games/${state.gameId}/` ? state.gameDetail?.game.name || segment : segment;
    if(!current)button.addEventListener("click", () => loadPrefix(destination));
    elements.breadcrumbs.append(button);
  }
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const amount = bytes / 1024 ** unit;
  return `${amount.toFixed(unit === 0 || amount >= 10 ? 0 : 1)} ${units[unit]}`;
}

function webGlAvailable() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function characterPath(character) {
  return `/games/${encodeURIComponent(character.gameId)}/characters/${encodeURIComponent(character.id)}`;
}

function gamePath(section) {
  return state.gameId ? `/games/${encodeURIComponent(state.gameId)}/${section}` : `/${section}`;
}

async function selectGame(requested, epoch) {
  if (!state.games) {
    showLoading(document.getElementById("page-loading"), "Fetching your games…");
    const result = await api("/games");
    if (epoch !== routeEpoch) return false;
    state.games = result.games;
    elements.gameSelector.replaceChildren();
    for (const game of state.games) {
      const option = document.createElement("option");
      option.value = game.id;
      option.textContent = game.name;
      elements.gameSelector.append(option);
    }
  }
  let remembered = null;
  try { remembered = sessionStorage.getItem("panther.game"); } catch { /* Optional preference. */ }
  const selected = requested || state.gameId || remembered || state.games[0]?.id;
  if ((roomCapture?.recording || roomCapture?.stopping || roomCapture?.archiving) && selected !== roomCapture.draft.gameId) throw new Error("Finish saving the room recording before switching games.");
  if (!state.games.some(g => g.id === selected)) throw new Error("Game not found. Choose an available game.");
  elements.gameToolbar.hidden = false;
  document.getElementById("game-context").hidden = false;
  if (selected !== state.gameId) {
    resetLive();
    state.gameId = selected;
    state.gameDetail = null;
    state.charactersLoaded = false;
    state.mediaLoaded = false;
    state.currentCharacter = null;
    state.currentPrefix = `games/${selected}/`;
    listingEpoch += 1;
    window.PantherUI.unmountMediaBrowser(elements.entries);
    elements.entries.replaceChildren();
    elements.characterList.replaceChildren();
    elements.characterProfile.hidden = true;
    elements.playerRoster.replaceChildren();
    elements.gameRuleset.textContent = "";
    document.getElementById("game-style").hidden = true;
    elements.characterModel.src = null;
    elements.characterModel.removeAttribute("src");
    closePreview();
  }
  elements.gameSelector.value = selected;
  window.PantherUI.syncGameSelector();
  elements.gamePurpose.textContent = state.games.find(g => g.id === selected).purpose === "test" ? "Test game · separate from campaign material" : "";
  if (!state.gameDetail) {
    showLoading(document.getElementById("page-loading"), "Fetching the selected game and player roster…");
    const detail = await api("/game", { gameId: selected });
    if (epoch !== routeEpoch || state.gameId !== selected) return false;
    state.gameDetail = detail;

  }
  try { sessionStorage.setItem("panther.game", selected); } catch { /* Optional preference. */ }
  elements.gameRuleset.textContent = state.gameDetail.game.ruleset ? `System: ${state.gameDetail.game.ruleset}` : "System not set";
  const reviewEntry = document.getElementById("storyboard-entry");
  reviewEntry.href = `${gamePath("videos")}?review=1`;
  reviewEntry.onclick = event => {if(event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)return;event.preventDefault();navigate(reviewEntry.href);};
  renderGameStyle();
  if (liveGame !== selected) { liveGame = selected; void refreshLive(); }
  return true;
}

function gameLink(link, section) {
  link.href = gamePath(section);
  link.onclick = event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(link.getAttribute("href"));
  };
}

function navigationArrow() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.classList.add("navigation-arrow");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path"); path.setAttribute("d", "M5 19 19 5M5 5h14v14"); svg.append(path); return svg;
}

function renderDashboard() {
  const {game} = state.gameDetail;
  document.getElementById("dashboard-name").textContent = game.name;
  document.getElementById("dashboard-description").textContent = state.gameDetail.gameSettings?.description || "";
  for (const selector of ['#dashboard-purpose','#dashboard-facts','.dashboard-open','#dashboard .dashboard-section-heading','#dashboard .dashboard-bottom','#dashboard-recent']) {
    document.querySelector(selector)?.setAttribute('hidden','');
  }
  const cards = document.getElementById("dashboard-sections");for(const icon of cards.querySelectorAll("[data-dashboard-icon]"))window.PantherUI.unmountIcon?.(icon);cards.replaceChildren();
  for (const [section,label] of [["characters","Characters"],["sessions","Sessions"],["novel","Novel"],["videos","Videos"],["assets","Assets"]]) {
    const card=document.createElement('section');card.className='dashboard-card';card.dataset.section=section;
    const icon=document.createElement('span'),arrow=document.createElement('span');icon.className='dashboard-section-icon';arrow.className='dashboard-card-arrow';icon.dataset.dashboardIcon=section;arrow.dataset.dashboardIcon='arrow';icon.setAttribute('aria-hidden','true');arrow.setAttribute('aria-hidden','true');card.append(icon,arrow);window.PantherUI.mountIcon(icon,section);window.PantherUI.mountIcon(arrow,'arrow');
    const title=document.createElement('h2'),link=document.createElement('a');gameLink(link,section);link.textContent=label;link.className='dashboard-card-link';title.append(link);
    const list=document.createElement('ul');list.className='dashboard-recent-links';list.setAttribute('aria-label',`Recent ${label.toLowerCase()}`);card.append(title,list);cards.append(card);
  }
  renderWorkspaceHome();
  void loadApprovalInbox(document.getElementById("approval-inbox"), routeEpoch);
}

// Each workspace has its own information architecture; shared editors remain mounted.
// These home projections copy navigation links, not media players or mutable forms.
function renderWorkspaceHome() {
  const host=document.getElementById('workspace-home');if(!host)return;
  const design=document.documentElement.dataset.interface;
  const source=document.getElementById('dashboard-sections');host.replaceChildren();
  source.hidden=design!=='studio';host.hidden=design==='studio';if(host.hidden)return;
  host.dataset.layout=design;
  const collections=[['characters','The cast'],['sessions','Session records'],['novel','The novel'],['videos','Screening room'],['assets','The archive']];
  const copyLinks=(section,destination)=>{
    const links=source.querySelector(`[data-section="${section}"] ul`);
    const list=document.createElement('ul');list.className='workspace-recent';
    for(const row of links?.children||[]){const original=row.querySelector('a');if(!original)continue;const li=document.createElement('li'),a=document.createElement('a');a.href=original.href;a.textContent=original.textContent;a.onclick=event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();original.click();};li.append(a);list.append(li);}
    if(!list.children.length)list.append(movieNode('li','No recent entries. Open the collection to browse.'));
    destination.append(list);
  };
  const collection=(section,title,index)=>{
    const card=movieNode('article',undefined,'workspace-collection');card.dataset.collection=section;
    card.append(movieNode('span',String(index+1).padStart(2,'0'),'workspace-number'),movieNode('h3',title));copyLinks(section,card);
    const link=movieNode('a',`Open ${title.toLowerCase()} →`);gameLink(link,section);card.append(link);return card;
  };
  if(design==='field'){
    host.append(movieNode('h2','Explore your world'));
    const search=movieNode('input');search.type='search';search.placeholder='Search recent entries and collections';search.setAttribute('aria-label','Find a collection');
    const explorer=movieNode('div',undefined,'workspace-explorer'),directory=movieNode('section',undefined,'workspace-directory'),inspector=movieNode('aside',undefined,'workspace-inspector');inspector.setAttribute('aria-label','Entry inspector');
    const table=movieNode('table'),head=movieNode('thead'),heading=movieNode('tr');for(const title of ['Collection','Recent entry'])heading.append(movieNode('th',title));head.append(heading);const body=movieNode('tbody');table.append(head,body);directory.append(search,table);
    for(const [number,[section,title]]of collections.entries()){
      const originals=[...source.querySelectorAll(`[data-section="${section}"] ul a`)];
      for(const original of originals.length?originals:[null]){
        const row=movieNode('tr'),name=original?.textContent||'Browse collection',button=movieButton(name,()=>{for(const item of body.querySelectorAll('button'))item.setAttribute('aria-pressed',String(item===button));inspector.replaceChildren(movieNode('p','SELECTED ENTRY','eyebrow'),movieNode('h3',name),movieNode('p',title));const open=movieNode('a','Open selected entry →','primary-button');if(original){open.href=original.href;open.onclick=event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();original.click();};}else gameLink(open,section);inspector.append(open);});
        button.dataset.collection=section;const cell=movieNode('td');cell.append(button);row.append(movieNode('td',title),cell);row.dataset.search=`${title} ${name}`.toLowerCase();body.append(row);
      }
    }
    search.oninput=()=>{for(const row of body.children)row.hidden=!row.dataset.search.includes(search.value.toLowerCase());};explorer.append(directory,inspector);host.append(explorer);body.querySelector('button')?.click();
  }else if(design==='chronicle'){
    const book=movieNode('div',undefined,'workspace-split'),index=movieNode('nav',undefined,'workspace-index'),page=movieNode('article',undefined,'workspace-page');index.setAttribute('aria-label',design==='chronicle'?'Book contents':'Collection directory');
    const search=movieNode('input');search.type='search';search.placeholder='Find a collection';search.setAttribute('aria-label','Find a collection');if(design==='field')index.append(search);
    function select(section,title,number){for(const button of index.querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.collection===section));page.replaceChildren(movieNode('p',design==='chronicle'?`CHAPTER ${number+1}`:'COLLECTION','eyebrow'),collection(section,title,number));}
    for(const [number,[section,title]]of collections.entries()){const button=movieButton(`${number+1}. ${title}`,()=>select(section,title,number));button.dataset.collection=section;index.append(button);}
    search.oninput=()=>{for(const button of index.querySelectorAll('button'))button.hidden=!button.textContent.toLowerCase().includes(search.value.toLowerCase());};
    book.append(index,page);host.append(movieNode('h2',design==='chronicle'?'Your campaign, bound together':'Explore your world'),book);select(...collections[design==='chronicle'?2:0],design==='chronicle'?2:0);
  }else if(design==='mission'){
    host.append(movieNode('h2','From the table to the screen'));
    const board=movieNode('div',undefined,'workspace-kanban');
    for(const [name,sections]of [['01 / SOURCE',['sessions','characters']],['02 / MAKE',['novel','workflows']],['03 / WATCH',['videos','assets']]]){const lane=movieNode('section',undefined,'workspace-lane');lane.append(movieNode('h3',name));for(const section of sections){const title=collections.find(c=>c[0]===section)?.[1]||'Workflow progress';lane.append(collection(section,title,collections.findIndex(c=>c[0]===section)));}board.append(lane);}host.append(board);
  }else if(design==='cinema'){
    const feature=movieNode('section',undefined,'workspace-feature');feature.append(movieNode('p','YOUR PRIVATE PREMIERE','eyebrow'),movieNode('h2','Stories worth pressing play for.'),movieNode('p','Watch finished episodes, or step behind the screen to review the next one.'));const link=movieNode('a','Enter the screening room →','primary-button');gameLink(link,'videos');feature.append(link);host.append(feature);
    for(const [number,[section,title]]of [...collections.entries()].sort((a,b)=>(a[1][0]==='videos'?-1:b[1][0]==='videos'?1:0))){const shelf=collection(section,title,number);shelf.classList.add('workspace-shelf');host.append(shelf);}
  }else{
    host.append(movieNode('h2','A world of connected stories'));
    const board=movieNode('div',undefined,'workspace-pinboard');for(const [number,[section,title]]of collections.entries())board.append(collection(section,title,number));host.append(board);
  }
}
document.addEventListener('panther-interface-changed',()=>renderWorkspaceHome());

async function loadApprovalInbox(host,epoch,cursor=null,append=false) {
  const gameId=state.gameId,current=()=>epoch===routeEpoch&&gameId===state.gameId&&host.isConnected;
  if(!append){host.replaceChildren(movieNode('h2','Review & approve storyboards'),movieNode('p','Choose a session below. Review the shots and script, then approve its exact plan and budget. Approval never silently starts a paid request.'));}
  const status=movieNode('p','Finding prepared storyboards…');status.setAttribute('role','status');host.append(status);
  try{
    const result=await api('/assets',{gameId,section:'videos',cursor});if(!current())return;
    if(!Array.isArray(result.assets))throw new Error('Storyboard catalog unavailable');
    let count=0;const checks=[];
    for(const asset of result.assets.filter(a=>a.kind==='movie-review-plan'&&sameGameKey(a.key)).sort((a,b)=>String(b.lastModified||'').localeCompare(String(a.lastModified||'')))){count++;const card=movieNode('article',undefined,'approval-card');card.append(movieNode('p',asset.metadata?.sessionId?`SESSION / ${asset.metadata.sessionId}`:'PREPARED MOVIE PLAN','eyebrow'),movieNode('h3',asset.metadata?.title||asset.name));
      const link=movieNode('a','Review storyboard & approve →','primary-button');link.href=`${gamePath('videos')}?project=${encodeURIComponent(asset.key)}`;link.onclick=event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();navigate(link.href);};
      const readiness=movieNode('p','Checking this plan’s review status…','approval-readiness');readiness.setAttribute('role','status');card.append(link,readiness);host.append(card);
      checks.push(async()=>{try{const data=await api('/movie-review',{gameId,key:asset.key});if(!current()||!card.isConnected)return;
        readiness.textContent=data.review?.action==='approved'?'This revision is already approved.':data.readiness?.ready?'Ready for your shot-by-shot review and approval.':Array.isArray(data.readiness?.blockers)&&data.readiness.blockers.length?`Preparation needs attention: ${data.readiness.blockers[0]}`:'Open this plan to check its preparation and approval requirements.';
        if(data.review?.action==='approved')link.textContent='View approved storyboard →';
      }catch{if(current()&&card.isConnected)readiness.textContent='Review status unavailable. Open the plan to retry; no approval has been assumed.';}});
    }
    status.textContent=count?'Approval is available inside each plan after every shot is reviewed and its checks pass.':result.cursor?'No prepared storyboards on this catalog page. More entries are available below.':'No prepared storyboards on this page. If your session is still being prepared, check its workflow.';
    if(result.cursor){const more=movieButton('Find more storyboards',()=>{more.remove();void loadApprovalInbox(host,epoch,result.cursor,true);});host.append(more);}
    if(!append){const workflow=movieNode('a','Check session preparation in Workflows →');gameLink(workflow,'workflows');host.append(workflow);}
    // Bound detail reads; never fan out an entire game or scan source storage.
    await Promise.all(Array.from({length:Math.min(4,checks.length)},async()=>{while(checks.length&&current())await checks.shift()();}));
  }catch(error){if(current()){status.textContent=`Could not load storyboard reviews: ${error.message}`;host.append(movieButton('Retry storyboard list',()=>void loadApprovalInbox(host,epoch)));}}
}

async function loadDashboardRecent(epoch) {
  const gameId=state.gameId;
  try {
    const result=await api('/dashboard-recent',{gameId});
    if(epoch!==routeEpoch||gameId!==state.gameId)return;
    if(result.complete!==true||!result.groups)throw new Error('Recent activity unavailable');
    for(const [section,key] of [['characters','characters'],['sessions','transcripts'],['novel','chapters'],['videos','videos'],['assets','assets']]) {
      const card=document.querySelector(`#dashboard-sections [data-section="${section}"]`),list=card.querySelector('ul');list.replaceChildren();
      const items=Array.isArray(result.groups[key])?result.groups[key]:[];
      for(const item of items.slice(0,5)) {
        const row=document.createElement('li');let link;
        if(section==='characters'){link=document.createElement('a');link.href=characterPath({...item,gameId});link.textContent=item.name;link.onclick=event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();navigate(link.pathname);};}
        else if(section==='novel')link=novelLink(item.title,item.id);
        else link=assetLink(item,item.metadata?.title||item.title||item.name);
        row.append(link);list.append(row);
      }
      const count=result.counts?.[key];
      if(Number.isInteger(count)&&count>items.slice(0,5).length){const row=document.createElement('li'),link=document.createElement('a');gameLink(link,section);link.textContent=`+ ${count-items.slice(0,5).length} more`;row.append(link);list.append(row);}
    }
    renderWorkspaceHome();
  }catch(error){if(epoch===routeEpoch&&gameId===state.gameId){const host=document.getElementById('dashboard-recent');host.hidden=false;host.textContent=error.message;}}
}

function applyGameDetail(detail) {
  state.gameDetail = detail;
  const entry = state.games.find(g => g.id === state.gameId); if (entry) Object.assign(entry, detail.game);
  const option = Array.from(elements.gameSelector.options).find(o => o.value === state.gameId);
  if (option) option.textContent = detail.game.name;
  elements.gameRuleset.textContent = detail.game.ruleset ? `System: ${detail.game.ruleset}` : "System not set";
}

function renderGameSettings() {
  const detail = state.gameDetail, gameId = state.gameId, epoch = routeEpoch, canEdit = detail.canEditGame === true;
  const form = document.getElementById("game-settings-form"), status = document.getElementById("game-settings-status"), button = form.querySelector("button");
  form.dataset.dirty = "false";
  const fields = {name: document.getElementById("game-name"), description: document.getElementById("game-description"), ruleset: document.getElementById("game-system")};
  fields.name.value = detail.game.name; fields.description.value = detail.gameSettings?.description || ""; fields.ruleset.value = detail.game.ruleset || "";
  for (const field of Object.values(fields)) field.readOnly = !canEdit;
  button.disabled = !canEdit; status.textContent = ""; delete status.dataset.state;
  const notice = document.getElementById("game-settings-access"); notice.hidden = canEdit;
  notice.textContent = "You can view this game’s settings. A publisher can edit game details and generation defaults.";
  let pending = null;
  form.onsubmit = async event => {
    event.preventDefault(); if (!canEdit || button.disabled) return;
    const edits = {name: fields.name.value.trim(), description: fields.description.value.trim() || null, ruleset: fields.ruleset.value.trim() || null};
    if (!pending || JSON.stringify(pending.edits) !== JSON.stringify(edits)) pending = {edits, operationId: crypto.randomUUID()};
    button.disabled = true; button.textContent = "Saving…"; status.textContent = "Saving game details…"; delete status.dataset.state;
    try {
      const updated = await api("/game/settings", {}, {body: {gameId, ...edits, expectedName: detail.game.name, expectedRuleset: detail.game.ruleset || null, expectedDescriptionRevision: detail.gameSettings?.descriptionRevision || null, operationId: pending.operationId}});
      if (state.gameId !== gameId || routeEpoch !== epoch) return;
      applyGameDetail(updated); renderGameSettings(); status.textContent = "Game details saved.";
    } catch (error) {
      if (state.gameId !== gameId || routeEpoch !== epoch) return;
      status.textContent = error.status === 409 ? "Someone changed these settings. Reload the page to review the latest values before saving." : `Could not save. ${error.message} You can retry this save.`;
      status.dataset.state = "error";
    } finally {
      if (state.gameId === gameId && routeEpoch === epoch) { button.disabled = !canEdit; button.textContent = "Save game details"; }
    }
  };
  renderGameStyle();
}

function renderGameStyle() {
  const panel=document.getElementById("game-style"),form=document.getElementById("game-style-form"),select=document.getElementById("visual-style"),status=document.getElementById("style-status"),detail=state.gameDetail;
  panel.hidden=!detail?.visualStyles?.length;if(panel.hidden)return;
  const gameId=state.gameId,expectedStyle=detail.game.visualStyle??null,canEdit=detail.canEditGame===true;
  form.dataset.dirty="false";select.replaceChildren();select.hidden=true;
  document.getElementById("visual-style-cards")?.remove();
  const grid=document.createElement("div");grid.id="visual-style-cards";grid.className="visual-style-cards";grid.setAttribute("role","group");grid.setAttribute("aria-label","Visual style");
  for(const style of detail.visualStyles){
    select.add(new Option(style.label,style.id));
    const card=document.createElement("article");card.className="visual-style-card";card.dataset.style=style.id;card.dataset.selected=String(style.id===expectedStyle);
    const title=document.createElement("h3");title.textContent=style.label;
    const controls=document.createElement("div");controls.className="visual-style-actions";
    const chosen=style.id===expectedStyle,choose=document.createElement("button");choose.type="button";choose.className=chosen?"quiet-button":"primary-button";choose.textContent=chosen?"Selected":"Select";choose.setAttribute("aria-label",`${chosen?"Selected":"Select"} ${style.label}`);choose.disabled=!canEdit||chosen;
    const preview=style.previewImage===`/style-previews/${style.id}.webp`?style.previewImage:null;
    if(preview){const image=document.createElement("img");image.src=preview;image.alt=`${style.label} preview`;image.loading="lazy";card.append(image);const zoom=document.createElement("button");zoom.type="button";zoom.className="icon-button";zoom.title="Zoom";zoom.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/></svg>';zoom.setAttribute("aria-label",`Zoom ${style.label}`);zoom.onclick=()=>{const dialog=document.getElementById("style-preview-dialog");document.getElementById("style-preview-title").textContent=style.label;const large=document.getElementById("style-preview-image");large.src=preview;large.alt=image.alt;dialog.showModal();document.getElementById("style-preview-close").onclick=()=>{dialog.close();zoom.focus();};};controls.append(zoom);image.onerror=()=>{image.remove();zoom.remove();};}
    controls.append(choose);card.append(title,controls);grid.append(card);
    choose.onclick=async()=>{
      const epoch=routeEpoch;for(const button of grid.querySelectorAll("button"))button.disabled=true;status.textContent="Saving style…";
      try{const updated=await api("/game/style",{},{body:{gameId,visualStyle:style.id,expectedStyle}});if(state.gameId!==gameId||routeEpoch!==epoch)return;state.gameDetail=updated;renderGameStyle();status.textContent="Style saved.";}
      catch(error){if(state.gameId!==gameId||routeEpoch!==epoch)return;status.textContent=`Could not save style. ${error.message}`;for(const button of grid.querySelectorAll("button"))button.disabled=false;for(const selected of grid.querySelectorAll('[data-selected="true"] button[aria-label^="Selected"]'))selected.disabled=true;}
    };
  }
  select.value=expectedStyle||"";select.disabled=!canEdit;form.prepend(grid);status.textContent="";form.onsubmit=event=>event.preventDefault();
}


function navigate(path, { replace = false } = {}) {
  if (replace) window.history.replaceState({}, "", path);
  else window.history.pushState({}, "", path);
  renderRoute();
}

function renderCharacterCard(character) {
  const button = document.createElement("button");
  button.className = "character-card";
  button.type = "button";

  const marker = document.createElement("span");
  marker.className = "character-monogram";
  marker.textContent = character.name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2);
  marker.setAttribute("aria-hidden", "true");
  if (character.detailsThumbnailKey) marker.dataset.imageKey = character.detailsThumbnailKey;

  const copy = document.createElement("span");
  const name = document.createElement("strong");
  name.textContent = character.name;
  const title = document.createElement("small");
  title.textContent = character.detailsSubtitle || character.title || "Character";
  const member = state.gameDetail?.memberships?.find(m => m.characterIds.includes(character.id));
  const player = state.gameDetail?.players?.find(p => p.id === member?.playerId);
  copy.append(name, title);
  if (player) { const credit = document.createElement("small"); credit.className = "character-player"; credit.textContent = `Played by ${player.name}`; copy.append(credit); }

  const arrow = document.createElement("span");
  arrow.className = "entry-arrow";
  arrow.textContent = "View character";
  button.append(marker, copy, arrow);
  button.addEventListener("click", () => navigate(characterPath(character)));
  elements.characterList.append(button);
}

async function loadCharacters() {
  const epoch = routeEpoch;
  elements.characterProfile.hidden = true;
  document.getElementById("character-create").hidden = false;
  elements.characterList.hidden = false;
  elements.charactersStatus.hidden = false;
  showLoading(elements.charactersStatus, "Fetching character profiles…");
  try {
    const result = await api("/characters", { gameId: state.gameId });
    if (epoch !== routeEpoch) return;
    elements.characterList.replaceChildren();
    // Registered catalog records only; a page never scans source profiles in S3.
    for (const c of result.characters) if (c.gameId === state.gameId) renderCharacterCard(c);
    void loadCharacterThumbnails(epoch);
    const more = document.getElementById("characters-more");
    const seen = new Set();
    let cursor = result.cursor;
    more.hidden = !cursor;
    more.onclick = async () => {
      more.disabled = true;
      try {
        if (seen.has(cursor)) throw new Error("Repeated cursor; character list is incomplete.");
        const page = await api("/characters", {gameId: state.gameId, cursor});
        if (epoch !== routeEpoch) return;
        seen.add(cursor);
        for (const c of page.characters) if (c.gameId === state.gameId) renderCharacterCard(c);
        void loadCharacterThumbnails(epoch);
        cursor = page.cursor; more.hidden = !cursor;
        elements.charactersStatus.hidden = false;
        elements.charactersStatus.textContent = cursor ? "More characters are available below." : "All characters loaded.";
      } catch (error) { if (epoch === routeEpoch) { elements.charactersStatus.hidden = false; elements.charactersStatus.textContent = error.message; } }
      finally { more.disabled = false; }
    };
    state.charactersLoaded = true;
    elements.charactersStatus.hidden = !cursor;
    if (cursor) elements.charactersStatus.textContent = "More characters are available below.";
    if (!result.characters.length && !cursor) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "There are no character profiles yet.";
      elements.characterList.append(empty);
    }
  } catch (error) {
    if (epoch !== routeEpoch) return;
    if (error.message !== "Session expired") {
      elements.charactersStatus.textContent = error.message;
    }
  }
}

async function createCharacter() {
  const host = document.getElementById("character-create-form");
  if (!host.hidden) return;
  host.hidden = false;
  const name = host.querySelector("input"), status = host.querySelector("[role=status]");
  name.value = ""; name.disabled = false; name.focus();
  let pending = null;
  host.onsubmit = async event => {
    event.preventDefault();
    const button = host.querySelector("button[type=submit]"); button.disabled = true;
    const gameId = state.gameId;
    const id = pending?.id || `${name.value.trim().toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,48) || "character"}-${crypto.randomUUID().slice(0,8)}`;
    try {
      pending ||= {gameId,id,name:name.value.trim()};
      name.disabled = true;
      await api("/game/characters", {}, {body:pending});
      if (gameId !== state.gameId) return;
      state.gameDetail.characters.push({id,gameId,name:name.value.trim()});
      host.hidden = true;
      navigate(characterPath({id,gameId}));
    } catch(error) {status.textContent = error.message; if(error.status === 400 || error.status === 409) {pending = null;name.disabled = false;} else button.textContent = "Retry create";}
    finally {button.disabled = false;}
  };
  host.querySelector("button[type=button]").onclick = () => {host.hidden = true;};
}

async function loadCharacterThumbnails(epoch) {
  const hosts = [...elements.characterList.querySelectorAll("[data-image-key]:not([data-requested])")];
  for (const host of hosts) host.dataset.requested = "true";
  for (let offset=0; offset<hosts.length; offset+=60) {
    const batch = hosts.slice(offset,offset+60), keys = [...new Set(batch.map(h=>h.dataset.imageKey))];
    try {
      const links = await api("/image-links",{}, {body:{gameId:state.gameId,keys}});
      if (epoch !== routeEpoch) return;
      for (const host of batch) if (links.images?.[host.dataset.imageKey]?.url && host.isConnected) {
        const image = document.createElement("img"); image.alt = ""; image.src = links.images[host.dataset.imageKey].url;
        image.onerror = () => {image.remove(); delete host.dataset.requested;}; host.append(image);
      }
    } catch { for (const host of batch) delete host.dataset.requested; }
  }
}

function showModelFallback(message) {
  resetModelAnimation();
  elements.characterModel.hidden = true;
  elements.modelFallback.hidden = false;
  elements.modelFallbackMessage.textContent = message;
  elements.modelStatus.textContent = message;
  elements.modelReset.disabled = true;
  setModelControls(false);
}

function setModelControls(enabled) {
  for (const id of ["model-pan-up", "model-pan-left", "model-pan-down", "model-pan-right", "model-zoom-in", "model-zoom-out"]) {
    document.getElementById(id).disabled = !enabled;
  }
}

function loadProfilePortrait(record,epoch=routeEpoch) {
  if(!record?.details?.thumbnailAssetKey||new URLSearchParams(location.search).has("appearance")||new URLSearchParams(location.search).has("selection"))return;
  const key=record.details.thumbnailAssetKey,gameId=record.gameId,characterId=record.characterId;
  void api("/image-links",{},{body:{gameId,keys:[key]}}).then(result=>{
    if(epoch!==routeEpoch||state.gameId!==gameId||state.currentCharacter?.characterId!==characterId)return;
    const url=result.images?.[key]?.url;
    if(!url)return;
    const portrait=document.getElementById("character-portrait-only");portrait.src=url;portrait.alt=`Portrait of ${record.name}`;portrait.hidden=false;document.getElementById("character-portrait-empty").hidden=true;
  }).catch(()=>{});
}

function configureCharacter(profile) {
  resetModelAnimation();
  const { character, model, poster } = profile;
  state.selectedAppearance = profile;
  state.currentCharacter = { gameId: character.gameId, characterId: character.id };
  elements.characterName.textContent = character.name;
  const facts = state.currentCharacterFacts;
  elements.characterTitle.textContent = `Class / role · ${facts?.gameId === character.gameId && facts?.characterId === character.id ? facts.details.role || "—" : "—"}`;
  elements.characterSummary.textContent = "";
  document.querySelector("#character-model-area").hidden = !model;
  document.getElementById("character-artwork-empty").hidden=Boolean(model||poster);
  document.querySelector("#character-no-model").hidden = true;
  const portraitOnly = document.querySelector("#character-portrait-only");
  portraitOnly.hidden = !poster;
  document.getElementById("character-portrait-empty").hidden = Boolean(poster);
  portraitOnly.removeAttribute("src");
  if (poster) { portraitOnly.src = poster.url; portraitOnly.alt = `Portrait of ${character.name}`; }
  if(facts?.gameId===character.gameId&&facts.characterId===character.id)loadProfilePortrait(facts);
  if (!model) {
    elements.characterModel.src = null;
    elements.characterModel.removeAttribute("src");
    state.selectedModelKey=null;
    setModelControls(false);
    return;
  }
  configureModelView(model, poster, character.name);
}

function configureModelView(model, poster, name, keepActive = false) {
  resetModelAnimation();
  state.selectedModelKey = model.key || null;
  elements.characterPoster.src = poster.url;
  elements.characterPoster.alt = `Portrait of ${name}`;
  elements.fallbackPoster.src = poster.url;
  elements.fallbackPoster.alt = `Portrait of ${name}`;
  elements.characterModel.alt = `Interactive 3D model of ${name}`;
  elements.characterModel.cameraOrbit = model.cameraOrbit;
  elements.characterModel.fieldOfView = model.fieldOfView;
  elements.characterModel.dataset.defaultCameraOrbit = model.cameraOrbit;
  elements.characterModel.dataset.defaultFieldOfView = model.fieldOfView;
  if (!keepActive) {
    elements.characterModel.src = null;
    elements.characterModel.removeAttribute("src");
    if (typeof elements.characterModel.showPoster === "function") elements.characterModel.showPoster();
  }
  elements.characterModel.hidden = false;
  elements.modelFallback.hidden = true;
  elements.modelLoad.disabled = keepActive;
  elements.modelLoad.textContent = keepActive ? "Loading…" : "Explore 3D model";
  elements.modelReset.disabled = true;
  setModelControls(false);
  elements.modelProgressBar.style.transform = "scaleX(0)";
  elements.modelSize.textContent = `${formatBytes(model.size)} · limit ${formatBytes(5 * 1024 * 1024)}`;
  elements.modelSource.textContent =
    model.sourceRetained && model.provenanceRetained
      ? "Original and provenance retained"
      : "Web representation";
  elements.modelStatus.textContent = keepActive ? "Loading model…" : "";
}

let appearanceRequest = 0;
async function loadAppearanceVersions(gameId, characterId, epoch) {
  const status = document.getElementById("appearance-status");
  document.getElementById("appearance-history").hidden = false;
  showLoading(status, "Fetching recorded appearance and artwork editions…");
  try {
    const result = await api("/character-versions", {gameId, characterId});
    if (epoch !== routeEpoch) return;
    if (result.schemaVersion !== 2 || !Array.isArray(result.appearances) || !Array.isArray(result.selections) || !Array.isArray(result.activations))
      throw new Error("Appearance history is not ready");
    // Official history excludes unactivated candidates. Preserve an exact,
    // server-resolved deep-link preview in the controls without inventing an
    // activation event or silently pointing the menu at the current edition.
    const pinned=state.selectedAppearance;
    if (pinned?.character?.gameId===gameId && pinned.character.id===characterId &&
        pinned.selection && pinned.appearance?.id===pinned.selection.appearanceId &&
        !result.selections.some(s=>s.id===pinned.selection.id)) {
      result.selections=[...result.selections,{...pinned.selection,previewOnly:true}];
      if (!result.appearances.some(a=>a.id===pinned.appearance.id))
        result.appearances=[...result.appearances,pinned.appearance];
    }
    state.appearanceVersions = result;
    if (!result.selections.length && !result.appearances.length) {document.getElementById("appearance-history").hidden = true; return result;}
    const states = document.getElementById("appearance-state");
    states.replaceChildren();
    for (const appearance of result.appearances) states.add(new Option(appearance.name, appearance.id));
    const selected = state.selectedAppearance?.selection || result.selections.find(s=>s.id===result.current);
    states.value = selected?.appearanceId || result.appearances[0]?.id || "";
    states.disabled = result.appearances.length < 2 || Boolean(state.pendingAppearanceRestore);
    populateArtworkEditions(selected?.id);
    const legacy = new URLSearchParams(location.search).get("model");
    if (legacy) {
      const matches=result.selections.filter(s=>s.modelKey===legacy);
      if (matches.length!==1) {
        configureCharacter({character:{gameId,id:characterId,name:elements.characterName.textContent},poster:null,model:null});
        renderAppearanceDownloads();
        updateAppearanceStory();
        throw new Error("This model link does not identify one complete portrait/model pair. Choose an artwork edition");
      }
      states.value=matches[0].appearanceId;populateArtworkEditions(matches[0].id);
      await showSelectedArtwork();
    } else {
      status.textContent=result.selections.find(s=>s.id===selected?.id)?.previewOnly
        ? "Previewing an unselected edition. The current official selection is unchanged."
        : "";
      renderAppearanceDownloads();
      updateAppearanceStory();
    }
    return true;
  } catch(error) {
    if (epoch===routeEpoch) status.textContent=`Appearance history unavailable: ${error.message}. Reload the page to try again.`;
    return false;
  }
}

function populateArtworkEditions(preferred) {
  const data=state.appearanceVersions, menu=document.getElementById("model-version");
  const aid=document.getElementById("appearance-state").value;
  const pairs=(data?.selections||[]).filter(s=>s.appearanceId===aid);
  menu.replaceChildren();
  pairs.forEach((pair,index)=>{
    let label=`Retained edition ${index+1}`;
    if(pair.previewOnly) label="Unselected preview edition";
    if(pair.id===data.current) label="Current edition";
    menu.add(new Option(`${label}${pair.modelKey?" · portrait + model":" · portrait only"}`,pair.id));
  });
  if (!pairs.length) menu.add(new Option("No official editions",""));
  menu.value=pairs.some(s=>s.id===preferred) ? preferred : pairs.find(s=>s.id===data?.current)?.id || pairs[0]?.id || "";
  menu.disabled=pairs.length<2 || Boolean(state.pendingAppearanceRestore);
}

function updateAppearanceStory() {
  const selected=state.selectedAppearance, data=state.appearanceVersions;
  const story=selected?.appearance?.story;
  const host=document.getElementById("appearance-story");
  host.textContent=story && Object.values(story).some(v=>v!==null)
    ? `Story timing supplied: ${[story.sessionId,story.eventId,story.date].filter(Boolean).join(" · ")}`
    : "";
  document.getElementById("appearance-restore").disabled=!selected?.selection || selected.selection.id===data?.current || Boolean(state.pendingAppearanceRestore);
}

async function showSelectedArtwork() {
  const cid=state.currentCharacter;
  if (!cid) return;
  const request=++appearanceRequest, epoch=routeEpoch;
  const appearanceId=document.getElementById("appearance-state").value;
  const selectionId=document.getElementById("model-version").value;
  if (!appearanceId || !selectionId) return;
  const status=document.getElementById("appearance-status");
  const wasActive=(elements.characterModel.loaded || elements.modelLoad.disabled) &&
    !elements.characterModel.hidden && Boolean(state.selectedModelKey);
  showLoading(status,"Fetching this exact portrait/model pair…");
  document.getElementById("appearance-restore").disabled=true;
  try {
    const selected=await api("/character",{...cid,appearanceId,selectionId});
    if (request!==appearanceRequest || epoch!==routeEpoch) return;
    if (selected.selection?.id!==selectionId || selected.selection?.appearanceId!==appearanceId) throw new Error("Selected artwork pair does not match");
    configureCharacter(selected);
    if (wasActive && selected.model) {configureModelView(selected.model,selected.poster,selected.character.name,true);void loadCharacterModel();}
    const url=new URL(location.href);url.searchParams.delete("model");
    url.searchParams.set("appearance",appearanceId);url.searchParams.set("selection",selectionId);
    history.replaceState(null,"",url);
    if(selected.warnings?.length) status.textContent="A pinned asset is unavailable. No other edition has been substituted.";
    else if(selectionId===state.appearanceVersions?.current) status.textContent="Viewing the current official artwork pair.";
    else if(state.appearanceVersions?.selections.find(s=>s.id===selectionId)?.previewOnly)
      status.textContent="Previewing an unselected edition. The current official selection is unchanged.";
    else status.textContent="Viewing a retained edition. The current official selection is unchanged.";
    renderAppearanceDownloads();updateAppearanceStory();
  } catch(error) {
    if(request!==appearanceRequest || epoch!==routeEpoch) return;
    state.selectedAppearance=null;
    configureCharacter({character:{gameId:cid.gameId,id:cid.characterId,name:elements.characterName.textContent},poster:null,model:null});
    status.textContent=`Selected edition unavailable: ${error.message}. No replacement was chosen.`;
    renderAppearanceDownloads();
  }
}

function renderAppearanceDownloads() {
  const host=document.getElementById("appearance-downloads"), selected=state.selectedAppearance;
  host.replaceChildren();
  const preview=document.getElementById("portrait-version-preview");
  preview.hidden=!selected?.poster;
  if(selected?.poster) {preview.src=selected.poster.url;preview.alt=`Selected portrait of ${elements.characterName.textContent}`;} else preview.removeAttribute("src");
  for(const [asset,label] of [[selected?.poster,"Download selected portrait"],[selected?.model,"Download selected 3D model (GLB)"]]) {
    if(!asset) continue;
    const button=document.createElement("button"), status=document.createElement("span");
    button.type="button";button.className="quiet-button";button.textContent=label;status.setAttribute("role","status");
    button.onclick=()=>downloadAsset(asset.key,button,status,()=>button.isConnected);
    host.append(button,status);
  }
}

async function restoreSelectedAppearance() {
  const selected=state.selectedAppearance?.selection, data=state.appearanceVersions, cid=state.currentCharacter;
  if(!selected || !data || !cid || selected.id===data.current) return;
  const button=document.getElementById("appearance-restore"), status=document.getElementById("appearance-status"), epoch=routeEpoch;
  const request=state.pendingAppearanceRestore || {...cid,id:"current",appearanceId:selected.appearanceId,selectionId:selected.id,
    expectedRevision:data.activationRevision,operationId:crypto.randomUUID().replaceAll("-",""),
    reason:"Restore an explicitly selected retained artwork pair",story:{sessionId:null,eventId:null,date:null}};
  state.pendingAppearanceRestore=request;button.disabled=true;
  document.getElementById("appearance-state").disabled=true;
  document.getElementById("model-version").disabled=true;
  showLoading(status,"Recording the guarded official selection…");
  try {
    await api("/character-appearance-current",{}, {body:request});
    if(epoch!==routeEpoch) return;
    state.pendingAppearanceRestore=null;
    const refreshed=await loadAppearanceVersions(cid.gameId,cid.characterId,epoch);
    if(!refreshed) {
      status.textContent="The selection operation was confirmed, but current history could not be refreshed. Reload before making another selection.";
      button.disabled=true;return;
    }
    status.textContent=state.appearanceVersions.current===request.selectionId ? "This edition is now current. Earlier selections remain in history." : "The restoration was recorded, but a later current selection has been preserved.";
    button.textContent="Make this edition current";updateAppearanceStory();
  } catch(error) {
    if(epoch!==routeEpoch) return;
    if(error.status===409 || error.status===403) {
      state.pendingAppearanceRestore=null;button.disabled=true;
      document.getElementById("appearance-state").disabled=data.appearances.length<2;
      populateArtworkEditions(selected.id);
      status.textContent=`${error.message}. Refresh and inspect the current selection before a new operation.`;
    }
    else {button.disabled=false;button.textContent="Retry this selection";status.textContent="Could not confirm the selection. Retry the same operation or refresh to inspect; no newer revision will be fetched and overwritten.";}
  }
}

async function loadCharacterFacts(gameId, characterId, epoch) {
  const host = document.getElementById("character-facts");
  const current = () => epoch === routeEpoch && gameId === state.gameId;
  showLoading(host, "Fetching structured character information…");
  try {
    const controller = new AbortController(), timer = setTimeout(()=>controller.abort(),30000);
    let result;
    try {
      try {result = await api("/character-details", {gameId, characterId}, {signal:controller.signal});}
      catch(error) {
        if (error.status !== 400 || !/migration/i.test(error.message)) throw error;
        const prepared = await api("/character-details/migrate", {}, {body:{gameId,characterId,mode:"migrate",details:{},expectedRevision:null,expectedSourceHash:null,operationId:crypto.randomUUID().replaceAll("-",""),reason:"Initialize profile from existing recorded facts",dryRun:true}});
        result = prepared.character ? prepared : await api("/character-details/migrate", {}, {body:prepared.plan});
      }
    }
    finally {clearTimeout(timer);}
    if (!current()) return;
    if (!result.character?.details || !result.character.revision) throw new Error("Character profile is unavailable.");
    const record = result.character;
    state.currentCharacterFacts = record;
    loadProfilePortrait(record,epoch);
    const render = () => {
      if(record.name)elements.characterName.textContent=record.name;
      elements.characterTitle.textContent = `Class / role · ${record.details.role || "—"}`;
      for(const select of host.querySelectorAll("select[data-react-select]"))window.PantherUI.destroySelect?.(select);
      host.replaceChildren();
      const heading = document.createElement("div"); heading.className = "explorer-heading";

      const edit = document.createElement("button"); edit.type = "button"; edit.className = "quiet-button"; edit.textContent = "Edit character information";
      heading.className="profile-edit-action";document.querySelector(".character-bio-heading .profile-edit-action")?.remove();heading.append(edit);document.querySelector(".character-bio-heading").append(heading);
      const facts = document.createElement("dl"); facts.className = "character-fact-grid";
      const membership = state.gameDetail.memberships.filter(m => m.characterIds?.includes(characterId));
      const players = membership.map(m => state.gameDetail.players.find(p => p.id === m.playerId)?.name).filter(Boolean);
      for (const [label, value] of [["Played by", players.join(", ")], ["Status", record.details.status]]) {
        const row = document.createElement("div"), dt = document.createElement("dt"), dd = document.createElement("dd");
        dt.textContent = label; dd.textContent = value || "—"; row.append(dt, dd); facts.append(row);
      }
      host.append(facts);
      for (const [field, label] of [["backstory","Backstory"]]) {
        const h = document.createElement("h3"), p = document.createElement("p"); h.textContent = label; p.textContent = record.details[field] || "—"; p.className = "character-prose"; host.append(h,p);
      }
      {
        const h = document.createElement("h3"); h.textContent = "Statistics"; host.append(h);
        const list = document.createElement("dl"); list.className = "character-fact-grid";
        for (const stat of record.details.statistics) { const row = document.createElement("div"), name = document.createElement("dt"), value = document.createElement("dd");
          name.textContent = stat.name; value.textContent = stat.value === null ? "—" : String(stat.value); row.append(name,value); list.append(row); }
        if(!list.children.length){const unknown=document.createElement("p");unknown.textContent="—";list.append(unknown);}host.append(list);
      }
      if (record.details.relationships.length) {
        const h = document.createElement("h3"), list = document.createElement("ul"),panel=document.createElement("section"),toggle=document.createElement("button"); h.textContent = "Connections";panel.hidden=true;toggle.type="button";toggle.className="quiet-button";toggle.textContent="Connections";toggle.setAttribute("aria-expanded","false");toggle.onclick=()=>{panel.hidden=!panel.hidden;toggle.setAttribute("aria-expanded",String(!panel.hidden));};
        for (const ref of record.details.relationships) {
          const li = document.createElement("li"); li.append(document.createTextNode(`${ref.relation} · `));
          const target = ref.entityType === "Character" ? state.gameDetail.characters.find(c => c.id === ref.id) : ref.entityType === "Player" ? state.gameDetail.players.find(p => p.id === ref.id) : null;
          if (target && ref.entityType === "Character") { const a = document.createElement("a"); a.textContent = target.name; a.href = characterPath({...target, gameId}); li.append(a); }
          else if (ref.entityType === "Asset" && sameGameKey(ref.id)) li.append(assetLink({key:ref.id,name:ref.id.split("/").pop()}));
          else li.append(document.createTextNode(target?.name || "Unavailable connection"));
          list.append(li);
        }
        panel.append(h,list);host.append(toggle,panel);
      }
      edit.onclick = () => editor();
    };
    const editor = () => {
      document.querySelector(".character-bio-heading .profile-edit-action")?.remove();
      for(const select of host.querySelectorAll("select[data-react-select]"))window.PantherUI.destroySelect?.(select);
      host.replaceChildren();
      const form = document.createElement("form"); form.className = "character-edit-form";

      const nameLabel = document.createElement("label"), nameInput = document.createElement("input");
      nameLabel.textContent = "Character name"; nameInput.value = record.name; nameInput.required = true; nameInput.maxLength = 120; nameLabel.append(nameInput); form.append(nameLabel);
      const inputs = {};
      for (const [field,label,max,multi] of [["role","Class / role",120,false],["status","Status",120,false],["backstory","Backstory",8000,true]]) {
        const wrapper = document.createElement("label"), input = document.createElement(multi ? "textarea" : "select");
        wrapper.textContent = label; input.maxLength = max; input.value = field === "aliases" ? record.details.aliases.join("\n") : record.details[field] || "";
        if (!multi) {
          const options=field==="role"?["", "Adventurer", "Fighter", "Rogue", "Ranger", "Wizard", "Cleric", "Bard", "Druid", "Paladin", "NPC"]:["", "Active", "Missing", "Retired", "Deceased"];
          if(input.value&&!options.includes(input.value))options.push(input.value);
          const selected=record.details[field]||"";if(selected&&!options.includes(selected))options.push(selected);
          for(const value of options)input.add(new Option(value||"Not set",value));input.value=selected;
        }
        input.id = `character-edit-${field}`; input.setAttribute("aria-label",label); wrapper.append(input); form.append(wrapper); inputs[field] = input;
      }
      const stats = document.createElement("fieldset"), legend = document.createElement("legend"); legend.textContent = "Statistics"; stats.append(legend);
      const rows = [];
      const addStat = (stat = {group:null,name:"",value:null}) => {
        const row = document.createElement("div"); row.className = "character-stat-editor";
        const controls = {};
        for (const label of ["Name","Value"]) { const wrap = document.createElement("label"); wrap.textContent = label; const input = document.createElement(label === "Type" ? "select" : "input");
          input.setAttribute("aria-label",label);
          if (label === "Type") for (const kind of ["Unknown","Text","Number","Boolean"]) { const option = document.createElement("option"); option.textContent = kind; input.append(option); }
          else input.maxLength = label === "Name" ? 120 : 500;
          wrap.append(input); row.append(wrap); controls[label] = input;
        }
        controls.Name.value = stat.name; controls.Value.value = stat.value === null ? "" : String(stat.value);
        controls.original=stat;
        const remove = document.createElement("button"); remove.type = "button"; remove.className = "quiet-button"; remove.textContent = "Remove statistic"; remove.onclick = () => {row.remove();};
        row.append(remove); stats.append(row); rows.push({row, ...controls});
      };
      record.details.statistics.forEach(addStat);
      const add = document.createElement("button"); add.type = "button"; add.className = "quiet-button"; add.textContent = "Add statistic"; add.onclick = () => {if (rows.filter(r => r.row.isConnected).length < 100) addStat();}; form.append(stats,add);
      const relationships = document.createElement("fieldset"), connectionsLegend = document.createElement("legend"); connectionsLegend.textContent = "Relationships"; relationships.append(connectionsLegend);
      const connectionRows = [], connectionHelp = document.createElement("p");
      let connectionAssets = [];
      const populateTargets = (row, chosen = row.target.value) => {
        row.target.replaceChildren();
        const none = document.createElement("option"); none.value = ""; none.textContent = "Choose player"; row.target.append(none);
        const targets = row.type.value === "Character" ? state.gameDetail.characters.map(c=>({id:c.id,name:c.name}))
          : row.type.value === "Player" ? state.gameDetail.players.map(p=>({id:p.id,name:p.name}))
          : connectionAssets.map(a=>({id:a.key,name:a.metadata?.title || a.name}));
        if (chosen && !targets.some(t=>t.id===chosen)) targets.unshift({id:chosen,name:chosen.split("/").at(-1)});
        for (const target of targets) {const option = document.createElement("option"); option.value = target.id; option.textContent = target.name; row.target.append(option);}
        row.target.value = chosen;
      };
      const addConnection = (ref = {entityType:"Player",id:"",relation:""}) => {
        const element = document.createElement("div"); element.className = "character-connection-editor";
        const type = document.createElement("select"), target = document.createElement("select"), relation = document.createElement("select");
        for(const kind of (ref.id ? [ref.entityType] : ["Player"])) {const option = document.createElement("option");option.value=kind;option.textContent=kind;type.append(option);}
        type.value=ref.entityType;type.hidden=true;for(const value of ["","Ally","Sibling of","Enemy of","Parent of","Child of",...(ref.relation?[ref.relation]:[])].filter((value,index,all)=>all.indexOf(value)===index))relation.add(new Option(value||"Choose relationship",value));relation.value=ref.relation;
        for(const [label,input] of [["Reference type",type],["Player",target],["Relationship",relation]]) {const wrap=document.createElement("label");wrap.textContent=label;input.setAttribute("aria-label",label);wrap.append(input);if(input===type)wrap.hidden=true;element.append(wrap);}
        const row={element,type,target,relation}; populateTargets(row,ref.id); type.onchange=()=>populateTargets(row,"");
        const remove=document.createElement("button");remove.type="button";remove.className="quiet-button";remove.textContent="Remove relationship";remove.onclick=()=>element.remove();element.append(remove);
        connectionRows.push(row);relationships.append(element);window.PantherUI.enhanceSelect(target,"Player");window.PantherUI.enhanceSelect(relation,"Relationship");
      };
      record.details.relationships.filter(ref=>ref.entityType==="Player").forEach(addConnection);
      const addConnectionButton=document.createElement("button");addConnectionButton.type="button";addConnectionButton.className="quiet-button";addConnectionButton.textContent="Add relationship";addConnectionButton.onclick=()=>{if(connectionRows.filter(r=>r.element.isConnected).length<40)addConnection();};
      form.append(relationships,addConnectionButton,connectionHelp);
      const coverWrap = document.createElement("label"), cover = document.createElement("select"); coverWrap.textContent = "Profile portrait";
      const none = document.createElement("option"); none.value = ""; none.textContent = "No thumbnail"; cover.append(none);
      if (record.details.thumbnailAssetKey) {const selected = document.createElement("option"); selected.value = record.details.thumbnailAssetKey; selected.textContent = "Current selected thumbnail"; cover.append(selected);}
      cover.value = record.details.thumbnailAssetKey || ""; coverWrap.append(cover); const uploadPortrait=document.createElement("button");uploadPortrait.type="button";uploadPortrait.className="quiet-button";uploadPortrait.textContent="Upload portrait";uploadPortrait.onclick=()=>document.getElementById("character-portrait-file").click();form.append(coverWrap,uploadPortrait);
      void allAssets(gameId).then(assets=>{if (!current() || !cover.isConnected) return;
        connectionAssets = assets.filter(a=>a.metadata?.extra?.relationshipRole === "finished" || a.metadata?.category === "reference");
        for(const row of connectionRows) if(row.type.value === "Asset")populateTargets(row);
        for (const asset of assets) if (asset.contentType?.startsWith("image/") && asset.metadata?.characterIds?.includes(characterId) && ![...cover.options].some(o=>o.value===asset.key)) {
          const option = document.createElement("option"); option.value = asset.key; option.textContent = asset.metadata.title || asset.name; cover.append(option);
        }
      }).catch(()=>{if (cover.isConnected) connectionHelp.textContent += " Thumbnail inventory could not be loaded; existing selection remains available.";});

      const buttons = document.createElement("div"), save = document.createElement("button"), cancel = document.createElement("button"), status = document.createElement("p");
      buttons.className = "model-control-row"; save.type = "submit"; save.className = "primary-button"; save.textContent = "Save character information";
      cancel.type = "button"; cancel.className = "quiet-button"; cancel.textContent = "Cancel edit"; status.setAttribute("role","status");
      cancel.onclick = render; buttons.append(save,cancel); form.append(buttons,status); host.append(form);for(const select of form.querySelectorAll("select:not([hidden])"))window.PantherUI.enhanceSelect(select,select.getAttribute("aria-label")||"Profile portrait");
      let pending = null;
      form.onsubmit = async event => {
        event.preventDefault(); save.disabled = true;
        try {
          if (!pending) {
            const details = structuredClone(record.details);
            for (const [field,input] of Object.entries(inputs)) details[field] = field === "aliases" ? input.value.split("\n").map(s=>s.trim()).filter(Boolean) : input.value.trim() || null;
            details.relationships = [...record.details.relationships.filter(ref=>ref.entityType!=="Player"), ...connectionRows.filter(r=>r.element.isConnected && (r.target.value || r.relation.value.trim())).map(row=>{
              if (!row.target.value || !row.relation.value.trim()) throw new Error("Choose a player and relationship, or remove this row.");
              return {entityType:row.type.value,id:row.target.value,relation:row.relation.value.trim()};
            })];
            details.thumbnailAssetKey = cover.value || null;
            details.statistics = rows.filter(r=>r.row.isConnected && (r.Name.value.trim() || r.Value.value.trim())).map(r => {
              const text=r.Value.value.trim(),original=r.original;
              if(!r.Name.value.trim())throw new Error("Name this statistic or remove it.");
              let value=text||null;
              if(text&&typeof original.value==="number"&&Number.isFinite(Number(text)))value=Number(text);
              else if(text&&typeof original.value==="boolean"&&["true","false"].includes(text))value=text==="true";
              else if(text&&original.value===null&&/^-?\d+(\.\d+)?$/.test(text))value=Number(text);
              else if(original.value===null&&["true","false"].includes(text))value=text==="true";
              return {group:original.group||null,name:r.Name.value.trim(),value};
            });
            pending = {gameId,characterId,name:nameInput.value.trim(),mode:"edit",details,expectedRevision:record.revision,expectedSourceHash:null,
              operationId:crypto.randomUUID().replaceAll("-",""),reason:`Updated ${Object.keys(details).filter(key=>JSON.stringify(details[key])!==JSON.stringify(record.details[key])).join(", ") || "profile"}${nameInput.value.trim()!==record.name?" and name":""}`,dryRun:false};
          }
          for (const control of form.querySelectorAll("input,textarea,select,fieldset,button")) control.disabled = true;
          showLoading(status,"Saving the guarded character revision…");
          const controller = new AbortController(), timer = setTimeout(()=>controller.abort(),30000);
          let response;
          try { response = await api("/character-details",{}, {body:pending,signal:controller.signal}); } finally {clearTimeout(timer);}
          if (!current()) return;
          Object.assign(record,response.character);
          elements.characterName.textContent = record.name;
          const registered = state.gameDetail.characters.find(c => c.id === characterId); if (registered) registered.name = record.name;
          render();
          const message = document.createElement("p"); message.setAttribute("role","status"); message.textContent = "Character information saved."; host.append(message);
        } catch (error) {
          if (!current()) return;
          if (!pending || error.status === 400) {
            pending = null;
            for (const c of form.querySelectorAll("input,textarea,select,fieldset,button")) c.disabled = false;
            save.textContent = "Save character information";
            status.textContent = error.message;
            return;
          }
          status.textContent = error.status === 409 ? "Another update changed this character. Cancel to review the latest version." : `${error.message}. Retry saves the same revision.`;
          save.disabled = error.status === 409;
          save.textContent = "Retry exact save"; cancel.disabled = false;
          cancel.onclick = () => {void loadCharacterFacts(gameId,characterId,epoch);};
        }
      };
      nameInput.focus();
    };
    render();
  } catch (error) {
    if (!current()) return;
    host.textContent = error.status === 403 ? "A game administrator needs to initialize this profile." : error.message;
  }
}

function generateCharacterPortrait(gameId,characterId,epoch) {
  const record=state.currentCharacterFacts,status=document.getElementById("character-portrait-status");
  if(!record){status.textContent="Wait for the profile to load.";return;}
  let form=document.getElementById("character-portrait-generation");if(form){form.hidden=!form.hidden;return;}
  form=document.createElement("form");form.id="character-portrait-generation";form.className="character-edit-form";
  const label=document.createElement("label"),prompt=document.createElement("textarea");label.textContent="Portrait direction";prompt.required=true;prompt.maxLength=4000;prompt.placeholder="Appearance, clothing, pose…";label.append(prompt);
  const submit=document.createElement("button");submit.className="primary-button";submit.textContent="Generate portrait";submit.type="submit";form.append(label,submit);document.querySelector(".character-heading").append(form);
  let request=null,job=null,saveBody=null;
  const current=()=>epoch===routeEpoch&&state.currentCharacter?.characterId===characterId;
  const poll=async()=>{
    if(!current())return;
    try {
      job=await api("/asset-generation",{gameId,jobId:job.jobId});
      if(!current())return;
      if(job.status==="PUBLISHED"){
        const asset=await api("/object-url",{key:job.assetKey});
        if(!sameGameKey(job.assetKey)||!asset.metadata?.characterIds?.includes(characterId))throw new Error("Generated portrait does not match this character.");
        saveBody ||= {gameId,characterId,name:record.name,mode:"edit",details:{...record.details,thumbnailAssetKey:job.assetKey},expectedRevision:record.revision,expectedSourceHash:null,operationId:crypto.randomUUID().replaceAll("-",""),reason:"Selected generated profile portrait",dryRun:false};
        await api("/character-details",{},{body:saveBody});
        if(!current())return;assetIndex=null;await loadCharacterFacts(gameId,characterId,epoch);if(!document.getElementById("character-assets").hidden)void loadCharacterAssets(gameId,characterId,epoch);form.remove();status.textContent="";return;
      }
      if(job.status==="ATTENTION"){status.textContent=job.message||"Portrait generation needs attention.";return;}
      status.textContent=job.status==="QUEUED"?"Portrait queued":"Generating portrait…";setTimeout(()=>void poll(),4000);
    }catch(error){if(current()){status.textContent=error.message;submit.textContent="Continue portrait";submit.disabled=false;}}
  };
  form.onsubmit=async event=>{event.preventDefault();submit.disabled=true;try{if(!job){request ||= {gameId,type:"portrait",characterId,name:`${record.name} portrait`,prompt:prompt.value.trim(),operationId:crypto.randomUUID().replaceAll("-","")};job=await api("/asset-generation",{},{body:request});prompt.disabled=true;}void poll();}catch(error){if(current()){status.textContent=error.message;submit.disabled=false;submit.textContent="Retry portrait request";}}};prompt.focus();
}

async function uploadCharacterPortrait(gameId,characterId,file,epoch,setThumbnail=true) {
  if(!file)return;
  const status=document.getElementById("character-portrait-status"),button=document.getElementById("character-portrait-upload"),record=state.currentCharacterFacts;
  if(!record || record.characterId!==characterId){status.textContent="Wait for the profile to load.";return;}
  button.disabled=true;
  try {
    if(!["image/png","image/jpeg","image/webp"].includes(file.type)||file.size>20*1024**2||!file.size)throw new Error("Choose a PNG, JPEG or WebP under 20 MiB.");
    const bytes=await file.arrayBuffer(),sha256=btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)))),operationId=crypto.randomUUID().replaceAll("-","");
    status.textContent="Uploading portrait…";
    const signed=await api("/uploads",{},{body:{gameId,assetId:`portrait-${operationId}`,kind:"portrait",filename:file.name,size:file.size,contentType:file.type,sha256,metadata:{title:`${record.name} portrait`,category:"reference",characterIds:[characterId],extra:{relationshipRole:"finished",generation:{schemaVersion:1,method:"unknown",cost:{status:"unknown"}}}}}});
    const headers={...signed.headers};delete headers["Content-Length"];delete headers["content-length"];
    const uploaded=await fetch(signed.url,{method:"PUT",headers,body:bytes,signal:AbortSignal.timeout(45000)});if(!uploaded.ok)throw new Error("Portrait upload failed.");
    const verified=await api("/object-url",{key:signed.key});if(verified.sha256!==sha256||verified.size!==file.size)throw new Error("Portrait verification failed.");
    const details={...record.details,thumbnailAssetKey:signed.key};
    if(setThumbnail)await api("/character-details",{},{body:{gameId,characterId,name:record.name,mode:"edit",details,expectedRevision:record.revision,expectedSourceHash:null,operationId,reason:"Uploaded profile portrait",dryRun:false}});
    if(epoch!==routeEpoch)return;
    if(setThumbnail){const portrait=document.getElementById("character-portrait-only");portrait.src=verified.url;portrait.alt=`Portrait of ${record.name}`;portrait.hidden=false;document.getElementById("character-portrait-empty").hidden=true;}
    assetIndex=null;await window.PantherUI.invalidate(apiScope(),["/assets","/characters","/character-details","/character-details/history","/dashboard-recent"],gameId);
    await loadCharacterFacts(gameId,characterId,epoch);if(!document.getElementById("character-assets").hidden)void loadCharacterAssets(gameId,characterId,epoch);status.textContent="";
  }catch(error){if(epoch===routeEpoch)status.textContent=error.message;}
  finally{if(epoch===routeEpoch)button.disabled=false;}
}

async function loadCharacter(gameId, characterId) {
  const epoch = routeEpoch;
  state.currentCharacterFacts = null;
  for(const button of document.querySelectorAll("[data-character-panel]")){const panel=document.getElementById(button.dataset.characterPanel);panel.hidden=true;button.setAttribute("aria-expanded","false");button.onclick=()=>{panel.hidden=!panel.hidden;button.setAttribute("aria-expanded",String(!panel.hidden));if(!panel.hidden&&panel.id==="character-assets")void loadCharacterAssets(gameId,characterId,epoch);if(!panel.hidden&&panel.id==="character-appearance-panel"&&!state.appearanceVersions)void loadAppearanceVersions(gameId,characterId,epoch);};}
  document.getElementById("character-appearance-panel").hidden=false;document.getElementById("character-assets").hidden=false;
  for(const button of document.querySelectorAll('[data-character-upload]'))button.onclick=()=>document.getElementById(button.dataset.characterUpload==="reference"?"character-reference-file":"character-portrait-file").click();
  for(const button of document.querySelectorAll('[data-character-generate]'))button.onclick=()=>generateCharacterPortrait(gameId,characterId,epoch);
  document.getElementById("character-reference-file").onchange=event=>void uploadCharacterPortrait(gameId,characterId,event.target.files?.[0],epoch,false);
  const portraitStatus=document.getElementById("character-portrait-status");portraitStatus.textContent="";
  document.getElementById("character-portrait-upload").onclick=()=>document.getElementById("character-portrait-file").click();
  document.getElementById("character-portrait-file").value="";
  document.getElementById("character-portrait-file").onchange=event=>void uploadCharacterPortrait(gameId,characterId,event.target.files?.[0],epoch);
  document.getElementById("character-portrait-generation")?.remove();
  document.getElementById("character-portrait-generate").onclick=()=>generateCharacterPortrait(gameId,characterId,epoch);
  document.getElementById("characters-more").hidden = true;
  document.getElementById("character-create").hidden = true;
  document.getElementById("character-create-form").hidden = true;
  const registered=state.gameDetail?.characters?.find(character=>character.id===characterId);
  configureCharacter({character:{...registered,gameId,id:characterId,name:registered?.name||characterId},poster:null,model:null});
  void loadCharacterFacts(gameId, characterId, epoch);
  document.getElementById("character-assets-list").replaceChildren();
  document.getElementById("appearance-history").hidden = true;
  state.appearanceVersions = null;
  state.selectedAppearance = null;
  state.pendingAppearanceRestore = null;
  appearanceRequest++;
  showLoading(document.getElementById("character-assets-status"), "Loading references…");
  void loadCharacterAssets(gameId,characterId,epoch);
  elements.characterList.hidden = true;
  elements.characterProfile.hidden = false;
  elements.charactersStatus.hidden = false;
  showLoading(elements.charactersStatus, "Fetching portrait…");
  try {
    const params=new URLSearchParams(location.search);
    const profile = await api("/character", { gameId, characterId,
      appearanceId:params.get("appearance"),selectionId:params.get("selection") });
    if (epoch !== routeEpoch) return;
    configureCharacter(profile);
    elements.characterProfile.hidden = false;
    elements.charactersStatus.hidden = true;
    void loadAppearanceVersions(gameId,characterId,epoch);
  } catch (error) {
    if (epoch !== routeEpoch) return;
    if (error.message !== "Session expired") {
      elements.charactersStatus.textContent = `Appearance unavailable: ${error.message}`;
    }
  }
}

async function loadCharacterAssets(gameId, characterId, epoch) {
  const status = document.getElementById("character-assets-status");
  const list = document.getElementById("character-assets-list");
  const current = () => epoch === routeEpoch && gameId === state.gameId && state.tokens;
  try {
    const assets = await allAssets(gameId);
    if (!current()) return;
    const matching = assets.filter(a => sameGameKey(a.key) && Array.isArray(a.metadata?.characterIds) && a.metadata.characterIds.includes(characterId));
    matching.sort((a,b) => b.lastModified.localeCompare(a.lastModified));
    list.replaceChildren();
    let previousGroup = null;
    matching.sort((a,b) => a.kind.localeCompare(b.kind) || b.lastModified.localeCompare(a.lastModified));
    for (const asset of matching) {
      const li = document.createElement("li");
      const group = asset.kind;
      if (group !== previousGroup) {const header = document.createElement("li"), h = document.createElement("h3"); h.textContent = group; header.append(h); list.append(header); previousGroup = group;}
      const link = assetLink(asset);
      if (asset.contentType?.startsWith("image/")) {
        const image = document.createElement("img"); image.alt = asset.metadata?.title || asset.name;
        image.loading = "lazy"; image.dataset.characterReference = asset.key;
        link.prepend(image); li.className = "character-reference-card";
      }
      li.append(link, document.createTextNode((asset.metadata?.tags || []).length ? ` · ${asset.metadata.tags.join(" · ")}` : ""));
      list.append(li);
    }
    const images = [...list.querySelectorAll("img[data-character-reference]")];
    for (let offset=0; offset<images.length; offset+=60) {
      const batch = images.slice(offset,offset+60);
      void api("/image-links", {}, {body:{gameId,keys:batch.map(img=>img.dataset.characterReference)}}).then(links=>{
        if (!current()) return;
        for (const img of batch) { const url = links.images?.[img.dataset.characterReference]?.url; if (url) img.src = url; else img.remove(); }
      }).catch(()=>batch.forEach(img=>img.remove()));
    }
    status.textContent = "";const empty=document.getElementById("character-reference-empty"),upload=document.querySelector('[data-character-upload="reference"]');empty.hidden=Boolean(matching.length);if(matching.length)document.querySelector("#character-assets .explorer-heading").append(upload);else empty.append(upload);
  } catch (error) {
    if (current()) status.textContent = error.message;
  }
}

async function loadCharacterModel() {
  const epoch = routeEpoch;
  const pair = state.selectedAppearance?.selection;
  if (!state.currentCharacter) return;
  if (!webGlAvailable()) {
    showModelFallback("This device cannot display WebGL, so the portrait is shown instead.");
    return;
  }
  elements.modelLoad.disabled = true;
  elements.modelLoad.textContent = "Loading…";
  showLoading(elements.modelStatus, "Preparing a secure link to the 3D model…");
  try {
    if (!pair) throw new Error("No exact artwork pair is selected");
    const fresh = await api("/character", {...state.currentCharacter,appearanceId:pair.appearanceId,selectionId:pair.id});
    const selected = fresh.model;
    if (!selected || fresh.selection?.id!==pair.id || selected.key!==state.selectedModelKey) throw new Error("Selected model is unavailable");
    await Promise.race([
      customElements.whenDefined("model-viewer"),
      new Promise((_, reject) =>
        window.setTimeout(() => reject(new Error("3D viewer unavailable")), 10_000),
      ),
    ]);
    if (epoch !== routeEpoch || state.selectedAppearance?.selection?.id!==pair.id) return;
    elements.characterModel.src = selected.url;
    showLoading(elements.modelStatus, "Downloading the 3D model…");
  } catch (error) {
    if (epoch !== routeEpoch || state.selectedAppearance?.selection?.id!==pair?.id) return;
    showModelFallback(
      error.message === "Session expired"
        ? "Your session has expired."
        : "The 3D model could not be loaded. The portrait remains available.",
    );
  }
}

function resetCharacterModel() {
  elements.characterModel.cameraOrbit = elements.characterModel.dataset.defaultCameraOrbit;
  elements.characterModel.fieldOfView = elements.characterModel.dataset.defaultFieldOfView;
  elements.characterModel.cameraTarget = "auto auto auto";
  elements.characterModel.jumpCameraToGoal();
  elements.modelStatus.textContent = "Default view restored.";
}

const modelMotionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
let modelAnimationIntent = false, modelAnimationVisible = false, modelAnimationSource = null;
function resetModelAnimation() {
  modelAnimationSource = null;
  modelAnimationIntent = false;
  if (typeof elements.characterModel.pause === "function") elements.characterModel.pause();
  document.getElementById("model-animation-controls").hidden = true;
  document.getElementById("model-animation-empty").hidden = true;
  document.getElementById("model-animation-clip").replaceChildren();
}
function syncModelAnimation() {
  const viewer = elements.characterModel;
  const clip = document.getElementById("model-animation-clip");
  const button = document.getElementById("model-animation-toggle");
  const status = document.getElementById("model-animation-status");
  if (!clip.options.length || typeof viewer.pause !== "function") return;
  const visible = modelAnimationVisible && !document.hidden && viewer.offsetParent !== null;
  const playing = modelAnimationIntent && visible && viewer.loaded && !viewer.hidden;
  if (playing) { if (viewer.paused) viewer.play({repetitions:Infinity}); } else viewer.pause();
  button.textContent = modelAnimationIntent ? "Pause animation" : "Play animation";
  button.setAttribute("aria-pressed", String(modelAnimationIntent));
  status.textContent = playing ? "Character animation playing. Camera controls remain available."
    : modelAnimationIntent ? "Animation paused while this model is out of view."
    : modelMotionPreference.matches ? "Animation paused. Reduced motion is enabled; Play starts it only when you choose."
    : "Animation paused. You can explore a static pose or play the selected clip.";
}
function configureModelAnimation() {
  const viewer = elements.characterModel;
  if (!viewer.loaded || !viewer.src || modelAnimationSource === viewer.src) return;
  modelAnimationSource = viewer.src;
  const names = viewer.availableAnimations || [];
  const clip = document.getElementById("model-animation-clip");
  clip.replaceChildren();
  for (const name of names) clip.add(new Option(name,name));
  document.getElementById("model-animation-controls").hidden = !names.length;
  document.getElementById("model-animation-empty").hidden = Boolean(names.length);
  if (!names.length) return;
  // Only the explicitly authored idle clip starts automatically. Other clips remain opt-in.
  clip.value = names.includes("Panther Idle") ? "Panther Idle" : names[0];
  viewer.animationName = clip.value;
  modelAnimationIntent = clip.value === "Panther Idle" && !modelMotionPreference.matches;
  syncModelAnimation();
}
new IntersectionObserver(entries => {
  modelAnimationVisible = entries[0]?.isIntersecting || false;
  syncModelAnimation();
}, {threshold:0.01}).observe(elements.characterModel);
document.getElementById("model-animation-toggle").addEventListener("click", () => {
  modelAnimationIntent = !modelAnimationIntent; syncModelAnimation();
});
document.getElementById("model-animation-clip").addEventListener("change", event => {
  elements.characterModel.pause();
  elements.characterModel.animationName = event.target.value;
  elements.characterModel.currentTime = 0;
  syncModelAnimation();
});
document.addEventListener("visibilitychange", syncModelAnimation);
modelMotionPreference.addEventListener("change", () => {
  if (modelMotionPreference.matches) modelAnimationIntent = false;
  syncModelAnimation();
});

function zoomCharacterModel(factor) {
  const viewer = elements.characterModel;
  if (!viewer.loaded) return;
  const orbit = viewer.getCameraOrbit();
  const next = Math.max(0.2, Math.min(20, orbit.radius * factor));
  viewer.cameraOrbit = `${orbit.theta}rad ${orbit.phi}rad ${next}m`;
  viewer.jumpCameraToGoal();
}

function panCharacterModel(horizontal, vertical) {
  const viewer = elements.characterModel;
  if (!viewer.loaded) return;
  const target = viewer.getCameraTarget();
  const orbit = viewer.getCameraOrbit();
  const step = orbit.radius * 0.12;
  // Move in the camera's screen plane, not fixed world X/Y after the model rotates.
  const right = [Math.cos(orbit.theta), 0, -Math.sin(orbit.theta)];
  const up = [-Math.cos(orbit.phi) * Math.sin(orbit.theta), Math.sin(orbit.phi),
    -Math.cos(orbit.phi) * Math.cos(orbit.theta)];
  viewer.cameraTarget = `${target.x + step * (horizontal * right[0] + vertical * up[0])}m `
    + `${target.y + step * vertical * up[1]}m `
    + `${target.z + step * (horizontal * right[2] + vertical * up[2])}m`;
  viewer.jumpCameraToGoal();
}

async function renderRoute() {
  closeOptionalInfoDialogs();
  const legacySessionRoute=location.pathname.match(/^(\/games\/[a-z0-9]+(?:-[a-z0-9]+)*)?\/(?:audio|transcripts)\/?$/);
  if(legacySessionRoute){navigate(`${legacySessionRoute[1]||''}/sessions${location.search}${location.hash}`,{replace:true});return;}
  closeLiveReader();
  document.getElementById("recording-badge").hidden = true;
  document.getElementById("episode-create-action")?.remove();
  document.getElementById("episode-workspace")?.stopEditing?.();
  document.getElementById("episode-workspace")?.stopPreview?.();
  workshop.stop();
  document.getElementById("workshop").hidden = true;
  if (location.pathname === "/account" || location.pathname === "/account/recovery") {
    const epoch = ++routeEpoch;
    await roomCapture?.render("account", epoch);
    await openAccountSettings(location.pathname === "/account/recovery");
    return;
  }
  closeAccountSettings();
  dismissNarrativePreview(true);
  const epoch = ++routeEpoch;
  const pageLoading = document.getElementById("page-loading");
  pageLoading.hidden = false; showLoading(pageLoading, "Checking your sign-in…");
  document.getElementById("dashboard").hidden = true;
  document.getElementById("game-settings").hidden = true;
  clearLibrary();
  closePreview();
  window.PantherUI.unmountAssetsLibrary?.(document.getElementById('assets-library'));
  document.getElementById('assets-library').hidden=true;document.getElementById('asset-view-actions').hidden=true;
  elements.entries.hidden=false;elements.breadcrumbs.hidden=false;elements.status.hidden=false;
  elements.novel.hidden = true;
  clearNovel();
  try { await ensureSession(); } catch (error) { if (epoch === routeEpoch) pageLoading.hidden = true; showWelcome(error.message); return; }
  if (epoch !== routeEpoch) return;
  showApplicationChrome();
  const gameRoute = window.location.pathname.match(/^\/games\/([a-z0-9]+(?:-[a-z0-9]+)*)\/(dashboard|settings|assets|media|characters|novel|sessions|videos|workflows)(?:\/([a-z0-9]+(?:-[a-z0-9]+)*))?\/?$/);
  const characterMatch = window.location.pathname.match(
    /^\/characters\/([a-z0-9]+(?:-[a-z0-9]+)*)\/([a-z0-9]+(?:-[a-z0-9]+)*)\/?$/,
  );
  try {
    if (!await selectGame(gameRoute?.[1] || characterMatch?.[1], epoch)) return;
  } catch (error) {
    if (epoch !== routeEpoch) return;
    elements.characters.hidden = true;
    elements.explorer.hidden = false;
    window.PantherUI.unmountMediaBrowser(elements.entries);
    elements.entries.replaceChildren();
    elements.status.hidden = false;
    elements.status.textContent = error.message;
    return;
  } finally {
    if (epoch === routeEpoch) pageLoading.hidden = true;
  }
  if (epoch !== routeEpoch) return;
  const section = gameRoute?.[2] || window.location.pathname.slice(1);
  await roomCapture.render(section, epoch);
  if (epoch !== routeEpoch) return;
  if(section === "workflows") {
    setActiveNavigation("workflows"); elements.characters.hidden = true; elements.explorer.hidden = true;
    await workshop.open(epoch); return;
  }
  if (section === "dashboard" || location.pathname === "/") {
    setActiveNavigation("dashboard"); elements.characters.hidden = true; elements.explorer.hidden = true;
    document.getElementById("dashboard").hidden = false; renderDashboard(); void loadDashboardRecent(epoch); return;
  }
  if (section === "settings") {
    setActiveNavigation("settings"); elements.characters.hidden = true; elements.explorer.hidden = true;
    document.getElementById("game-settings").hidden = false; renderGameSettings(); return;
  }
  if(section==='assets') {
    setActiveNavigation('assets');elements.characters.hidden=true;elements.explorer.hidden=false;
    const files=new URLSearchParams(location.search).has('folder');
    document.getElementById('asset-view-actions').hidden=!files;document.getElementById('asset-browse-files').hidden=true;
    const back=document.getElementById('asset-back-library');back.hidden=!files;back.href=gamePath('assets');back.onclick=event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();navigate(back.href);};
    document.getElementById('asset-browse-files').onclick=()=>navigate(gamePath('assets')+'?folder='+encodeURIComponent(`games/${state.gameId}/`));
    if(!files){elements.entries.hidden=true;elements.breadcrumbs.hidden=true;elements.status.hidden=true;elements.loadMore.hidden=true;await loadAssetLibrary(epoch);}
    else {const folder=new URLSearchParams(location.search).get('folder');await loadPrefix(folder?.startsWith(`games/${state.gameId}/`)?folder:`games/${state.gameId}/`);}
    const key=new URLSearchParams(location.search).get('asset');if(epoch===routeEpoch&&sameGameKey(key))await previewFile({key,name:key.split('/').at(-1)});return;
  }
  if (["sessions", "videos"].includes(section)) {
    setActiveNavigation(section);
    elements.characters.hidden = true;
    elements.explorer.hidden = true;
    await loadLibrary(section, epoch);
    return;
  }
  if (window.location.pathname === "/novel" || gameRoute?.[2] === "novel") {
    setActiveNavigation("novel");
    elements.characters.hidden = true;
    elements.explorer.hidden = true;
    elements.novel.hidden = false;
    await loadNovel(gameRoute?.[3], epoch);
    return;
  }
  if (window.location.pathname === "/characters" || characterMatch || gameRoute?.[2] === "characters") {
    setActiveNavigation("characters");
    elements.characters.hidden = false;
    elements.explorer.hidden = true;
    if (characterMatch) await loadCharacter(characterMatch[1], characterMatch[2]);
    else if (gameRoute?.[3]) await loadCharacter(gameRoute[1], gameRoute[3]);
    else await loadCharacters();
    return;
  }
  if (window.location.pathname !== "/" && window.location.pathname !== "/media" && !gameRoute) {
    navigate("/media", { replace: true });
    return;
  }
  setActiveNavigation("assets");
  elements.characters.hidden = true;
  elements.explorer.hidden = false;
  const folder = new URLSearchParams(location.search).get("folder");
  const destination = folder?.startsWith(`games/${state.gameId}/`) ? folder : `games/${state.gameId}/`;
  if (!state.mediaLoaded || destination !== mediaListing.prefix) {
    state.mediaLoaded = true;
    await loadPrefix(destination);
  }
  const key = new URLSearchParams(location.search).get("asset");
  const physicalAsset = typeof key === "string" && key.startsWith(`games/${state.gameId}/content/`)
    && !key.split("/").some(part => !part || part === "." || part === "..") && !/[\\\x00-\x1f]/.test(key);
  if (epoch === routeEpoch && (sameGameKey(key) || physicalAsset)) await previewFile({key, name: key.split("/").at(-1)});
}

function fileGlyph(name) {
  const extension = name.split(".").at(-1)?.toLowerCase();
  if (["jpg", "jpeg", "png", "gif", "webp", "avif"].includes(extension)) return "▧";
  if (["mp4", "mov", "webm", "m4v"].includes(extension)) return "▶";
  if (["mp3", "wav", "flac", "m4a", "ogg"].includes(extension)) return "♪";
  if (["md", "txt", "json", "pdf", "doc", "docx"].includes(extension)) return "▤";
  return "◆";
}

function appendFolder(prefix) {
  const fragment = elements.folderTemplate.content.cloneNode(true);
  const button = fragment.querySelector(".entry");
  fragment.querySelector(".entry-name").textContent = folderName(prefix);
  button.addEventListener("click", () => loadPrefix(prefix));
  elements.entries.append(fragment);
}

function appendFile(file) {
  const fragment = elements.fileTemplate.content.cloneNode(true);
  const button = fragment.querySelector(".entry");
  fragment.querySelector(".entry-name").textContent = file.name;
  fragment.querySelector(".file-kind").textContent = fileGlyph(file.name);
  fragment.querySelector(".entry-meta").textContent = `${formatBytes(file.size)} · ${new Date(file.lastModified).toLocaleString()}`;
  button.addEventListener("click", () => previewFile(file));
  elements.entries.append(fragment);
}


let mediaListing = {prefix:null,folders:[],files:[],loading:false,error:"",hasMore:false,loadedPages:0};
let assetListing={gameId:null,assets:[],cursor:null,loading:false,error:'',pages:0};
const assetUploads=new Map(),assetGenerationJobs=new Map();
function describeResolvedAsset(result){return {...result,name:result.metadata?.title||result.filename||result.key?.split('/').at(-1),kind:result.kind||'unknown',sourceKeys:result.metadata?.sourceKeys||[]};}
async function uploadGameAsset(gameId,request){
  let pending=assetUploads.get(request.operationId);
  if(!pending){
    const file=request.file;if(!file||!file.size||file.size>100*1024**2)throw Object.assign(new Error('Choose a file under 100 MiB.'),{status:400});
    const raster=['map','blueprint','location'].includes(request.type);if(raster&&(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>20*1024**2))throw Object.assign(new Error('Choose a PNG, JPEG or WebP image under 20 MiB.'),{status:400});
    const bytes=await file.arrayBuffer(),sha256=btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))));
    pending={bytes,body:{gameId,assetId:`${request.type||'asset'}-${request.operationId}`,kind:request.type||'unknown',filename:file.name,size:file.size,contentType:file.type||'application/octet-stream',sha256,metadata:{title:(request.name||file.name).trim(),category:'reference',extra:{relationshipRole:'finished',generation:{schemaVersion:1,method:'unknown',cost:{status:'unknown'}}}}}};
    assetUploads.set(request.operationId,pending);
  }
  try{
    const signed=await api('/uploads',{},{body:pending.body});
    let existing=null;try{existing=await api('/object-url',{key:signed.key});}catch(error){if(error.status!==404)throw error;}
    if(!existing){const headers={...signed.headers};delete headers['Content-Length'];delete headers['content-length'];const response=await fetch(signed.url,{method:'PUT',headers,body:pending.bytes,signal:AbortSignal.timeout(45000)});if(!response.ok)throw new Error('Upload could not finish. Retry to continue.');existing=await api('/object-url',{key:signed.key});}
    if(existing.sha256!==pending.body.sha256||existing.size!==pending.body.size)throw new Error('Uploaded file verification failed. The original was not replaced.');
    const asset=describeResolvedAsset(existing);assetUploads.delete(request.operationId);await window.PantherUI.invalidate(apiScope(),['/assets','/objects','/dashboard-recent'],gameId);assetIndex=null;
    if(assetListing.gameId===gameId){assetListing.assets=[asset,...assetListing.assets.filter(item=>item.key!==asset.key)];drawAssetLibrary(routeEpoch);}return asset;
  }catch(error){if(error.status===400)assetUploads.delete(request.operationId);if(error instanceof TypeError)throw new Error('Upload interrupted. Your file is still selected; retry to continue.');throw error;}
}
function drawAssetLibrary(epoch){
  const host=document.getElementById('assets-library'),gameId=state.gameId;host.hidden=false;
  window.PantherUI.mountAssetsLibrary?.(host,{...assetListing,assets:assetListing.assets.map(asset=>({...asset,title:asset.metadata?.title||asset.title||asset.name,tags:asset.metadata?.tags||asset.tags||[]})),gameId,browseFilesHref:gamePath('assets')+'?folder='+encodeURIComponent(`games/${gameId}/`),onBrowseFiles:event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();navigate(gamePath('assets')+'?folder='+encodeURIComponent(`games/${gameId}/`));},hasMore:Boolean(assetListing.cursor),initialJobs:[...assetGenerationJobs.values()].filter(job=>job.gameId===gameId&&job.status!=='PUBLISHED'),
    onMore:()=>void loadAssetLibrary(epoch,assetListing.cursor),onOpen:asset=>void previewFile({key:asset.key,name:asset.metadata?.title||asset.title||asset.name||asset.key.split('/').at(-1)}),
    onThumbnail:async asset=>(await api('/object-url',{key:asset.key})).url,
    onUpload:request=>uploadGameAsset(gameId,request),
    onGenerate:async request=>{const job=await api('/asset-generation',{},{body:{gameId,...request}});assetGenerationJobs.set(job.jobId,job);return job;},
    onGenerationStatus:async job=>{const result=await api('/asset-generation',{gameId,jobId:job.jobId});assetGenerationJobs.set(job.jobId,result);if(result.status==='PUBLISHED'&&result.assetKey&&!assetListing.assets.some(asset=>asset.key===result.assetKey)){const asset=describeResolvedAsset(await api('/object-url',{key:result.assetKey}));await window.PantherUI.invalidate(apiScope(),['/assets','/dashboard-recent'],gameId);assetIndex=null;if(assetListing.gameId===gameId){assetListing.assets=[asset,...assetListing.assets];drawAssetLibrary(epoch);}}return result;}});
}
async function loadAssetLibrary(epoch,cursor=null){
  const gameId=state.gameId,current=()=>epoch===routeEpoch&&state.gameId===gameId;
  if(assetListing.gameId!==gameId)assetListing={gameId,assets:[],cursor:null,loading:false,error:'',pages:0};
  assetListing.loading=true;assetListing.error='';drawAssetLibrary(epoch);
  const jobsRequest=!cursor?api('/asset-generation',{gameId}).catch(()=>null):Promise.resolve(null);
  try{const [result,jobs]=await Promise.all([api('/assets',{gameId,section:'all',cursor}),jobsRequest]);if(!current())return;if(!Array.isArray(result.assets))throw new Error('Assets are temporarily unavailable.');
    for(const job of jobs?.jobs||[])assetGenerationJobs.set(job.jobId,job);
    const assets=cursor?[...assetListing.assets,...result.assets]:result.assets;assetListing={gameId,assets:[...new Map(assets.map(asset=>[asset.key,asset])).values()],cursor:result.cursor||null,loading:false,error:'',pages:cursor?assetListing.pages+1:1};drawAssetLibrary(epoch);
    const missing=(jobs?.jobs||[]).filter(job=>job.status==='PUBLISHED'&&sameGameKey(job.assetKey)&&!assetListing.assets.some(asset=>asset.key===job.assetKey));
    const resolved=await Promise.allSettled(missing.map(job=>api('/object-url',{key:job.assetKey})));if(!current())return;for(const result of resolved)if(result.status==='fulfilled'){const asset=describeResolvedAsset(result.value);if(!assetListing.assets.some(existing=>existing.key===asset.key))assetListing.assets.push(asset);}if(resolved.length)drawAssetLibrary(epoch);
  }catch(error){if(current()){assetListing.loading=false;assetListing.error=error.message;drawAssetLibrary(epoch);}}
}
function drawMediaBrowser() {
  const mount=window.PantherUI?.mountMediaBrowser;
  if (!mount) return false;
  elements.breadcrumbs.hidden=true;elements.status.hidden=true;elements.loadMore.hidden=true;
  elements.entries.classList.add("react-media-host");
  mount(elements.entries,{...mediaListing,gameId:state.gameId,gameName:state.gameDetail?.game.name || state.gameId,
    onFolder:prefix=>navigate(gamePath(new URLSearchParams(location.search).has('folder')&&location.pathname.endsWith('/assets')?'assets':'media')+"?folder="+encodeURIComponent(prefix)), onFile:previewFile,
    onMore:()=>loadPrefix(state.currentPrefix,state.nextCursor)});
  return true;
}
async function loadPrefix(prefix, cursor = null) {
  if (!state.gameId || !prefix.startsWith(`games/${state.gameId}/`)) return;
  const epoch = ++listingEpoch;
  const sameFolder = mediaListing.prefix === prefix;
  mediaListing={prefix,folders:sameFolder?mediaListing.folders:[],files:sameFolder?mediaListing.files:[],loading:true,error:"",hasMore:false,loadedPages:cursor?(sameFolder?mediaListing.loadedPages:0)+1:1};
  state.currentPrefix=prefix;
  const mounted=drawMediaBrowser();
  if (!mounted) {
    elements.status.hidden=false;showLoading(elements.status,"Loading files");
    if(!cursor) {elements.entries.replaceChildren();renderBreadcrumbs(prefix);}
  }
  try {
    const result=await api("/objects",{prefix,cursor});
    if(epoch!==listingEpoch || !state.tokens)return;
    const folders=cursor?[...mediaListing.folders,...result.prefixes]:result.prefixes;
    const files=cursor?[...mediaListing.files,...result.objects]:result.objects;
    state.nextCursor=result.nextCursor;
    mediaListing={prefix,folders:[...new Set(folders)],files:[...new Map(files.map(f=>[f.key,f])).values()],loading:false,error:"",hasMore:Boolean(result.nextCursor),loadedPages:mediaListing.loadedPages};
    if(drawMediaBrowser())return;
    if(!cursor)elements.entries.replaceChildren();
    result.prefixes.forEach(appendFolder);result.objects.forEach(appendFile);
    elements.status.hidden=true;elements.loadMore.hidden=!state.nextCursor;
    if(!elements.entries.children.length){const empty=document.createElement("div");empty.className="empty";empty.textContent="This folder is empty.";elements.entries.append(empty);}
  } catch(error) {
    if(epoch!==listingEpoch)return;
    mediaListing.loading=false;mediaListing.error=error.message;
    if(!drawMediaBrowser()){elements.status.textContent=error.message;elements.status.hidden=false;}
  }
}

function previewElement(contentType, url, title) {
  if (contentType.startsWith("image/")) {
    const wrapper = document.createElement("div"), activity = document.createElement("p");
    wrapper.append(activity); showLoading(activity, "Downloading the image preview…");
    const image = document.createElement("img");
    image.onload = () => activity.remove();
    image.onerror = () => { activity.textContent = "Image preview unavailable. Try Open original or reopen this preview."; };
    image.src = url;
    image.alt = title;
    wrapper.append(image); return wrapper;
  }
  if (contentType.startsWith("video/")) {
    const video = document.createElement("video");
    video.src = url;
    video.controls = true;
    video.autoplay = false;
    return video;
  }
  if (contentType.startsWith("audio/")) {
    const audio = document.createElement("audio");
    audio.src = url;
    audio.controls = true;
    return audio;
  }
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "");
  frame.src = url;
  frame.title = title;
  return frame;
}

async function previewFile(file) {
  closeOptionalInfoDialogs();
  dismissNarrativePreview();
  for (const media of elements.previewBody.querySelectorAll("audio, video")) { media.pause(); media.pantherCleanup?.(); }
  const epoch = ++previewEpoch;
  const download = document.getElementById("asset-download");
  download.disabled = true; download.onclick = null;
  document.getElementById("asset-download-status").textContent = "";
  elements.previewTitle.textContent = file.name;
  showLoading(elements.previewBody, "Preparing a secure asset preview…");
  document.getElementById("asset-generation").replaceChildren();
  showLoading(document.getElementById("asset-versions"), "Finding earlier and later versions…");
  showLoading(document.getElementById("asset-links"), "Finding this asset’s inputs and outputs…");
  elements.previewDetails.textContent = formatBytes(file.size);
  elements.openOriginal.removeAttribute("href");
  if (!elements.previewDialog.open) elements.previewDialog.showModal();

  try {
    const result = await api("/object-url", { key: file.key });
    if (epoch !== previewEpoch) return;
    elements.previewTitle.textContent=result.metadata?.title||file.name;
    renderGeneration(document.getElementById("asset-generation"), result.metadata);
    // Physical folders may change; connections/readers use the API's stable asset identity.
    const assetRef = result.key || file.key;
    download.disabled = false;
    download.onclick = () => downloadAsset(assetRef, download, document.getElementById("asset-download-status"), () => epoch === previewEpoch);
    const structured = assetRef.endsWith(".json") && sameGameKey(assetRef);
    if (structured) showLoading(elements.previewBody, "Reading the document and its metadata…");
    else elements.previewBody.replaceChildren(previewElement(result.contentType, result.url, file.name));
    elements.previewDetails.textContent = `${formatBytes(result.size)}${Number.isFinite(result.expiresIn) ? ` · link valid for ${Math.round(result.expiresIn / 60)} minutes` : ""}`;
    elements.openOriginal.href = result.url;
    if (/^(audio|video)\//.test(result.contentType)) attachMediaRecovery(elements.previewBody.firstChild, assetRef, () => epoch === previewEpoch);
    if (result.contentType.startsWith("video/")) configureVideoPreview({...result,key:assetRef},elements.previewBody.firstChild,epoch);
    void renderAssetLinks(assetRef, epoch, {...result,key:assetRef,name:result.filename||file.name,kind:result.kind||'unknown',sourceKeys:result.metadata?.sourceKeys||[]});
    void renderAssetVersions(assetRef, epoch);
    if (structured) {
      const detail = await api("/asset-document", {gameId: state.gameId, key: assetRef});
      if (epoch !== previewEpoch) return;
      renderStructuredAsset(detail, epoch);
    }
  } catch (error) {
    if (epoch !== previewEpoch) return;
    elements.previewBody.textContent = error.message;
    document.getElementById("asset-links").textContent = "Connections unavailable. Close and reopen the asset to retry.";
    document.getElementById("asset-versions").textContent = "Versions unavailable. Close and reopen the asset to retry.";
  }
}

async function downloadAsset(key, button, status, current = () => true) {
  button.disabled = true;
  status.textContent = "Preparing download…";
  try {
    // Obtain a fresh authenticated attachment URL on every click. Do not buffer
    // potentially gigabyte-sized originals into browser memory.
    const result = await api("/object-url", {key, download: "true"});
    if (!current()) return;
    const link = document.createElement("a");
    link.href = result.url; link.download = result.filename || key.split("/").at(-1);
    document.body.append(link); link.click(); link.remove();
    status.textContent = "Download requested. Check your browser’s downloads. If it fails or expires, choose Download original again.";
  } catch (error) {
    if (current()) status.textContent = `Download unavailable: ${error.message}. Sign in if needed, then retry.`;
  } finally { if (current()) button.disabled = false; }
}

function closePreview() {
  closeOptionalInfoDialogs();
  previewEpoch += 1;
  for (const media of elements.previewBody.querySelectorAll("audio, video")) { media.pause(); media.pantherCleanup?.(); media.removeAttribute("src"); media.load(); }
  elements.previewDialog.close();
  dismissNarrativePreview();
  elements.previewBody.replaceChildren();
  elements.openOriginal.removeAttribute("href");
  document.getElementById("asset-links").replaceChildren();
  document.getElementById("asset-generation").replaceChildren();
  document.getElementById("asset-versions").replaceChildren();
}

function renderGeneration(host, metadata) {
  const g = metadata?.extra?.generation;
  host.replaceChildren();
  const heading = document.createElement("h3"); heading.textContent = "Generation details";
  const list = document.createElement("dl");
  const row = (label, value) => {
    const dt = document.createElement("dt"), dd = document.createElement("dd");
    dt.textContent = label; dd.textContent = value; list.append(dt, dd);
  };
  if (!g || g.schemaVersion !== 1) return;
  const methods = {ai:"AI-generated", "ai-assisted":"AI-assisted", procedural:"Software-generated", capture:"Recorded", human:"Human-created", unknown:"Unknown"};
  const locations = {local:"Local computer", remote:"Provider-hosted", "not-applicable":"Not applicable", unknown:"Unknown"};
  row("Creation", methods[g.method] || "Unknown");
  row("Model", g.model || (["human", "capture", "procedural"].includes(g.method) ? "Not applicable" : "Unknown / not recorded"));
  row("Provider", g.provider || "Not recorded");
  row("Inference ran", locations[g.inference] || "Unknown / not recorded");
  if (g.execution) row("Processing ran", locations[g.execution] || "Unknown");
  if (g.tool) row("Tools", g.tool);
  const cost = g.cost || {};
  if (["billed", "estimated"].includes(cost.status) && /^\d{1,9}(\.\d{1,9})?$/.test(cost.amount) && /^[A-Z]{3}$/.test(cost.currency)) {
    row("Generation cost", `${cost.currency} ${cost.amount} · ${cost.status === "billed" ? "Billed" : "Estimate, not a charge"}`);
  } else row("Generation cost", {subscription:"Subscription-covered · no per-asset charge recorded", "not-applicable":"No metered generation charge · hardware/storage excluded", unknown:"Unknown / not reconciled"}[cost.status] || "Unknown / not reconciled");
  if (g.evidence) row("Evidence", g.evidence);
  host.append(heading, list);
}

const novel = Object.fromEntries(["status", "list", "reader", "prose", "title", "manuscript",
  "details", "notice", "pagination", "read", "show-details", "download", "back", "refresh", "resume", "progress", "artwork", "art-before", "art-after"]
  .map(name => [name, document.getElementById(`novel-${name}`)]));
let currentChapter = null;
let currentNovelBook = null;
let novelProgressCleanup = null;

function clearNovel() {
  novelProgressCleanup?.(); novelProgressCleanup = null;
  currentNovelBook = null;
  dismissNarrativePreview(true);
  currentChapter = null;
  novel.reader.hidden = true;
  for (const part of ["list", "prose", "details", "pagination", "title", "notice"]) novel[part].replaceChildren();
  novel.resume.replaceChildren(); novel.resume.hidden = true; novel.progress.textContent = "";
  for(const name of ["artwork", "art-before", "art-after"]) novel[name].replaceChildren();
  novel.artwork.hidden=true;
}

async function novelIllustrations(chapter,current) {
  const params={gameId:state.gameId,id:chapter.id};
  const pinned=new URL(location.href).searchParams.get("illustrationRevision");
  if(pinned)params.revision=pinned;
  let record;
  try { record=(await api("/novel-illustrations",params)).record; }
  catch(error) {
    if(!current() || error.status===404)return;
    novel.artwork.hidden=false;
    const note=document.createElement("p");note.textContent="Artwork could not be checked. The complete chapter remains readable.";
    const retry=document.createElement("button");retry.textContent="Retry artwork";
    retry.onclick=()=>{novel.artwork.replaceChildren();novelIllustrations(chapter,current);};
    novel.artwork.replaceChildren(note,retry);return;
  }
  if(!current() || !record)return;
  const key=chapter.details?.artifact?.key;
  if(record.entityType!=="ChapterIllustrations" || record.schemaVersion!==1 || record.gameId!==state.gameId || record.id!==chapter.id
    || record.chapterKey!==key || !["draft","approved"].includes(record.status) || !Array.isArray(record.illustrations) || record.illustrations.length>12
    || record.illustrations.some(i=>!i || !sameGameKey(i.assetKey) || !["before-chapter","after-chapter"].includes(i.placement) || typeof i.altText!=="string" || !i.altText || typeof i.caption!=="string")){
      novel.artwork.hidden=false;novel.artwork.textContent="Artwork selection is invalid for this chapter edition. No substitute images were shown.";return;
    }
  novel.artwork.hidden=false;
  const note=document.createElement("p");note.textContent=`Artwork is an illustrative adaptation, not additional campaign facts. ${record.status==="approved"?"Approved private selection":"Private draft · hidden by default"}.`;
  const label=document.createElement("label"),toggle=document.createElement("input");toggle.type="checkbox";toggle.checked=record.status==="approved";
  label.append(toggle,document.createTextNode("Show chapter artwork"));novel.artwork.replaceChildren(note,label);
  if(record.previousRevision && /^[a-f0-9]{32}$/.test(record.previousRevision)){
    const previous=document.createElement("a"),url=new URL(location.href);url.searchParams.set("illustrationRevision",record.previousRevision);
    previous.href=url.pathname+url.search;previous.textContent="Previous artwork selection";previous.onclick=e=>{if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();navigate(previous.getAttribute("href"));};novel.artwork.append(previous);
  }
  const figures=record.illustrations.map(item=>{
    const figure=document.createElement("figure");figure.className="novel-illustration";
    const host=document.createElement("div"),caption=document.createElement("figcaption");caption.textContent=item.caption;
    // Use the established typed asset destination, never an artifact-supplied URL.
    const typed=assetLink({key:item.assetKey},"View image and provenance");caption.append(document.createTextNode(item.caption?" · ":""),typed);
    figure.append(host,caption);novel[item.placement==="before-chapter"?"art-before":"art-after"].append(figure);
    return {item,figure,host};
  });
  let generation=0;
  async function loadFigures() {
    const mine=++generation;
    const active=()=>current() && toggle.checked && mine===generation;
    try {
      const result=await api("/image-links",{},{body:{gameId:state.gameId,keys:record.illustrations.map(i=>i.assetKey)}});
      if(!active())return;
      for(const {item,host} of figures){
        const image=document.createElement("img");image.alt=item.altText;image.decoding="async";
        const fail=()=>{if(!active())return;const message=document.createElement("p");message.className="illustration-fallback";message.textContent="Image unavailable. The chapter text is unaffected.";const retry=document.createElement("button");retry.textContent="Retry image access";retry.onclick=loadFigures;host.replaceChildren(message,retry);};
        image.onerror=fail;const file=result.images?.[item.assetKey];if(file?.url){host.replaceChildren(image);image.src=file.url;}else fail();
      }
    } catch { if(active())for(const {host} of figures){const retry=document.createElement("button");retry.textContent="Artwork unavailable · retry";retry.onclick=loadFigures;host.replaceChildren(retry);} }
  }
  function show(){for(const name of ["art-before","art-after"])novel[name].hidden=!toggle.checked;
    if(toggle.checked && figures.length)loadFigures();else generation++;}
  toggle.onchange=show;show();
}

function novelProgressKey() {
  try {
    const sub = decodeToken(state.tokens?.id_token)?.sub;
    return typeof sub === "string" && sub.length <= 256 ? `panther.reading.v1:${sub}:${state.gameId}` : null;
  } catch { return null; }
}

function savedNovelProgress() {
  try {
    const key = novelProgressKey();
    const value = key && JSON.parse(localStorage.getItem(key) || "null");
    if (value?.schemaVersion !== 1 || value.gameId !== state.gameId || !/^[a-f0-9]{64}$/.test(value.chapterId)
      || !Number.isInteger(value.paragraph) || value.paragraph < 0 || value.paragraph > 100000
      || !Number.isFinite(value.percent) || value.percent < 0 || value.percent > 100
      || (value.bookRevision !== null && !/^[a-f0-9]{32}$/.test(value.bookRevision))
      || (value.bookId !== null && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.bookId))) return null;
    return value;
  } catch { return null; }
}

function readingProgress(chapter, book, current) {
  const key = novelProgressKey();
  if (!key) { novel.progress.textContent = "Reading position unavailable for this sign-in."; return; }
  novel.progress.textContent = "Reading position is saved on this device.";
  const saved = savedNovelProgress();
  if (saved?.chapterId === chapter.id) {
    const button = document.createElement("button"); button.className = "quiet-button";
    button.textContent = `Resume at ${saved.percent}% · saved on this device`;
    button.addEventListener("click", () => {
      novelView(false);
      const paragraphs = [...novel.prose.children];
      const target = paragraphs[Math.min(saved.paragraph, paragraphs.length - 1)];
      if (target) { target.tabIndex = -1; target.focus({preventScroll:true}); target.scrollIntoView({block:"start",behavior:"smooth"}); }
    });
    novel.resume.replaceChildren(button); novel.resume.hidden = false;
  }
  let timer;
  const save = () => {
    if (!current() || novel.manuscript.hidden || novel.reader.hidden) return;
    const paragraphs = [...novel.prose.children];
    if (!paragraphs.length || novel.prose.getBoundingClientRect().top > innerHeight) return;
    let paragraph = 0;
    for (let i = 0; i < paragraphs.length; i++) if (paragraphs[i].getBoundingClientRect().top <= innerHeight * .3) paragraph = i;
    const percent = Math.round(100 * (paragraph + 1) / paragraphs.length);
    try {
      localStorage.setItem(key, JSON.stringify({schemaVersion:1,gameId:state.gameId,chapterId:chapter.id,
        bookId:book?.id || null,bookRevision:book?.revision || null,paragraph,percent,title:chapter.title,updatedAt:Date.now()}));
      novel.progress.textContent = `${percent}% through this chapter · position saved on this device`;
    } catch { novel.progress.textContent = "This browser cannot save reading position. The chapter remains available."; }
  };
  const onScroll = () => { clearTimeout(timer); timer = setTimeout(save, 250); };
  window.addEventListener("scroll", onScroll, {passive:true});
  novelProgressCleanup = () => { clearTimeout(timer); window.removeEventListener("scroll", onScroll); };
}

async function novelOrganization(gameId, current) {
  const results = [];
  for (const type of ["stories", "books"]) {
    const records = [], seen = new Set(); let cursor;
    do {
      const page = await api(`/novel-${type}`, {gameId,cursor});
      if (!current()) return null;
      if (!Array.isArray(page.records)) throw new Error("The book library could not be read completely");
      records.push(...page.records); cursor = page.cursor;
      if (records.length > 5000 || seen.size >= 200 || (cursor && seen.has(cursor))) throw new Error("The book library exceeds its bounded reader limit or returned a repeated cursor");
      if (cursor) seen.add(cursor);
    } while (cursor);
    results.push(records);
  }
  return {stories:results[0],books:results[1]};
}

function bookLink(title, book, chapterId) {
  const link = novelLink(title, chapterId || "", book.id);
  link.href = gamePath(chapterId ? `novel/${chapterId}` : "novel") + `?book=${encodeURIComponent(book.id)}&bookRevision=${encodeURIComponent(book.revision)}`;
  return link;
}

function bookCard(book, story, byKey, current) {
  const card = document.createElement("article"); card.className = "novel-card novel-book";
  const content = document.createElement("div");
  const heading = document.createElement("h2"); heading.append(bookLink(book.title,book));
  const meta = document.createElement("p"); meta.className = "eyebrow";
  meta.textContent = `${story?.title || "Story unavailable"} · ${book.status === "approved" ? "Approved private selection" : "Private draft"}`;
  const synopsis = document.createElement("p"); synopsis.textContent = book.synopsis || "No synopsis provided.";
  const details = document.createElement("p"); details.textContent = [...(book.tags || []),book.authorCredit,
    `${book.volumes.length} volume${book.volumes.length === 1 ? "" : "s"}`,`Revision ${book.revision.slice(0,8)}`].filter(Boolean).join(" · ");
  content.append(meta,heading,synopsis,details); card.append(content);
  if(book.previousRevision){const previous=bookLink("Previous book revision",{...book,revision:book.previousRevision});content.append(previous);}
  if (book.coverAssetKey) {
    const image = document.createElement("img"); image.alt = `Cover for ${book.title}`; image.className = "novel-cover";
    image.dataset.novelCover = book.coverAssetKey;
    card.prepend(image);
    image.addEventListener("error",()=>image.remove());
  }
  if (book.volumes.some(v=>v.chapterKeys.some(k=>!byKey.has(k)))) {
    const warning=document.createElement("p"); warning.textContent="Some pinned chapters are unavailable. No newer edition was substituted."; content.append(warning);
  }
  return card;
}

async function novelCovers(gameId,current) {
  const images=[...novel.list.querySelectorAll('[data-novel-cover]')], keys=[...new Set(images.map(i=>i.dataset.novelCover))];
  for(let offset=0;offset<keys.length;offset+=60){
    if(!current())return;
    const batch=keys.slice(offset,offset+60);
    try{const result=await api("/image-links",{},{body:{gameId,keys:batch}});if(!current())return;
      for(const image of images.filter(i=>batch.includes(i.dataset.novelCover))){const item=result.images?.[image.dataset.novelCover];if(item?.url)image.src=item.url;else image.remove();}
    }catch{if(current())for(const image of images.filter(i=>batch.includes(i.dataset.novelCover)))image.remove();}
  }
}

function novelView(details) {
  novel.manuscript.hidden = details;
  novel.details.hidden = !details;
  novel.read.setAttribute("aria-pressed", String(!details));
  novel["show-details"].setAttribute("aria-pressed", String(details));
}

// A deliberately small prose-Markdown renderer. Raw HTML, images, and links stay inert text;
// nothing from an AI artifact is ever assigned to innerHTML or fetched as a remote resource.
function proseInline(parent, text, references) {
  for (const part of text.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*|_[^_\n]+_)/g)) {
    const strong = part.startsWith("**") && part.endsWith("**");
    const emphasis = !strong && ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_")));
    if (strong || emphasis) {
      const el = document.createElement(strong ? "strong" : "em");
      linkedProse(el, part.slice(strong ? 2 : 1, strong ? -2 : -1), references);
      parent.append(el);
    } else linkedProse(parent, part, references);
  }
}

function proseMarkdown(parent, markdown, references) {
  if (narrativePreviewAnchor && parent.contains(narrativePreviewAnchor)) dismissNarrativePreview();
  parent.replaceChildren();
  for (const block of markdown.trim().split(/\n\s*\n/)) {
    if (!block) continue;
    const heading = block.match(/^(#{1,6}) (.+)$/);
    const separator = /^(?:\*\s*){3,}$|^-{3,}$/.test(block.trim());
    const quote = block.startsWith("> ");
    const el = document.createElement(separator ? "hr" : heading ? `h${Math.min(heading[1].length + 1, 6)}` : quote ? "blockquote" : "p");
    if (!separator) proseInline(el, heading ? heading[2] : quote ? block.replace(/^> ?/gm, "") : block, references);
    parent.append(el);
  }
}

// Typed destinations, not artifact-supplied URLs. Add a resolver when a new data type has a page.
function narrativeReferences(chapter, assets, chapters, collections = []) {
  const characters = state.gameDetail.characters || [];
  const resolvers = {
    collection: target => {
      const collection=collections.find(c=>c.id===target.id && c.gameId===state.gameId && c.entityType==="VideoCollection");
      if(!collection || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(target.id))return null;
      return {identity:`collection:${collection.id}`,target,make:text=>{
        const link=document.createElement("a");link.href=gamePath("videos")+`?collection=${encodeURIComponent(collection.id)}`;link.textContent=text;link.title=`Video collection: ${collection.name}`;
        link.onclick=event=>{if(event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)return;event.preventDefault();navigate(link.getAttribute("href"));};return link;
      }};
    },
    character: target => {
      const c = characters.find(c => c.id === target.id);
      if (!c || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(c.id)) return null;
      return {identity: `character:${c.id}`, target, make: text => {
        const a = document.createElement("a"); a.href = gamePath(`characters/${c.id}`); a.textContent = text; a.title = `Character: ${c.name}`;
        a.addEventListener("click", e => {
          if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
          e.preventDefault(); navigate(a.getAttribute("href"));
        });
        return a;
      }};
    },
    asset: target => {
      const asset = assets.find(a => a.key === target.key && sameGameKey(a.key));
      return asset ? {identity: `asset:${asset.key}`, target, make: text => assetLink(asset, text)} : null;
    },
    chapter: target => chapters.some(c => c.id === target.id && /^[a-f0-9]{64}$/.test(c.id))
      ? {identity: `chapter:${target.id}`, target, make: text => novelLink(text, target.id)} : null,
  };
  const names = new Map();
  const add = (text, target, explicit = false) => {
    if (typeof text !== "string" || text !== text.trim() || text.length < 2 || text.length > 160 || /[\n\r<>\[\]*_`]/.test(text)) return;
    if (!target || (target.gameId !== undefined && target.gameId !== state.gameId)) {
      if (explicit) names.set(text, {explicit, ambiguous:true});
      return;
    }
    const resolve = Object.hasOwn(resolvers, target.type) && resolvers[target.type];
    const destination = resolve && resolve(target);
    if (!destination) {
      if (explicit) names.set(text, {explicit, ambiguous:true});
      return;
    }
    const previous = names.get(text);
    if (previous?.explicit && !explicit) return;
    if (!previous || (explicit && !previous.explicit)) names.set(text, {...destination, explicit});
    else if (previous.identity !== destination.identity) names.set(text, {explicit, ambiguous: true});
  };
  for (const c of characters) add(c.name, {type:"character", id:c.id});
  for (const a of assets) add(a.metadata?.title, {type:"asset", key:a.key});
  const declared = chapter.readerReferences;
  if (declared?.schemaVersion === 1 && Array.isArray(declared.mentions) && declared.mentions.length <= 200) {
    for (const mention of declared.mentions) if (mention) add(mention.text, mention.target, true);
  }
  // Keep ambiguous longer names in the matcher so they cannot turn into a shorter false match.
  const labels = [...names.keys()].filter(text => chapter.markdown.includes(text)).sort((a,b) => b.length - a.length);
  const pattern = labels.map(text => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  return {names, pattern: pattern ? new RegExp(`(?<![\\p{L}\\p{N}_])(?:${pattern})(?![\\p{L}\\p{N}_])`, "gu") : null};
}

function linkedProse(parent, text, references) {
  if (!references?.pattern) { parent.append(document.createTextNode(text)); return; }
  // Existing raw Markdown links/code/HTML remain inert, even when their labels match known names.
  for (const part of text.split(/(!?\[[^\]]*\]\([^)]*\)|`[^`]*`|<[^>]*>)/g)) {
    if (/^(?:!?\[|`|<)/.test(part)) { parent.append(document.createTextNode(part)); continue; }
    let end = 0;
    references.pattern.lastIndex = 0;
    for (const match of part.matchAll(references.pattern)) {
      parent.append(document.createTextNode(part.slice(end, match.index)));
      const reference = references.names.get(match[0]);
      if (reference.ambiguous) parent.append(document.createTextNode(match[0]));
      else {
        const a = reference.make(match[0]); a.classList.add("narrative-link"); parent.append(a);
        attachNarrativePreview(a, reference.target);
      }
      end = match.index + match[0].length;
    }
    parent.append(document.createTextNode(part.slice(end)));
  }
}

// Read-time, versioned preview projections work for every existing and future target. They never
// rewrite manuscripts or turn generated adaptations into facts. No AI/provider requests on hover.
const narrativePreviewCache = new Map();
let narrativePreviewCard, narrativePreviewAnchor, narrativePreviewTimer, narrativePreviewSerial = 0;
let narrativePreviewTouch = false;

function previewText(value, maximum = 320) {
  if (typeof value !== "string") return "";
  const text = value.replace(/^#{1,6}\s+/gm, "").replace(/\s+/g, " ").trim();
  if (text.length <= maximum) return text;
  const short = text.slice(0, maximum - 1);
  const boundary = short.lastIndexOf(" ");
  return short.slice(0, boundary > maximum / 2 ? boundary : short.length) + "…";
}

function dismissNarrativePreview(clearCache = false) {
  clearTimeout(narrativePreviewTimer);
  narrativePreviewSerial += 1;
  if (narrativePreviewAnchor) {
    narrativePreviewAnchor.removeAttribute("aria-describedby");
    narrativePreviewAnchor.setAttribute("aria-expanded", "false");
  }
  narrativePreviewAnchor = null;
  narrativePreviewTouch = false;
  if (narrativePreviewCard) { narrativePreviewCard.hidden = true; narrativePreviewCard.replaceChildren(); }
  if (clearCache) narrativePreviewCache.clear();
}

function positionNarrativePreview() {
  if (!narrativePreviewAnchor || !narrativePreviewCard || narrativePreviewCard.hidden) return;
  const rect = narrativePreviewAnchor.getBoundingClientRect();
  if (!narrativePreviewAnchor.isConnected || rect.bottom < 0 || rect.top > innerHeight) {
    dismissNarrativePreview(); return;
  }
  const card = narrativePreviewCard, margin = 12;
  card.style.maxHeight = `${Math.max(120, innerHeight - margin * 2)}px`;
  const box = card.getBoundingClientRect();
  card.style.left = `${Math.max(margin, Math.min(rect.left, innerWidth - box.width - margin))}px`;
  const below = rect.bottom + 6;
  card.style.top = `${Math.max(margin, Math.min(below + box.height <= innerHeight - margin
    ? below : rect.top - box.height - 6, innerHeight - box.height - margin))}px`;
}

function previewCard() {
  if (narrativePreviewCard) return narrativePreviewCard;
  const card = document.createElement("section"); card.id = "narrative-preview";
  card.className = "narrative-preview"; card.hidden = true;
  card.setAttribute("role", "dialog"); card.setAttribute("aria-label", "Link preview");
  card.addEventListener("pointerenter", () => clearTimeout(narrativePreviewTimer));
  card.addEventListener("pointerleave", () => {
    if (!narrativePreviewTouch && !card.contains(document.activeElement)) {
      narrativePreviewTimer = setTimeout(() => dismissNarrativePreview(), 180);
    }
  });
  card.addEventListener("focusout", () => setTimeout(() => {
    if (!card.contains(document.activeElement) && document.activeElement !== narrativePreviewAnchor) dismissNarrativePreview();
  }, 0));
  document.body.append(card); narrativePreviewCard = card;
  return card;
}

async function narrativePreviewData(target, gameId) {
  const requestRoute = routeEpoch, requestSession = sessionEpoch;
  const characters = state.gameDetail?.characters || [];
  const cacheKey = JSON.stringify([gameId, target]);
  const cached = narrativePreviewCache.get(cacheKey);
  if (cached && Date.now() - cached.at < 60000) return cached.value;
  const localAssets = await allAssets(gameId);
  const metadataPreview = metadata => metadata?.extra?.preview?.schemaVersion === 1 ? metadata.extra.preview : {};
  let title, summary = "", source = "description", imageKey, imageLabel = "Preview image", asset;
  if (target.type === "character") {
    const character = characters.find(c => c.id === target.id);
    title = character?.name || "Character";
    const result = await api("/character-details", {gameId, characterId: target.id});
    const details = result?.character?.details;
    summary = previewText(details?.overview) || previewText(details?.subtitle);
    imageKey = details?.thumbnailAssetKey;
    imageLabel = `Portrait of ${title}`;
    if (!summary) { summary = `${title} is a character in this game. No description has been recorded yet.`; source = "metadata"; }
    if (!imageKey) {
      // Only an explicitly associated portrait; never infer identity from appearance or filename.
      const portraits = localAssets.filter(a => a.kind === "portrait" && a.metadata?.characterIds?.includes(target.id));
      if (portraits.length === 1) { imageKey = portraits[0].key; imageLabel = `Associated portrait of ${title}`; }
    }
  } else if (target.type === "asset") {
    asset = localAssets.find(a => a.key === target.key);
    if (!asset) throw new Error("Linked asset is unavailable");
    title = asset.metadata?.title || asset.name;
    const supplied = metadataPreview(asset.metadata);
    summary = previewText(supplied.summary) || previewText(asset.metadata?.description);
    imageKey = supplied.imageKey || (/^image\/(png|jpeg|webp|avif)$/.test(asset.contentType) ? asset.key : null);
    if (!summary && asset.key.endsWith(".json")) {
      const detail = await api("/asset-document", {gameId, key: asset.key});
      const doc = detail.document;
      summary = previewText(doc?.payload?.summary || doc?.summary);
      if (!summary) {
        const transcript = doc?.entityType === "PlayerTranscript" ? doc : doc?.payload?.transcript;
        const text = doc?.stage === "novel-chapter" ? doc.payload?.chapter
          : transcript?.segments?.slice(0, 3).map(s => s.text).filter(t => typeof t === "string").join(" ");
        summary = previewText(text); if (summary) source = "excerpt";
      }
    }
    if (!summary) {
      summary = `${title} · ${(asset.kind || "asset").replaceAll("-", " ")}${asset.metadata?.sessionId ? ` · ${asset.metadata.sessionId}` : ""}. No description has been recorded yet.`;
      source = "metadata";
    }
  } else if (target.type === "chapter") {
    const chapter = await api("/novel-chapter", {gameId, chapterId: target.id});
    title = chapter.title; summary = previewText(chapter.markdown); source = "excerpt";
    asset = localAssets.find(a => a.kind === "novel-chapter" && a.metadata?.extra?.jobId === target.id);
    const supplied = metadataPreview(asset?.metadata);
    if (previewText(supplied.summary)) { summary = previewText(supplied.summary); source = "description"; }
    imageKey = supplied.imageKey;
  } else if (target.type === "collection") {
    const result=await api("/video-collections",{gameId,id:target.id,metadataOnly:"true"});
    if(result.collection?.gameId!==gameId || result.collection?.entityType!=="VideoCollection")throw new Error("Collection unavailable");
    title=result.collection.name;summary=previewText(result.collection.description);
    if(!summary){summary=`${result.collection.assetKeys.length} saved video references. No description recorded.`;source="metadata";}
  } else throw new Error("Unsupported preview target");
  let imageUrl;
  if (typeof imageKey === "string" && imageKey.startsWith(`games/${gameId}/assets/`) && !imageKey.split("/").includes("..")) {
    const image = await api("/object-url", {key: imageKey}).catch(() => null);
    if (image && /^image\/(png|jpeg|webp|avif)$/.test(image.contentType) && image.size > 0 && image.size <= 8 * 1024 * 1024) imageUrl = image.url;
  }
  const value = {schemaVersion: 1, title, summary, source, imageUrl, imageLabel};
  // A late response must not repopulate the cache after sign-out or a game change.
  if (state.gameId === gameId && state.tokens && requestRoute === routeEpoch && requestSession === sessionEpoch) {
    if (narrativePreviewCache.size >= 50) narrativePreviewCache.delete(narrativePreviewCache.keys().next().value);
    narrativePreviewCache.set(cacheKey, {at: Date.now(), value});
  }
  return value;
}

async function showNarrativePreview(anchor, target, touch = false) {
  dismissNarrativePreview();
  const serial = narrativePreviewSerial, gameId = state.gameId, epoch = routeEpoch;
  narrativePreviewAnchor = anchor; narrativePreviewTouch = touch;
  anchor.removeAttribute("title"); anchor.setAttribute("aria-expanded", "true");
  anchor.setAttribute("aria-describedby", "narrative-preview-summary");
  const card = previewCard(); card.hidden = false;
  const close = document.createElement("button"); close.className = "quiet-button preview-close";
  close.type = "button"; close.textContent = "×"; close.setAttribute("aria-label", "Close link preview");
  close.addEventListener("click", () => { dismissNarrativePreview(); anchor.focus({preventScroll:true}); dismissNarrativePreview(); });
  const heading = document.createElement("h3"); heading.textContent = anchor.textContent;
  const summary = document.createElement("p"); summary.id = "narrative-preview-summary";
  summary.setAttribute("aria-live", "polite"); showLoading(summary, "Fetching link preview…");
  const label = document.createElement("p"); label.className = "preview-caption";
  const open = document.createElement("a"); open.href = anchor.href; open.textContent = "Open linked page →";
  open.addEventListener("click", e => {
    if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault(); dismissNarrativePreview(); anchor.click();
  });
  card.replaceChildren(close, heading, summary, label, open); positionNarrativePreview();
  const current = () => serial === narrativePreviewSerial && epoch === routeEpoch && gameId === state.gameId && anchor.isConnected;
  try {
    const data = await narrativePreviewData(target, gameId);
    if (!current()) return;
    heading.textContent = data.title; summary.textContent = data.summary;
    label.textContent = data.source === "excerpt" ? "Opening excerpt · may contain spoilers" : data.source === "metadata" ? "Available information" : "Summary";
    if (data.imageUrl) {
      const img = document.createElement("img"); img.alt = data.imageLabel;
      img.referrerPolicy = "no-referrer"; img.src = data.imageUrl;
      img.addEventListener("error", () => { img.remove(); positionNarrativePreview(); });
      img.addEventListener("load", positionNarrativePreview);
      heading.after(img);
    }
    positionNarrativePreview();
  } catch {
    if (current()) { summary.textContent = "Preview unavailable. You can still open the linked page."; positionNarrativePreview(); }
  }
}

function attachNarrativePreview(anchor, target) {
  let touchDown = false;
  anchor.setAttribute("aria-haspopup", "dialog"); anchor.setAttribute("aria-controls", "narrative-preview");
  anchor.setAttribute("aria-expanded", "false");
  anchor.addEventListener("pointerenter", e => {
    if (e.pointerType === "touch") return;
    clearTimeout(narrativePreviewTimer);
    narrativePreviewTimer = setTimeout(() => showNarrativePreview(anchor, target), 160);
  });
  anchor.addEventListener("pointerleave", () => {
    clearTimeout(narrativePreviewTimer);
    if (!narrativePreviewTouch && document.activeElement !== anchor) narrativePreviewTimer = setTimeout(() => dismissNarrativePreview(), 180);
  });
  anchor.addEventListener("pointerdown", e => { touchDown = e.pointerType === "touch"; });
  anchor.addEventListener("focus", () => { if (!touchDown) showNarrativePreview(anchor, target); });
  anchor.addEventListener("blur", () => {
    touchDown = false;
    narrativePreviewTimer = setTimeout(() => { if (!narrativePreviewCard?.contains(document.activeElement)) dismissNarrativePreview(); }, 180);
  });
  anchor.addEventListener("click", e => {
    if (!(e.pointerType === "touch" || (e.detail && matchMedia("(hover: none)").matches))) return;
    if (narrativePreviewAnchor === anchor && narrativePreviewTouch) { dismissNarrativePreview(); return; }
    e.preventDefault(); e.stopImmediatePropagation(); showNarrativePreview(anchor, target, true);
  }, true);
}

document.addEventListener("keydown", event => {
  if (event.key === "Escape" && narrativePreviewAnchor) { event.preventDefault(); dismissNarrativePreview(); }
});
document.addEventListener("pointerdown", event => {
  if (narrativePreviewAnchor && !narrativePreviewAnchor.contains(event.target) && !narrativePreviewCard?.contains(event.target)) dismissNarrativePreview();
});
window.addEventListener("resize", positionNarrativePreview);
document.addEventListener("scroll", positionNarrativePreview, true);

function novelLink(title, id, bookId = null) {
  const link = document.createElement("a");
  link.href = gamePath(`novel/${id}`) + (bookId ? `?book=${encodeURIComponent(bookId)}` + (currentNovelBook?.id===bookId ? `&bookRevision=${encodeURIComponent(currentNovelBook.revision)}` : "") : "");
  link.textContent = title;
  link.addEventListener("click", event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(link.getAttribute("href"));
  });
  return link;
}

function chapterDate(chapter) {
  return new Date(chapter.publishedAt * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function chapterDetails(chapter, versions) {
  const heading = document.createElement("h2"); heading.textContent = "About this chapter";
  const summary = document.createElement("p");
  summary.textContent = `Session: ${chapter.sessionId} · Published ${chapterDate(chapter)} · ${chapter.publicationStatus} · ${chapter.reviewStatus}. An adaptation, not a factual transcript.`;
  const authored = chapter.details.authorship === "human";
  if (authored) summary.textContent = `Written manually · ${chapterDate(chapter)}`;
  const reviewTitle = document.createElement("h3"); reviewTitle.textContent = "Editorial review and notes"; reviewTitle.hidden = authored;
  const review = document.createElement("div");
  proseMarkdown(review, chapter.details.review.markdown || "No review text recorded."); review.hidden = authored;
  const notes = document.createElement("ul");
  for (const note of chapter.details.review.uncertainties || []) {
    const li = document.createElement("li"); li.textContent = note; notes.append(li);
  }
  const versionsTitle = document.createElement("h3"); versionsTitle.textContent = authored ? "Chapter versions" : "Versions of this session";
  const versionList = document.createElement("ul");
  for (const [index, version] of versions.entries()) {
    const li = document.createElement("li");
    li.append(novelLink(`${index === 0 ? "Latest" : "Earlier"} · ${chapterDate(version)} · ${version.title}${version.id === chapter.id ? " (viewing)" : ""}`, version.id));
    versionList.append(li);
  }
  const sourceTitle = document.createElement("h3"); sourceTitle.textContent = "Connected assets";
  const sources = document.createElement("div"); sources.className = "novel-connections asset-links";
  const creation = document.createElement("section"); creation.className = "generation-details";
  showLoading(sources, "Finding the chapter’s source assets…");
  const gameId = state.gameId, epoch = routeEpoch;
  void allAssets(gameId).then(assets => {
    if (epoch !== routeEpoch || state.gameId !== gameId || currentChapter !== chapter || !state.tokens) return;
    sources.replaceChildren();
    const key = chapter.details.artifact?.key;
    renderGeneration(creation, assets.find(a => a.key === key)?.metadata);
    if (!assets.some(a => a.key === key)) { sources.textContent = "Chapter connections are not indexed yet."; return; }
    const connections = finishedAssetConnections(assets, key, gameId);
    appendFinishedConnections(sources, connections);
    if (connections.incomplete) sources.append("Some recorded connections are unavailable.");
  }).catch(() => {
    if (epoch === routeEpoch && state.gameId === gameId && state.tokens) sources.textContent = "Connections unavailable. Reload the page to try again.";
  });
  const provenance = detailBlock("Provenance and revisions", chapter.details);
  novel.details.replaceChildren(heading, summary, creation, versionsTitle, versionList, reviewTitle, review, notes, sourceTitle, sources, provenance);
}

function manualChapterEditor(previous = null) {
  const host = document.getElementById("manual-chapter-form");
  host.hidden = false; host.replaceChildren();
  const composer = document.getElementById("editorial-novel-composer");
  const create = document.querySelector("#novel .explorer-heading [data-generation-action]");
  if (composer) composer.hidden = true;
  if (create) create.hidden = true;
  const gameId = state.gameId, epoch = routeEpoch;
  const titleLabel = document.createElement("label"), title = document.createElement("input");
  titleLabel.textContent = "Chapter title"; title.required = true; title.maxLength = 160; title.value = previous?.title || ""; titleLabel.append(title);
  const proseLabel = document.createElement("label"), prose = document.createElement("textarea");
  proseLabel.textContent = "Chapter text"; prose.required = true; prose.maxLength = 100000; prose.rows = 16; prose.value = previous?.markdown || ""; proseLabel.append(prose);
  const selectedSources = new Set(previous?.details.sourceKeys || []);
  const references = document.createElement("fieldset"), legend = document.createElement("legend"); legend.textContent = "References (optional)"; references.append(legend);
  const save = document.createElement("button"), cancel = document.createElement("button"), status = document.createElement("p"), buttons = document.createElement("div");
  save.type = "submit"; save.className = "primary-button"; save.textContent = previous ? "Save new chapter version" : "Save chapter";
  cancel.type = "button"; cancel.className = "quiet-button"; cancel.textContent = "Cancel"; cancel.onclick = () => {host.hidden = true; if (!previous) {if (composer) composer.hidden = false; if (create) create.hidden = false; composer?.querySelector(".editorial-creation-panel")?.setAttribute("hidden", "");}syncNovelEmptyState();};
  status.setAttribute("role","status"); buttons.className = "model-control-row"; buttons.append(save,cancel); host.append(titleLabel,proseLabel,references,buttons,status);
  void allAssets(gameId).then(assets=>{
    if(epoch !== routeEpoch || !host.isConnected) return;
    const available = assets.filter(a=>a.metadata?.extra?.relationshipRole === "finished" && !a.lineageWarning);
    if (!available.length) {references.hidden = true; return;}
    for (const asset of available) {
      const label = document.createElement("label"), check = document.createElement("input"); check.type = "checkbox"; check.value = asset.key; check.checked = selectedSources.has(asset.key); check.onchange = () => {if(check.checked)selectedSources.add(asset.key);else selectedSources.delete(asset.key);};
      label.append(check,document.createTextNode(asset.metadata?.title || asset.name)); references.append(label);
    }
  }).catch(()=>{references.hidden = true;});
  let pending = null;
  host.onsubmit = async event => {
    event.preventDefault(); save.disabled = true;
    try {
      pending ||= {gameId,title:title.value.trim(),markdown:prose.value.trim(),sourceKeys:[...selectedSources],
        operationId:crypto.randomUUID().replaceAll("-",""),previousChapterId:previous?.id || null};
      for (const control of host.querySelectorAll("input,textarea,button")) control.disabled = true;
      const result = await api("/novel-chapters", {}, {body:pending});
      if (epoch !== routeEpoch || gameId !== state.gameId) return;
      host.hidden = true; navigate(`${gamePath("novel")}/${result.chapterId}`);
    } catch(error) {
      if (epoch !== routeEpoch) return;
      status.textContent = error.message;
      if(error.status === 400 || error.status === 409) {pending = null; for(const c of host.querySelectorAll("input,textarea,button"))c.disabled = false;}
      else {save.disabled = false; save.textContent = "Retry save";cancel.disabled = false;}
    }
  };
  syncNovelEmptyState();
  title.focus();
}

function syncNovelEmptyState() {
  const empty=document.getElementById('novel-empty-state'),panel=document.querySelector('#editorial-novel-composer .editorial-creation-panel'),form=panel?.querySelector('form');
  const editing=!document.getElementById('manual-chapter-form').hidden||Boolean(panel&&!panel.hidden&&form&&!form.hidden);
  if(empty)empty.hidden=editing||Boolean(panel&&!panel.hidden&&panel.querySelector(".editorial-project-progress"));
  const action=document.querySelector('#novel .explorer-heading [data-generation-action]');
  if(action)action.hidden=editing||Boolean(currentChapter);
}

function renderNovelEmptyState() {
  const empty=document.createElement('section');empty.id='novel-empty-state';empty.className='novel-empty-state';empty.setAttribute('aria-label','Create your first chapter');
  const heading=document.createElement('h2');heading.textContent='Create your first chapter';
  const purpose=document.createElement('p');purpose.textContent='Turn recorded sessions into story chapters you can read and collect into books—or start a new story from a prompt. Transcripts are optional.';
  const generate=document.createElement('button');generate.type='button';generate.className='primary-button';generate.textContent='Generate chapter';
  const examples=document.createElement('div');examples.className='novel-prompt-examples';
  const label=document.createElement('p');label.textContent='Try a prompt';examples.append(label);
  const start=async(prompt='')=>{
    for(const button of empty.querySelectorAll('button'))button.disabled=true;
    try {
      await document.querySelector('#novel .explorer-heading [data-generation-action]').onclick();
      syncNovelEmptyState();
      const brief=document.querySelector('#editorial-novel-composer textarea');
      if(brief){if(prompt){brief.value=prompt;brief.dispatchEvent(new Event('input',{bubbles:true}));}brief.focus();}
    } finally {for(const button of empty.querySelectorAll('button'))button.disabled=false;}
  };
  generate.onclick=()=>void start();
  for(const prompt of ['Turn the selected session into a chapter with vivid scenes and natural dialogue.','Retell the session from one character’s point of view.','Write an original opening chapter for an adventure in this game.']){
    const example=document.createElement('button');example.type='button';example.className='quiet-button';example.textContent=prompt;example.onclick=()=>void start(prompt);examples.append(example);
  }
  empty.append(heading,purpose,generate,examples);novel.list.append(empty);syncNovelEmptyState();
}

async function loadNovel(chapterId, epoch) {
  document.getElementById("manual-chapter-form").hidden = true;
  document.getElementById("manual-chapter-edit")?.remove();
  renderEditorialComposer("novel",epoch);
  const composer = document.getElementById("editorial-novel-composer");
  composer.hidden=Boolean(chapterId);
  const create = document.querySelector("#novel .explorer-heading [data-generation-action]");
  if (create) create.hidden = true;
  const gameId = state.gameId;
  const current = () => epoch === routeEpoch && state.gameId === gameId && state.tokens;
  const loading = showLoading(novel.status, "Fetching the chapter list…");
  novel.status.hidden = false;
  try {
    const chapters = [];
    let cursor;
    const seenCursors = new Set();
    do {
      const page = await api("/novel", {gameId, cursor});
      if (!current()) return;
      chapters.push(...page.chapters);
      loading.update(`Found ${chapters.length} chapters · fetching remaining editions…`);
      cursor = page.cursor;
      if (chapters.length > 5000 || seenCursors.size >= 200 || (cursor && seenCursors.has(cursor))) {
        throw new Error("The chapter library could not be loaded completely. No partial list is shown; refresh to retry.");
      }
      if (cursor) seenCursors.add(cursor);
    } while (cursor);
    loading.update("Reading story and book organization…");
    const organization = await novelOrganization(gameId,current);
    if (!organization || !current()) return;
    const byKey = new Map(chapters.filter(c=>c.assetKey).map(c=>[c.assetKey,c]));
    const bookId = new URLSearchParams(location.search).get("book");
    let selectedBook = bookId ? organization.books.find(b=>b.id===bookId) : null;
    if (bookId && !selectedBook) throw new Error("The selected book is unavailable");
    const bookRevision = new URLSearchParams(location.search).get("bookRevision");
    if(bookRevision){if(!bookId || !/^[a-f0-9]{32}$/.test(bookRevision))throw new Error("Invalid book revision");
      selectedBook=(await api("/novel-books",{gameId,id:bookId,revision:bookRevision})).record;
      if(!current())return;
      if(!selectedBook || selectedBook.id!==bookId || selectedBook.gameId!==gameId || selectedBook.revision!==bookRevision)throw new Error("Book revision unavailable");}
    currentNovelBook = selectedBook;
    // A session can have multiple immutable editions; only the latest appears in the TOC.
    chapters.sort((a, b) => b.createdAt - a.createdAt || b.id.localeCompare(a.id));
    const sessions = new Map();
    for (const chapter of chapters) {
      if (!sessions.has(chapter.sessionId)) sessions.set(chapter.sessionId, []);
      sessions.get(chapter.sessionId).push(chapter);
    }
    const ordered = selectedBook ? selectedBook.volumes.flatMap(v=>v.chapterKeys.map(k=>byKey.get(k)).filter(Boolean)) : [...sessions.values()].sort((a, b) => a.at(-1).createdAt - b.at(-1).createdAt || a[0].sessionId.localeCompare(b[0].sessionId)).map(v => v[0]);
    if (!chapterId) {
      const saved = savedNovelProgress();
      if (saved && chapters.some(c=>c.id===saved.chapterId)) {
        const link = novelLink(`Resume ${chapters.find(c=>c.id===saved.chapterId).title} · ${saved.percent}% · saved on this device`,saved.chapterId,saved.bookId);
        if(saved.bookId && saved.bookRevision)link.href += `&bookRevision=${encodeURIComponent(saved.bookRevision)}`;
        novel.resume.append(link); novel.resume.hidden = false;
      }
      if (selectedBook) {
        if(create)create.hidden=Boolean(composer.querySelector(".editorial-creation-panel:not([hidden]) form:not([hidden])"));
        novel.list.append(bookCard(selectedBook,organization.stories.find(s=>s.id===selectedBook.storyId),byKey,current));
        for(const volume of selectedBook.volumes) {
          const section=document.createElement("section"), heading=document.createElement("h2"), list=document.createElement("ol"); heading.textContent=volume.title;
          for(const key of volume.chapterKeys){const chapter=byKey.get(key), item=document.createElement("li"); if(chapter)item.append(bookLink(chapter.title,selectedBook,chapter.id));else item.textContent="Pinned chapter unavailable";list.append(item);}
          section.append(heading,list);novel.list.append(section);
        }
        const publication=document.createElement("p");publication.textContent="Approval selects a private reading edition. It does not publish the book publicly or establish campaign canon.";novel.list.append(publication);
        if(selectedBook.relatedAssetKeys.length){const related=document.createElement("nav");related.setAttribute("aria-label","Related book assets");for(const key of selectedBook.relatedAssetKeys){related.append(assetLink({key}),document.createTextNode(" · "));}novel.list.append(related);}
        novel.status.hidden=true;void novelCovers(gameId,current);return;
      }
      for(const story of organization.stories){const books=organization.books.filter(b=>b.storyId===story.id).sort((a,b)=>a.order-b.order||a.id.localeCompare(b.id));
        const section=document.createElement("section"), heading=document.createElement("h2"), synopsis=document.createElement("p");heading.textContent=story.title;synopsis.textContent=story.synopsis;section.append(heading,synopsis);
        for(const book of books)section.append(bookCard(book,story,byKey,current));if(!books.length){const empty=document.createElement("p");empty.textContent="No books organized yet.";section.append(empty);}novel.list.append(section);}
      if(organization.books.some(b=>!organization.stories.some(s=>s.id===b.storyId)))throw new Error("A book's parent story is unavailable; no incomplete library is shown");
      if(ordered.length&&organization.stories.length){const sourceHeading=document.createElement("h2");sourceHeading.textContent="Session chapters";novel.list.append(sourceHeading);}
      novel.status.hidden = true;
      novel.status.textContent = "";
      if(!ordered.length&&!organization.stories.length)renderNovelEmptyState();
      if(create)create.hidden=Boolean(composer.querySelector(".editorial-creation-panel:not([hidden]) form:not([hidden])"));
      for (const [index, chapter] of ordered.entries()) {
        const card = document.createElement("div"); card.className = "novel-card";
        const number = document.createElement("p"); number.className = "eyebrow"; number.textContent = `Chapter ${index + 1}`;
        const title = document.createElement("h2"); title.append(novelLink(chapter.title, chapter.id));
        const meta = document.createElement("p"); meta.textContent = `${chapterDate(chapter)}${chapter.publicationStatus === "accepted-with-notes" ? " · Working draft" : ""}`;
        card.append(number, title, meta); novel.list.append(card);
      }
      void novelCovers(gameId,current);
      return;
    }
    loading.update("Reading the selected chapter…");
    const chapter = await api("/novel-chapter", {gameId, chapterId});
    if (!current()) return;
    currentChapter = chapter;
    if(selectedBook && !ordered.some(c=>c.id===chapter.id))throw new Error("This chapter edition is not selected in the book");
    novel.title.textContent = chapter.title;
    proseMarkdown(novel.prose, chapter.markdown);
    chapterDetails(chapter, sessions.get(chapter.sessionId) || [chapter]);
    if (chapter.details?.authorship === "human") {
      const edit = document.createElement("button"); edit.type = "button"; edit.className = "quiet-button"; edit.textContent = "Edit chapter"; edit.id = "manual-chapter-edit"; edit.onclick = () => manualChapterEditor(chapter); document.querySelector("#novel-reader .novel-tools").append(edit);
      if (chapter.details.previousChapterId) novel.details.append(novelLink("Previous chapter version",chapter.details.previousChapterId));
    }
    novel.notice.textContent = [chapter.notice,
      chapter.publicationStatus === "accepted-with-notes" ? "Working draft · AI review left unresolved notes. See Details." : "",
      selectedBook ? selectedBook.title : "",
      sessions.get(chapter.sessionId)?.[0].id !== chapter.id ? "You are reading an earlier version. See Details for the latest." : "",
    ].filter(Boolean).join(" ");
    novel.notice.hidden = !novel.notice.textContent;
    novelView(false);
    novel.reader.hidden = false;
    novel.status.hidden = true;
    novelIllustrations(chapter,current);
    readingProgress(chapter,selectedBook,current);
    // Link enrichment is optional: a catalog outage must not prevent reading the manuscript.
    proseMarkdown(novel.prose, chapter.markdown, narrativeReferences(chapter, [], chapters));
    const collectionIds=[...new Set((chapter.readerReferences?.schemaVersion===1 && Array.isArray(chapter.readerReferences.mentions) && chapter.readerReferences.mentions.length<=200 ? chapter.readerReferences.mentions : [])
      .filter(m=>m?.target?.type==="collection" && (!m.target.gameId || m.target.gameId===gameId) && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(m.target.id)).map(m=>m.target.id))];
    const collectionReferences=(async()=>{const records=[];for(let offset=0;offset<collectionIds.length;offset+=8){if(!current())return records;const batch=await Promise.all(collectionIds.slice(offset,offset+8).map(id=>api("/video-collections",{gameId,id,metadataOnly:"true"}).then(r=>r.collection).catch(()=>null)));records.push(...batch.filter(Boolean));}return records;})();
    void Promise.all([allAssets(gameId),collectionReferences]).then(([assets,collections]) => {
      if (current()) proseMarkdown(novel.prose, chapter.markdown, narrativeReferences(chapter, assets, chapters,collections));
    }).catch(() => {
      if (current()) { novel.status.hidden = false; novel.status.textContent = "Some asset links could not be loaded. The story is available; Reload the page to try again."; }
    });
    const index = ordered.findIndex(c => selectedBook ? c.id === chapter.id : c.sessionId === chapter.sessionId);
    if (index > 0) novel.pagination.append(novelLink(`← ${ordered[index - 1].title}`, ordered[index - 1].id,selectedBook?.id));
    if (index >= 0 && index < ordered.length - 1) novel.pagination.append(novelLink(`${ordered[index + 1].title} →`, ordered[index + 1].id,selectedBook?.id));
  } catch (error) {
    if (!current()) return;
    novel.status.hidden = false;
    novel.list.replaceChildren();
    novel.status.textContent = `${error.message}. Use Reload the page to try again.`;
    if(create)create.hidden=Boolean(chapterId)||Boolean(composer.querySelector(".editorial-creation-panel:not([hidden]) form:not([hidden])"));
  }
}

let assetIndex = null;
function sameGameKey(key) {
  return typeof key === "string" && key.startsWith(`games/${state.gameId}/assets/`)
    && !key.split("/").includes("..") && !/[\x00-\x1f]/.test(key);
}

function clearLibrary() {
  document.getElementById('episode-workspace')?.stopEditing?.();
  for(const host of document.querySelectorAll("[data-multi-filter]"))window.PantherUI.unmountMultiSelect?.(host);
  for(const native of document.querySelectorAll('#episode-workspace select[data-react-select]'))window.PantherUI.destroySelect(native);
  document.getElementById("movie-workspace").replaceChildren();
  document.getElementById("movie-workspace").hidden = true;
  document.getElementById("session-library").hidden = true;
  document.getElementById("library-list").replaceChildren();
  document.getElementById("library-list").hidden = false;
  document.getElementById("library-status").hidden = false;
  if (!state.tokens) {
    assetIndex = null; videoPlaylist = null;
    videoLibraryView = {gameId:null,search:"",tags:[],characters:[],collection:""};
  }
}

async function allAssets(gameId, onProgress = () => {}, section = "all") {
  if (assetIndex?.gameId === gameId && assetIndex.section === section) {
    const entry = assetIndex; entry.listeners.add(onProgress); onProgress(entry.count);
    try { return await entry.promise; } finally { entry.listeners.delete(onProgress); }
  }
  const entry = {gameId, section, count:0, listeners:new Set([onProgress])};
  entry.promise = (async () => {
    const assets = []; let cursor = null; const seen = new Set();
    do {
      const page = await api("/assets", {gameId, cursor, section});
      if (!Array.isArray(page.assets)) throw new Error("Asset catalog unavailable");
      assets.push(...page.assets);
      entry.count = assets.length;
      for (const listener of entry.listeners) listener(entry.count);
      if (assets.length > 5000) throw new Error("Catalog exceeds this reader's limit; incomplete results are not displayed.");
      cursor = page.cursor;
      if (cursor && (seen.has(cursor) || seen.size >= 200)) throw new Error("Catalog exceeds this reader's limit; incomplete results are not displayed.");
      if (cursor) seen.add(cursor);
    } while (cursor);
    return assets;
  })().catch(error => { if (assetIndex === entry) assetIndex = null; throw error; });
  assetIndex = entry;
  try { return await entry.promise; } finally { entry.listeners.delete(onProgress); }
}

function assetLink(asset, label) {
  const link = document.createElement("a");
  link.href = `${gamePath("media")}?asset=${encodeURIComponent(asset.key)}`;
  link.textContent = label || asset.metadata?.title || asset.name || asset.key.split("/").at(-1);
  link.title = asset.key;
  link.addEventListener("click", event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); void previewFile({key: asset.key, name: link.textContent, size: asset.size});
  });
  return link;
}

let videoLibraryView = {gameId:null, search:"", tags:[], characters:[], collection:""};
let videoPlaylist = null;
function sceneMapPicker(gameId, selectedKey, current, onChange = () => {}) {
  const host=document.createElement('section');host.className='scene-map-picker';
  const label=document.createElement('label'),caption=document.createElement('span'),select=document.createElement('select');
  caption.textContent='Map image';select.setAttribute('aria-label','Map image');select.add(new Option('Choose a map','none'));
  if(selectedKey)select.add(new Option('Selected map',selectedKey));select.value=selectedKey||'none';label.append(caption,select);
  const image=document.createElement('img'),status=document.createElement('p'),more=document.createElement('button');
  image.alt='Selected map';image.hidden=true;status.setAttribute('role','status');more.type='button';more.className='quiet-button';more.textContent='More images';more.hidden=true;
  host.append(label,image,status,more);window.PantherUI.enhanceSelect(select,'Map image');
  let started=false,cursor=null,generation=0;const seen=new Set();
  const active=()=>current()&&host.isConnected;
  const value=()=>select.value==='none'?null:select.value;
  async function preview(){const request=++generation;image.hidden=true;image.removeAttribute('src');if(!value())return;
    try{const result=await api('/object-url',{key:value()});if(!active()||request!==generation)return;if(!result.url||!/^image\/(png|jpeg|webp)$/.test(result.contentType||''))throw new Error('Map image unavailable');const option=[...select.options].find(option=>option.value===value());if(option&&result.metadata?.title)option.textContent=result.metadata.title;image.src=result.url;image.hidden=false;}
    catch(error){if(active()&&request===generation)status.textContent=error.message;}
  }
  select.onchange=()=>{status.textContent='';void preview();onChange(value());};
  image.onerror=()=>{image.hidden=true;status.textContent='Map preview unavailable.';};
  async function load(){if(!active())return;more.disabled=true;showLoading(status,'Loading images…');
    try{const result=await api('/assets',{gameId,section:'all',cursor});if(!active())return;
      for(const asset of result.assets||[]){if(!sameGameKey(asset.key)||!/^image\/(png|jpeg|webp)$/.test(asset.contentType||'')||asset.lineageWarning||['processing','intermediate','internal'].includes(asset.metadata?.extra?.relationshipRole)||['provenance','migration-report','audit-report','generation-metadata'].includes(asset.kind)||asset.kind?.startsWith('editorial-')||asset.kind?.includes('provenance'))continue;
        const title=asset.metadata?.title||asset.name||asset.key.split('/').at(-1),existing=[...select.options].find(option=>option.value===asset.key);if(existing)existing.textContent=title;else select.add(new Option(title,asset.key));
      }
      cursor=result.cursor||null;if(cursor&&(seen.has(cursor)||seen.size>=200))throw new Error('Image catalog pagination is unavailable.');if(cursor)seen.add(cursor);
      more.hidden=!cursor;more.disabled=false;status.textContent=select.options.length===1&&!cursor?'No images yet. Add a map in Assets.':'';
    }catch(error){if(active()){status.textContent=error.message;more.hidden=false;more.disabled=false;more.textContent='Retry loading images';}}
  }
  more.onclick=()=>void load();
  return {host,value,select,start(){if(started)return;started=true;void load();void preview();}};
}
function renderEpisodeWorkspace(epoch) {
  const gameId=state.gameId, parent=document.getElementById('session-library');
  let host=document.getElementById('episode-workspace');
  if(!host){host=document.createElement('section');host.id='episode-workspace';host.setAttribute('aria-label','Episodes and scenes');parent.querySelector('.explorer-heading').after(host);}
  host.hidden=false;
  if(host.dataset.key===`${gameId}:${epoch}`)return;
  for(const native of host.querySelectorAll('select[data-react-select]'))window.PantherUI.destroySelect(native);host.stopPreview?.();host.dataset.key=`${gameId}:${epoch}`;host.replaceChildren();
  const current=()=>state.gameId===gameId&&epoch===routeEpoch&&host.isConnected;
  const button=(text,action,primary=false)=>{const node=document.createElement('button');node.type='button';node.textContent=text;node.className=primary?'primary-button':'quiet-button';node.onclick=action;return node;};
  const episodes=[],scenes=[];let selectedEpisode=null,selectedScene=null,sceneGeneration=0;
  const toolbar=document.createElement('div'),heading=document.createElement('h2'),episodeCards=document.createElement('div'),episodeStatus=document.createElement('p'),editor=document.createElement('div'),detail=document.createElement('section');
  toolbar.className='episode-toolbar';heading.textContent='Episodes';episodeCards.className='episode-cards';episodeStatus.setAttribute('role','status');episodeStatus.dataset.episodeEmpty='true';detail.className='episode-detail';detail.hidden=true;
  const create=button('Create episode',()=>edit('episode'),true);create.id='episode-create-action';parent.querySelector('#episode-create-action')?.remove();parent.querySelector('.explorer-heading').append(create);toolbar.append(heading);host.append(toolbar,editor,episodeStatus,episodeCards,detail);
  const params=()=>new URLSearchParams(location.search);
  const updateURL=(episodeId,sceneId)=>{const url=new URL(location.href);for(const [name,value] of Object.entries({episode:episodeId,scene:sceneId,view:null,series:null,episodeRevision:null})){if(value)url.searchParams.set(name,value);else url.searchParams.delete(name);}history.replaceState(null,'',url);};
  const clearEditor=()=>{for(const dialog of editor.querySelectorAll('dialog'))if(dialog.open)dialog.close();for(const native of editor.querySelectorAll('select[data-react-select]'))window.PantherUI.destroySelect(native);editor.replaceChildren();};
  const back=button('Back to episodes',()=>{clearEditor();host.stopPreview();selectedEpisode=null;selectedScene=null;detail.hidden=true;host.dataset.view='library';back.hidden=true;updateURL(null,null);drawEpisodes();});back.classList.add('episode-back');detail.before(back);back.hidden=true;
  host.stopEditing=clearEditor;
  const automaticPlans=document.createElement('section');automaticPlans.id='session-video-plans';automaticPlans.hidden=true;host.append(automaticPlans);
  void api('/editorial-jobs',{gameId}).then(result=>{
    if(!current())return;
    const jobs=(result.jobs||[]).filter(job=>!job.creation&&job.sessionId);
    if(!jobs.length)return;
    automaticPlans.hidden=false;const heading=document.createElement('h2');heading.textContent='Session plans';automaticPlans.append(heading);
    for(const job of jobs){const progress=document.createElement('section');progress.className='editorial-project-progress';const title=`Session ${job.sessionId} · automatic`;const review=optionalInfoDialog(title,progress,()=>void showEditorialProgress(job.jobId,progress,gameId,'video'));automaticPlans.append(review.host);}
  }).catch(()=>{/* Workflow navigation remains available if this optional list cannot be read. */});

  function edit(kind,record=null){
    const parentEpisode=selectedEpisode,returnFocus=document.activeElement;clearEditor();const dialog=document.createElement('dialog'),dialogHeading=document.createElement('h2');dialog.className='episode-edit-dialog';dialogHeading.textContent=record?`Edit ${kind}`:kind==='episode'?'Create episode':'Add scene';dialog.setAttribute('aria-label',dialogHeading.textContent);dialog.append(dialogHeading);const form=document.createElement('form');form.className='episode-editor';form.setAttribute('aria-label',kind==='episode'?'Episode editor':'Scene editor');
    const label=(text,node)=>{const wrapper=document.createElement('label');wrapper.append(document.createTextNode(text),node);form.append(wrapper);return node;};
    const name=label(kind==='episode'?'Episode title':'Scene title',document.createElement('input'));name.required=true;name.maxLength=160;name.value=record?.name||'';
    const description=label('Description',document.createElement('textarea'));description.maxLength=4000;description.placeholder='Optional';description.value=record?.description||'';
    let type,map;if(kind==='scene'){type=label('Scene type',document.createElement('select'));for(const [value,text] of [['general','General'],['opener','Opener'],['map','Map'],['travel','Travel'],['action','Action'],['dialogue','Dialogue']])type.add(new Option(text,value));type.value=record?.type||'general';window.PantherUI.enhanceSelect(type,'Scene type');map=sceneMapPicker(gameId,record?.mapAssetKey,current);form.append(map.host);map.host.hidden=type.value!=='map';type.addEventListener('change',()=>{map.host.hidden=type.value!=='map';if(!map.host.hidden)map.start();});}
    const actions=document.createElement('div'),save=button(record?'Save changes':kind==='episode'?'Create episode':'Add scene',null,true),cancel=button('Cancel',()=>clearEditor()),status=document.createElement('p');save.type='submit';status.setAttribute('role','status');actions.append(save,cancel);actions.className='episode-form-actions';form.append(actions,status);dialog.append(form);editor.append(dialog);dialog.addEventListener('close',()=>{for(const native of dialog.querySelectorAll('select[data-react-select]'))window.PantherUI.destroySelect(native);dialog.remove();if(returnFocus?.isConnected)returnFocus.focus({preventScroll:true});});dialog.showModal();name.focus();let pending=null;
    if(map&&!map.host.hidden)map.start();
    form.onsubmit=async event=>{event.preventDefault();pending||={gameId,id:record?.id||`${kind}-${crypto.randomUUID().slice(0,8)}`,name:name.value.trim(),description:description.value.trim(),expectedRevision:record?.revision||null,operationId:crypto.randomUUID().replaceAll('-',''),...(kind==='scene'?{episodeId:parentEpisode.id,type:type.value,mapAssetKey:type.value==='map'?map.value():null,selectedOutputKey:record?.selectedOutputKey||null}:{sceneIds:record?.sceneIds||[]})};save.disabled=true;for(const control of form.querySelectorAll('input,textarea,select'))control.disabled=true;
      try{const response=await api(kind==='episode'?'/episodes':'/scenes',{},{body:pending});if(!current()||!form.isConnected||(kind==='scene'&&selectedEpisode?.id!==parentEpisode?.id))return;const saved=response.record;clearEditor();
        if(kind==='episode'){const index=episodes.findIndex(item=>item.id===saved.id);if(index<0)episodes.unshift(saved);else episodes[index]=saved;drawEpisodes();await chooseEpisode(saved);}
        else {if(response.episodeRecord){selectedEpisode=response.episodeRecord;const parentIndex=episodes.findIndex(item=>item.id===selectedEpisode.id);episodes[parentIndex]=selectedEpisode;drawEpisodes();}const index=scenes.findIndex(item=>item.id===saved.id);if(index<0)scenes.push(saved);else scenes[index]=saved;drawScenes();drawPlayback();chooseScene(saved);}
      }catch(error){if(current()){status.textContent=error.message;save.disabled=error.status===409;if(error.status===400){pending=null;for(const control of form.querySelectorAll('input,textarea,select'))control.disabled=false;}save.textContent=error.status===409?'Reopen to edit':'Retry save';}}
    };
  }
  function drawEpisodes(){host.dataset.hasEpisodes=String(episodes.length>0);episodeStatus.hidden=episodes.length>0||Number(host.dataset.videoAssetCount)>0;if(episodes.length&&episodeStatus.textContent==='Create your first episode.')episodeStatus.textContent='';episodeCards.replaceChildren();for(const episode of episodes){if(host.videoSearch&&!`${episode.name} ${episode.description||''}`.toLowerCase().includes(host.videoSearch.toLowerCase()))continue;const card=button(episode.name,()=>void chooseEpisode(episode));card.className='episode-card';card.setAttribute('aria-label',episode.name);const name=document.createElement('strong'),count=document.createElement('span');name.textContent=episode.name;count.textContent=`${episode.sceneIds?.length||0} ${episode.sceneIds?.length===1?'scene':'scenes'}`;card.replaceChildren(name,count);card.setAttribute('aria-pressed',String(selectedEpisode?.id===episode.id));episodeCards.append(card);}}
  host.filterEpisodes=value=>{host.videoSearch=value;drawEpisodes();};
  let sceneCards,sceneStatus,sceneDetail,sceneMore,previewHost,scenesComplete=false,mutationPending=false,mutationUncertain=false,previewGeneration=0,playbackView=0;
  const orderedScenes=()=>Array.isArray(selectedEpisode?.sceneIds)?selectedEpisode.sceneIds.map(id=>scenes.find(scene=>scene.id===id)):[];
  const finishedVideo=asset=>sameGameKey(asset.key)&&asset.contentType?.startsWith('video/')&&asset.metadata?.extra?.relationshipRole==='finished';
  host.stopPreview=()=>{previewGeneration++;const video=previewHost?.querySelector('video');if(video){video.pause();video.removeAttribute('src');video.load();}for(const dialog of previewHost?.querySelectorAll('dialog[open]')||[])dialog.close();};
  async function saveOrder(ids){if(mutationPending)return;mutationPending=true;host.stopPreview();drawScenes();const episode=selectedEpisode;try{const result=await api('/episodes',{},{body:{gameId,id:episode.id,name:episode.name,description:episode.description||'',sceneIds:ids,expectedRevision:episode.revision,operationId:crypto.randomUUID().replaceAll('-','')}});if(!current()||selectedEpisode.id!==episode.id)return;selectedEpisode=result.record;episodes[episodes.findIndex(item=>item.id===episode.id)]=result.record;sceneStatus.textContent='Order saved.';}catch(error){if(current()&&selectedEpisode?.id===episode.id){mutationUncertain=true;const reconcile=async()=>{try{await window.PantherUI.invalidate(apiScope(),['/episodes','/episode-composition'],gameId);const result=await api('/episodes',{gameId,id:episode.id});if(!result.record||result.record.id!==episode.id||!Array.isArray(result.record.sceneIds))throw new Error('Episode unavailable');if(!current()||selectedEpisode.id!==episode.id)return;selectedEpisode=result.record;episodes[episodes.findIndex(item=>item.id===episode.id)]=result.record;mutationUncertain=false;sceneStatus.textContent=JSON.stringify(result.record.sceneIds)===JSON.stringify(ids)?'Order saved.':'Order changed; review it before moving scenes again.';drawScenes();drawPlayback();}catch(readError){if(current()){sceneStatus.textContent=`Order could not be confirmed: ${readError.message}`;sceneStatus.append(button('Check saved order',()=>void reconcile()));}}};await reconcile();}}finally{mutationPending=false;if(current()){drawEpisodes();drawScenes();drawPlayback();}}}
  async function selectOutput(asset){if(mutationPending)return;mutationPending=true;host.stopPreview();const scene=selectedScene;drawOutputs();try{const result=await api('/scenes',{},{body:{gameId,id:scene.id,episodeId:scene.episodeId,name:scene.name,description:scene.description||'',type:scene.type||'general',selectedOutputKey:asset.key,expectedRevision:scene.revision,operationId:crypto.randomUUID().replaceAll('-','')}});if(!current()||selectedEpisode?.id!==scene.episodeId)return;scenes[scenes.findIndex(item=>item.id===scene.id)]=result.record;if(selectedScene?.id===scene.id)selectedScene=result.record;sceneStatus.textContent='Selected for this episode.';}catch(error){if(current()&&selectedEpisode?.id===scene.episodeId){mutationUncertain=true;const reconcile=async()=>{try{await window.PantherUI.invalidate(apiScope(),['/scenes','/episode-composition'],gameId);const result=await api('/scenes',{gameId,episodeId:scene.episodeId,id:scene.id});if(!result.record||result.record.id!==scene.id||result.record.episodeId!==scene.episodeId)throw new Error('Scene unavailable');if(!current()||selectedEpisode?.id!==scene.episodeId)return;scenes[scenes.findIndex(item=>item.id===scene.id)]=result.record;if(selectedScene?.id===scene.id)selectedScene=result.record;mutationUncertain=false;sceneStatus.textContent=result.record.selectedOutputKey===asset.key?'Selected for this episode.':'Selection changed; review it before choosing again.';drawOutputs();drawScenes();drawPlayback();}catch(readError){if(current()){sceneStatus.textContent=`Selection could not be confirmed: ${readError.message}`;sceneStatus.append(button('Check saved selection',()=>void reconcile()));}}};await reconcile();}}finally{mutationPending=false;if(current()){drawOutputs();drawScenes();drawPlayback();}}}
  function drawPlayback(){if(!previewHost||!selectedEpisode)return;host.stopPreview();previewHost.replaceChildren();const view=++playbackView;let ordered=orderedScenes();const missing=ordered.filter(scene=>!scene?.selectedOutputKey).length;const label=document.createElement('p');label.className='episode-preview-status';label.setAttribute('role','status');const start=button('Preview episode',()=>void begin(),true);start.disabled=mutationPending||mutationUncertain||!scenesComplete||!ordered.length||!!missing||ordered.length!==scenes.length;start.title=!scenesComplete?'Loading scenes':missing?`${missing} ${missing===1?'scene needs':'scenes need'} a video`:!ordered.length?'Add a scene first':ordered.length!==scenes.length?'Scene order is incomplete':'Play selected videos in scene order';label.hidden=true;previewHost.append(start,label);if(scenesComplete&&ordered.length&&!missing&&ordered.length===scenes.length){const episode=selectedEpisode;void api('/episode-composition',{gameId,episodeId:episode.id,revision:episode.revision}).then(composition=>{if(!current()||view!==playbackView)return;if(!composition.ready){start.disabled=true;label.textContent='One or more selected videos are unavailable.';return;}for(const asset of host.sceneAssets||[]){const extra=asset.metadata?.extra;if(finishedVideo(asset)&&extra?.episodeRef?.episodeId===episode.id&&extra.compositionHash===composition.compositionHash)previewHost.append(assetLink(asset,'Play episode'));}}).catch(error=>{if(current()&&view===playbackView){start.disabled=true;label.textContent=`Episode unavailable: ${error.message}`;}});}
    async function begin(){const generation=++previewGeneration;start.disabled=true;try{const composition=await api('/episode-composition',{gameId,episodeId:selectedEpisode.id,revision:selectedEpisode.revision});if(!current()||generation!==previewGeneration)return;if(!composition.ready||composition.scenes.length!==ordered.length)throw new Error('Selected videos are incomplete');ordered=composition.scenes.map(item=>({...item.scene,selectedOutputKey:item.assetKey}));}catch(error){if(current()&&generation===previewGeneration){label.textContent=`Preview unavailable: ${error.message}`;label.hidden=false;start.disabled=false;}return;}for(const previous of previewHost.querySelectorAll('video')){previous.pause();previous.remove();}const playbackDialog=document.createElement('dialog'),playbackHeader=document.createElement('header'),playbackTitle=document.createElement('h2'),closePlayback=button('Close',()=>playbackDialog.close());playbackDialog.className='episode-playback-dialog';playbackDialog.setAttribute('aria-label','Episode preview');playbackTitle.textContent=selectedEpisode.name;playbackHeader.append(playbackTitle,closePlayback);playbackDialog.append(playbackHeader,label);label.hidden=false;previewHost.append(playbackDialog);playbackDialog.showModal();playbackDialog.onclose=()=>{video.pause();video.removeAttribute('src');video.load();if(playbackDialog.isConnected){previewGeneration++;label.hidden=true;playbackDialog.parentElement.append(label);playbackDialog.remove();start.disabled=false;if(start.isConnected&&!start.closest('[hidden]'))start.focus({preventScroll:true});}};const video=document.createElement('video');video.controls=true;video.playsInline=true;video.preload='metadata';video.setAttribute('aria-label','Episode preview');playbackDialog.append(video);let index=0;const active=()=>current()&&generation===previewGeneration&&video.isConnected;const fail=message=>{if(!active())return;video.pause();label.textContent=message;label.hidden=false;start.disabled=false;video.onended=null;};const next=async()=>{const scene=ordered[index];label.textContent=`Preview · ${index+1} of ${ordered.length} · ${scene.name}`;try{const result=await api('/object-url',{key:scene.selectedOutputKey});if(!active())return;if(!result.url||!result.contentType?.startsWith('video/'))throw new Error('Selected video unavailable');video.src=result.url;await video.play();}catch(error){fail(`Preview stopped at ${scene.name}: ${error.message}`);}};video.onerror=()=>fail(`Preview stopped at ${ordered[index].name}: video could not be played.`);video.onended=()=>{if(!active())return;if(++index<ordered.length)void next();else{label.textContent='Preview complete.';start.disabled=false;}};await next();}
  }
  const drawOutputs=()=>{const output=sceneDetail?.querySelector('.scene-output-list');if(!output||!selectedScene)return;output.replaceChildren();
    const assets=(host.sceneAssets||[]).filter(asset=>{const ref=asset.metadata?.extra?.sceneRef;return finishedVideo(asset)&&ref?.episodeId===selectedEpisode.id&&ref?.sceneId===selectedScene.id;});
    if(!assets.length)return;const heading=document.createElement('h4');heading.textContent='Videos';output.append(heading);
    for(const asset of assets){const row=document.createElement('p');row.className='scene-output-row';row.append(assetLink(asset));const use=button(asset.key===selectedScene.selectedOutputKey?'Selected':'Use in episode',()=>void selectOutput(asset));use.disabled=mutationPending||mutationUncertain||asset.key===selectedScene.selectedOutputKey;use.setAttribute('aria-label',`${use.textContent}: ${asset.metadata?.title||asset.name}`);row.append(use);if(asset.metadata.extra.sceneRef.revision!==selectedScene.revision){const note=document.createElement('small');note.textContent=' · Earlier scene version';row.append(note);}output.append(row);}
  };
  host.updateOutputs=assets=>{host.sceneAssets=assets;drawOutputs();if(!previewHost?.querySelector('video'))drawPlayback();};
  function drawScenes(){sceneCards.replaceChildren();for(const [index,scene] of orderedScenes().entries()){const row=document.createElement('div');row.className='scene-order-row';if(!scene){row.textContent='Scene unavailable';sceneCards.append(row);continue;}const card=button(scene.name,()=>chooseScene(scene));card.className='scene-card';card.setAttribute('aria-label',scene.name);card.dataset.order=String(index+1)+'.';card.setAttribute('aria-pressed',String(selectedScene?.id===scene.id));const state=document.createElement('small');state.textContent=scene.selectedOutputKey?'Ready':scene.type&&scene.type!=='general'?scene.type[0].toUpperCase()+scene.type.slice(1):'Not rendered';const move=(direction)=>{const node=button(direction<0?'Move up':'Move down',()=>{const ids=[...selectedEpisode.sceneIds],next=index+direction;[ids[index],ids[next]]=[ids[next],ids[index]];void saveOrder(ids);});node.setAttribute('aria-label',`Move ${scene.name} ${direction<0?'up':'down'}`);node.textContent=direction<0?'↑':'↓';node.title=direction<0?'Move up':'Move down';node.classList.add('scene-move');node.disabled=mutationPending||mutationUncertain||!scenesComplete||index+direction<0||index+direction>=selectedEpisode.sceneIds.length;return node;};row.append(card,state,move(-1),move(1));sceneCards.append(row);}if(!scenes.length){const empty=document.createElement('p');empty.textContent='No scenes yet.';sceneCards.append(empty);}}
  function chooseScene(scene){clearEditor();selectedScene=scene;updateURL(selectedEpisode.id,scene.id);drawScenes();for(const native of sceneDetail.querySelectorAll('select[data-react-select]'))window.PantherUI.destroySelect(native);sceneDetail.replaceChildren();const heading=document.createElement('h3');heading.textContent=scene.name;const description=document.createElement('p');description.textContent=scene.description;description.hidden=!scene.description;
    const headingRow=document.createElement('header');headingRow.className='scene-editor-heading';headingRow.append(heading,button('Edit scene',()=>edit('scene',selectedScene)));
    const composer=document.createElement('section');composer.id='scene-video-composer';const work=document.createElement('section'),outputs=document.createElement('div');work.id='scene-work-progress';outputs.className='scene-output-list';sceneDetail.append(headingRow,description,composer,work,outputs);drawOutputs();
    openSceneVideoComposer({...scene,host:composer},epoch,saved=>{const index=scenes.findIndex(item=>item.id===saved.id);if(index>=0)scenes[index]=saved;if(selectedScene?.id===saved.id)selectedScene=saved;drawScenes();drawOutputs();drawPlayback();});
    void restoreSceneVideoProgress(scene,work,gameId,epoch);
  }
  async function chooseEpisode(episode,restoreScene=null){clearEditor();if(selectedEpisode?.id!==episode.id)mutationUncertain=false;selectedEpisode=episode;selectedScene=null;host.dataset.view='editor';back.hidden=false;host.stopPreview();const generation=++sceneGeneration;scenes.length=0;scenesComplete=false;updateURL(episode.id,restoreScene);drawEpisodes();detail.hidden=false;detail.replaceChildren();
    const toolbar=document.createElement('div'),title=document.createElement('h2'),description=document.createElement('p');toolbar.className='episode-toolbar';title.textContent=episode.name;toolbar.append(title,button('Add scene',()=>edit('scene'),true),button('Edit episode',()=>edit('episode',selectedEpisode)));description.textContent=episode.description;description.hidden=!episode.description;
    sceneCards=document.createElement('div');sceneCards.className='scene-cards';sceneStatus=document.createElement('p');sceneStatus.setAttribute('role','status');sceneDetail=document.createElement('section');sceneDetail.className='selected-scene';sceneMore=document.createElement('div');previewHost=document.createElement('section');previewHost.className='episode-preview';previewHost.setAttribute('aria-label','Episode playback');const layout=document.createElement('div'),scenesPanel=document.createElement('section'),scenesHeading=document.createElement('h3');layout.className='episode-editor-layout';scenesPanel.className='episode-scenes-panel';sceneDetail.classList.add('episode-scene-panel');scenesHeading.textContent='Scenes';scenesPanel.append(scenesHeading,sceneStatus,sceneCards,sceneMore);layout.append(scenesPanel,sceneDetail);toolbar.append(previewHost);detail.append(toolbar,description,layout);drawPlayback();
    const page=async cursor=>{showLoading(sceneStatus,'Loading scenes…');try{const result=await api('/scenes',{gameId,episodeId:episode.id,cursor});if(!current()||generation!==sceneGeneration)return;if(!Array.isArray(result.records))throw new Error('Scenes unavailable');scenes.push(...result.records);scenesComplete=!result.cursor;sceneStatus.textContent='';drawScenes();drawPlayback();sceneMore.replaceChildren();if(result.cursor)sceneMore.append(button('More scenes',()=>void page(result.cursor)));if(restoreScene){const scene=scenes.find(item=>item.id===restoreScene);if(scene){chooseScene(scene);restoreScene=null;}else if(!result.cursor){sceneStatus.textContent='This scene is unavailable.';updateURL(episode.id,null);}}else if(!selectedScene&&scenes.length)chooseScene(orderedScenes().find(Boolean)||scenes[0]);}catch(error){if(current()&&generation===sceneGeneration)sceneStatus.textContent=error.status===403?'You cannot access scenes in this game.':`Scenes unavailable: ${error.message}`;}};
    await page();
  }
  const load=async cursor=>{showLoading(episodeStatus,'Loading episodes…');try{const result=await api('/episodes',{gameId,cursor});if(!current())return;if(!Array.isArray(result.records))throw new Error('Episodes unavailable');episodes.push(...result.records);episodeStatus.textContent=episodes.length?'':'Create your first episode.';drawEpisodes();host.querySelector('.episodes-more')?.remove();if(result.cursor){const more=button('More episodes',()=>{more.remove();void load(result.cursor);});more.classList.add('episodes-more');episodeCards.after(more);}
      const requested=params().get('episode');if(requested&&!selectedEpisode){const selected=episodes.find(item=>item.id===requested);if(selected)await chooseEpisode(selected,params().get('scene'));else if(!result.cursor){episodeStatus.textContent='This episode is unavailable.';updateURL(null,null);}}
    }catch(error){if(current()){episodeStatus.textContent=error.status===403?'You cannot access episodes in this game.':`Episodes unavailable: ${error.message}`;if(error.status===403)create.disabled=true;}}};void load();
}

function renderVideoLibrary(assets, list, status, current, loadMore) {
  const gameId = state.gameId;
  const videoHost=document.createElement("div");videoHost.hidden=!assets.length&&!loadMore;list.append(videoHost);
  if (videoLibraryView.gameId !== gameId) videoLibraryView = {gameId,search:"",tags:[],characters:[],collection:new URLSearchParams(location.search).get("collection") || ""};
  const view = videoLibraryView;
  view.collection=new URLSearchParams(location.search).get("collection") || "";
  const cards=document.createElement('div');cards.className='video-library-cards';videoHost.append(cards);
  const search=document.createElement('input');search.type='search';search.id='video-search';search.placeholder='Search videos and episodes';search.maxLength=300;search.value=view.search;
  const label=document.createElement('label');label.htmlFor=search.id;label.textContent='Search videos';const searchField=document.createElement('div');searchField.append(label,search);
  const tagHost=document.createElement('div'),characterHost=document.createElement('div');tagHost.dataset.multiFilter='tags';characterHost.dataset.multiFilter='characters';
  const workspace=document.getElementById('episode-workspace'),filterBar=document.createElement('div'),filterFields=document.createElement('div');filterBar.className='video-search-toolbar';filterBar.setAttribute('aria-label','Video search and filters');filterFields.className='video-top-filter-fields';filterFields.append(tagHost,characterHost);filterBar.append(searchField,filterFields);
  workspace?.querySelector('.video-search-toolbar')?.remove();workspace?.prepend(filterBar);workspace?.filterEpisodes?.(view.search);
  let displayed=view.collection?[]:assets,chosen=null;
  const retry=document.createElement('button');retry.type='button';retry.className='quiet-button';retry.textContent='Retry preview images';retry.hidden=true;videoHost.append(retry);
  const tags=()=>[...new Set(assets.flatMap(asset=>asset.metadata?.tags||[]))].sort().map(name=>({id:name,name}));
  const characters=()=> (state.gameDetail?.characters||[]).map(character=>({id:character.id||character.characterId,name:character.name}));
  const filters=()=>{
    window.PantherUI.mountMultiSelect(tagHost,{label:'Tags',options:tags(),value:view.tags,onChange:value=>{view.tags=value;filters();draw();},placeholder:'Add tag…'});
    window.PantherUI.mountMultiSelect(characterHost,{label:'Characters',options:characters(),value:view.characters,onChange:value=>{view.characters=value;filters();draw();},placeholder:'Add character…'});
  };
  const more = document.createElement("button"); more.type = "button"; more.className = "load-more"; more.textContent = "Load more videos"; more.hidden = !loadMore; videoHost.append(more);
  more.onclick = () => { more.disabled = true; more.textContent = "Loading more…"; loadMore(); };
  const posters = new Map(), posterLinks = new Map(), posterRequests = new Map(); let imageGeneration=0;
  async function images() {
    const generation=++imageGeneration;
    retry.hidden = true;
    const entries = [...posters.entries()], keys = entries.map(([key])=>key);
    for (let offset=0;offset<keys.length;offset+=60) {
      const batch = keys.slice(offset,offset+60);
      try {
        const missing=batch.filter(key=>!posterRequests.has(key) && (!posterLinks.has(key) || posterLinks.get(key).expires<=Date.now()));
        if(missing.length) {
          const request=api("/image-links", {}, {body:{gameId,keys:missing}}).then(links=>{
            for(const key of missing)posterLinks.set(key,{...links.images?.[key],expires:Date.now()+Math.max(0,Number(links.expiresIn)-30)*1000});
          }).finally(()=>{for(const key of missing)posterRequests.delete(key);});
          for(const key of missing)posterRequests.set(key,request);
        }
        await Promise.all(batch.map(key=>posterRequests.get(key)).filter(Boolean));
        if (!current() || generation!==imageGeneration) return;
        for (const key of batch) for (const host of posters.get(key) || []) {
          if (!host.isConnected) continue;
          const image = document.createElement("img"); image.alt = host.dataset.alt; image.loading = "lazy";
          image.onload = () => { if (current() && generation===imageGeneration && host.isConnected) host.replaceChildren(image); };
          image.onerror = () => { if (current() && generation===imageGeneration && host.isConnected) { host.textContent = "Preview unavailable; the video can still be opened."; retry.hidden = false; } };
          if (posterLinks.get(key)?.url) { image.src = posterLinks.get(key).url; host.replaceChildren(image); }
          else { host.textContent = "Preview unavailable; the video can still be opened."; retry.hidden = false; }
        }
      } catch { if (current() && generation===imageGeneration) { for (const key of batch) for (const host of posters.get(key) || []) if(host.isConnected) host.textContent = "Preview unavailable; the video can still be opened."; retry.hidden = false; } }
    }
  }
  retry.onclick = () => { posterLinks.clear(); void images(); };
  function draw() {
    if (!current()) return;
    cards.replaceChildren(); posters.clear();
    const needle = view.search.trim().toLocaleLowerCase();
    const selected = displayed.filter(a => (!needle || [a.metadata?.title,a.metadata?.description,...(a.metadata?.tags || [])].filter(Boolean).join(" ").toLocaleLowerCase().includes(needle))
      && view.tags.every(tag=>a.metadata?.tags?.includes(tag)) && view.characters.every(id=>a.metadata?.characterIds?.includes(id)));
    status.textContent=displayed.length&&!selected.length?'No matching videos.':'';status.hidden=!status.textContent;
    const episodesEmpty=document.querySelector('#episode-workspace [data-episode-empty]');
    if(workspace)workspace.dataset.videoAssetCount=String(displayed.length);
    if(episodesEmpty){episodesEmpty.hidden=displayed.length>0||workspace?.dataset.hasEpisodes==='true';if(!displayed.length)episodesEmpty.textContent='Create your first episode.';}
    more.hidden = Boolean(chosen) || !loadMore;
    videoPlaylist = chosen ? {gameId,collection:chosen,assets:displayed} : null;
    for (const asset of selected) {
      const card = document.createElement("article"); card.className = "novel-card session-card video-card";
      const poster = document.createElement("div"); poster.className = "video-card-poster"; poster.textContent = "No preview image selected";
      const imageKey = asset.metadata?.extra?.preview?.schemaVersion === 1 ? asset.metadata.extra.preview.imageKey : null;
      poster.hidden = !imageKey;
      if (sameGameKey(imageKey) && /\.(png|jpe?g|webp|avif|gif|svg)$/i.test(imageKey)) {
        poster.textContent = "Loading selected preview…"; poster.dataset.alt = `Preview of ${asset.metadata?.title || asset.name}`;
        if (!posters.has(imageKey)) posters.set(imageKey,[]); posters.get(imageKey).push(poster);
      }
      const title = document.createElement("h2"); title.append(assetLink(asset));
      const description = document.createElement("p"); description.textContent = asset.metadata?.description || "";
      const info = document.createElement("p"); info.textContent = [new Date(asset.lastModified).toLocaleString(),...(asset.metadata?.tags || [])].join(" · ");
      const creator = asset.metadata?.extra?.creator; const credit = document.createElement("p"); credit.textContent = typeof creator === "string" ? `Creator: ${creator}` : "";
      card.append(poster,title,description,info,credit);
      const related = document.createElement("p");
      for (const id of asset.metadata?.characterIds || []) { const c = state.gameDetail?.characters.find(c=>c.id===id); if (!c) continue; const link=document.createElement("a"); link.href=gamePath("characters")+`/${encodeURIComponent(id)}`; link.textContent=c.name; related.append(link,document.createTextNode(" · ")); }
      if (asset.metadata?.sessionId) related.append(document.createTextNode(`Session: ${asset.metadata.sessionId}`));
      if (related.childNodes.length) card.append(related);
      cards.append(card);
    }
    void images();
  }
  search.oninput = () => { view.search=search.value;workspace?.filterEpisodes?.(view.search);draw(); };
  filters();draw();
  // Existing typed references retain their exact saved membership and order.
  // Collections are no longer offered as a creation or filtering control.
  if(view.collection)void(async()=>{
    try{const result=await api('/video-collections',{gameId,id:view.collection});if(!current())return;chosen=result.collection;displayed=result.assets||[];videoHost.hidden=false;draw();}
    catch(error){if(current()){status.textContent=`Videos unavailable: ${error.message}`;status.hidden=false;}}
  })();
}

function configureVideoPreview(asset, video, epoch) {
  const gameId=state.gameId, current=()=>epoch===previewEpoch && gameId===state.gameId && state.tokens;
  const host=document.createElement("section"); host.className="video-player-details"; video.after(host);
  const preview=asset.metadata?.extra?.preview;
  if(preview?.schemaVersion===1 && sameGameKey(preview.imageKey)) void api("/image-links",{},{body:{gameId,keys:[preview.imageKey]}}).then(result=>{if(current() && result.images?.[preview.imageKey]?.url)video.poster=result.images[preview.imageKey].url;}).catch(()=>{});
  const playlist=videoPlaylist?.gameId===gameId ? videoPlaylist : null;
  const index=playlist?.assets.findIndex(a=>a.key===asset.key) ?? -1;
  if(index>=0) {
    const navigation=document.createElement("nav"); navigation.setAttribute("aria-label","Ordered collection playback");
    const label=document.createElement("p"); label.textContent=`${playlist.collection.name} · ${index+1} of ${playlist.assets.length} available videos. Order is explicit; no automatic playback.`;
    const button=(name,position)=>{const node=document.createElement("button");node.type="button";node.className="quiet-button";node.textContent=name;node.disabled=position<0 || position>=playlist.assets.length;node.onclick=()=>{if(current()){const entry=playlist.assets[position];void previewFile({...entry,name:entry.metadata?.title || entry.name});}};return node;};
    navigation.append(label,button("Previous collection video",index-1),button("Next collection video",index+1));host.append(navigation);
  }
  const captions=document.createElement("section"), heading=document.createElement("h3"), captionStatus=document.createElement("p");
  captions.className="video-captions";heading.textContent="Caption tracks"; captionStatus.setAttribute("role","status");captionStatus.textContent="Finding explicitly associated WebVTT exports…";
  captions.append(heading,captionStatus);host.append(captions);
  let blobUrl=null;
  video.pantherCleanup=()=>{video.pantherCaptionController?.abort();if(blobUrl)URL.revokeObjectURL(blobUrl);blobUrl=null;};
  void(async()=>{
    try {
      const assets=await allAssets(gameId);if(!current())return;
      const directory=asset.key.slice(0,asset.key.lastIndexOf("/")+1);
      const tracks=assets.filter(a=>a.kind==="video-captions" && a.key.endsWith(".vtt") && sameGameKey(a.key)
        && (a.key.slice(0,a.key.lastIndexOf("/")+1)===directory || asset.sourceKeys?.includes(a.key) || a.sourceKeys?.includes(asset.key)));
      if(!tracks.length){captions.remove();return;}
      const label=document.createElement("label"), select=document.createElement("select"), load=document.createElement("button");
      label.textContent="Caption export";select.id="video-caption-export";label.htmlFor=select.id;
      select.add(new Option("Choose a recorded caption track",""));for(const track of tracks)select.add(new Option(track.metadata?.title || track.name,track.key));
      if(tracks.length===1)select.value=tracks[0].key;
      load.type="button";load.className="quiet-button";load.textContent="Load selected captions";load.disabled=!select.value;
      select.onchange=()=>{load.disabled=!select.value;};
      load.onclick=async()=>{
        const chosen=tracks.find(t=>t.key===select.value);if(!chosen)return;
        load.disabled=true;select.disabled=true;captionStatus.textContent="Loading the selected caption export…";
        const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);video.pantherCaptionController=controller;
        try{
          if(!Number.isFinite(chosen.size) || chosen.size>512*1024)throw new Error("Caption export exceeds the 512 KiB player limit; download its original instead");
          const signed=await api("/object-url",{key:chosen.key},{signal:controller.signal}), response=await fetch(signed.url,{signal:controller.signal});
          if(!response.ok || Number(response.headers.get("content-length"))>512*1024)throw new Error("Caption file is unavailable or too large");
          // Bound streaming reads as well as catalog/header sizes. Never buffer an arbitrary asset.
          const reader=response.body.getReader();let size=0;const chunks=[];
          try{while(true){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;if(size>512*1024)throw new Error("Caption file is too large");chunks.push(value);}}
          finally{await reader.cancel();}
          const text=await new Blob(chunks).text();if(!/^\uFEFF?WEBVTT(?:\s|$)/.test(text))throw new Error("Selected export is not WebVTT");
          if(!current())return;
          video.pantherCaptionController=null;video.querySelectorAll("track").forEach(t=>t.remove());video.pantherCleanup();
          blobUrl=URL.createObjectURL(new Blob([text],{type:"text/vtt"}));
          const track=document.createElement("track");track.kind="captions";track.label=chosen.metadata?.title || chosen.name;track.src=blobUrl;track.default=true;
          track.onload=()=>{if(current()){track.track.mode="showing";captionStatus.textContent="Selected captions loaded. These are the recorded export, not newly verified speech.";}};
          track.onerror=()=>{if(current())captionStatus.textContent="Captions could not be decoded. Retry or download the original export.";};
          video.append(track);track.track.mode="showing";
        }catch(error){if(current())captionStatus.textContent=`Captions unavailable: ${error.message}. Retry or open the original export.`;}
        finally{clearTimeout(timer);if(video.pantherCaptionController===controller)video.pantherCaptionController=null;if(current()){load.disabled=false;select.disabled=false;}}
      };
      captions.append(label,select,load);
      for(const track of tracks)captions.append(assetLink(track,`Open caption export · ${track.metadata?.title || track.name}`));
      captionStatus.textContent=`${tracks.length} caption tracks`;
    }catch(error){if(current())captionStatus.textContent=`Caption lookup unavailable: ${error.message}. Video playback remains usable.`;}
  })();
}

let liveReaderOpen=false,liveReaderRecording=null;
function ensureSessionGroup(list,sessionId){
  let group=[...list.querySelectorAll('.session-group')].find(node=>node.dataset.sessionId===sessionId);
  if(!group){group=document.createElement('section');group.className='session-group transcript-session';group.dataset.sessionId=sessionId;const title=document.createElement('h2');title.textContent=sessionId?`Session · ${sessionId}`:'Unassigned session';group.append(title);list.append(group);}return group;
}
function closeLiveReader(){liveReaderOpen=false;liveReaderRecording=null;document.getElementById('live-transcript').hidden=true;const list=document.getElementById('library-list');if(list)list.hidden=false;}
function openLiveReader(recordingId){const record=liveRecords.find(item=>item.recordingId===recordingId);if(record&&!liveHistory.get(historyKey(record))?.loaded)void loadLiveHistory(record);liveReaderOpen=true;liveReaderRecording=recordingId;liveRenderKey='';document.getElementById('library-list').hidden=true;document.getElementById('library-status').hidden=true;drawLive();document.getElementById('live-reader-back').focus();}
document.getElementById('live-reader-back').onclick=()=>{closeLiveReader();document.querySelector('.session-live-entry button')?.focus();};
function renderLiveSessionEntries(){
  if(elements.primaryNav.querySelector('[aria-current]')?.dataset.section!=='sessions')return;
  const list=document.getElementById('library-list');for(const node of list.querySelectorAll('.session-live-entry'))node.remove();
  for(const group of list.querySelectorAll('.session-group[data-live-only]'))if(group.children.length===1)group.remove();
  for(const record of liveRecords){const group=ensureSessionGroup(list,record.sessionId||'');if(group.children.length===1)group.dataset.liveOnly='true';const row=document.createElement('article');row.className='session-live-entry';const open=document.createElement('button');open.type='button';open.className='quiet-button';open.textContent='Open transcript';open.setAttribute('aria-label',`Open transcript for ${record.sessionId}`);open.onclick=()=>openLiveReader(record.recordingId);row.append(open);if(liveState(record)==='recording'){const state=document.createElement('span');state.className='session-recording-indicator';state.textContent='Recording';row.append(state);}group.insertBefore(row,group.children[1]||null);}
  if(liveRecords.length)document.getElementById('library-status').hidden=true;
}

async function loadLibrary(section, epoch, previousAssets = [], cursor = null) {
  const inbox=document.getElementById('video-approval-inbox');
  inbox.hidden=section!=='videos'||new URLSearchParams(location.search).has('project');
  if(!inbox.hidden&&!cursor)void loadApprovalInbox(inbox,epoch);
  document.getElementById("session-library").dataset.paged = String(previousAssets.length > 0 || Boolean(cursor));
  const gameId = state.gameId, current = () => epoch === routeEpoch && gameId === state.gameId && state.tokens;
  const status = document.getElementById("library-status"), list = document.getElementById("library-list");
  document.getElementById("session-library").hidden = false;
  if(section === "videos") renderEpisodeWorkspace(epoch);else {const workspace=document.getElementById("episode-workspace");if(workspace){workspace.stopPreview?.();workspace.hidden=true;}}
  const episodeCreate=document.getElementById("episode-create-action");
  if(episodeCreate)episodeCreate.hidden=section!=="videos";
  const videoComposer=document.getElementById("editorial-video-composer");
  if(videoComposer)videoComposer.hidden=section!=="videos";
  document.getElementById("live-transcript").hidden = section!=="sessions" || !liveReaderOpen;
  if (["sessions"].includes(section)) {
    drawLive();
    if(liveReaderOpen)for (const record of liveRecords) if (!liveHistory.has(historyKey(record))) void loadLiveHistory(record);
  }
  document.getElementById("library-title").textContent = {sessions:"Sessions", videos:"Videos"}[section];
  status.hidden = false;
  status.dataset.empty = "false";
  const loading = showLoading(status, `Fetching ${section} from the catalog…`);
  try {
    // A bounded page of the selected section, never an automatic whole-game scan.
    const page = await api("/assets", {gameId, section, cursor});
    if (!Array.isArray(page.assets)) throw new Error("Asset catalog unavailable");
    const assets = [...new Map([...previousAssets, ...page.assets].map(a => [a.key, a])).values()];
    if (!current()) return;
    list.replaceChildren();
    loading.update("Organizing recordings, transcripts and videos…");
    if (section === "videos" && new URLSearchParams(location.search).has("project")) await loadMovies(assets, epoch);
    if (!current()) return;
    status.hidden = section === "videos" && new URLSearchParams(location.search).has("project");
    list.hidden = status.hidden;
    if (status.hidden) return;
    const manifests = new Set(assets.filter(a => a.recording?.partCount > 0).map(a => a.key.split("/")[3]));
    const keys = new Set(assets.map(a => a.key));
    const isRecording=a=>a.recording?.partCount>0||((a.contentType?.startsWith("audio/")||/\.(flac|wav|mp3|m4a|ogg)$/i.test(a.name))&&!manifests.has(a.key.split("/")[3]));
    const isTranscript=a=>["transcript","raw-transcript","corrected-transcript","edited-transcript"].includes(a.kind)&&!(a.key.endsWith(".md")&&keys.has(a.key.slice(0,-3)+".json"));
    const selected=assets.filter(a=>section==="videos"?a.contentType?.startsWith("video/")||/\.(mp4|webm|mov|m4v|ogv)$/i.test(a.name):isRecording(a)||isTranscript(a));
    status.dataset.empty=String(!selected.length);
    selected.sort((a,b) => (b.metadata?.sessionId || "").localeCompare(a.metadata?.sessionId || "") || b.lastModified.localeCompare(a.lastModified) || a.name.localeCompare(b.name));
    if (section === "videos") {
      document.getElementById('episode-workspace')?.updateOutputs?.(selected);
      renderVideoLibrary(selected,list,status,current,page.cursor ? () => { void loadLibrary(section,epoch,assets,page.cursor); } : null);
      return;
    }
    status.textContent=selected.length?'':'No saved sessions yet.';status.hidden=!!selected.length||liveReaderOpen;
    for(const asset of selected){
      const sessionId=asset.metadata?.sessionId||'',group=ensureSessionGroup(list,sessionId),card=document.createElement('article');card.className='novel-card session-card';
      const heading=document.createElement('h3'),kind=document.createElement('p'),version=asset.metadata?.extra?.version;
      heading.append(assetLink(asset,asset.kind==='recording-manifest'?'Recording':asset.metadata?.title||asset.name));
      kind.className='session-asset-meta';const type=isTranscript(asset)?asset.kind==='raw-transcript'?'Raw transcript':['corrected-transcript','edited-transcript'].includes(asset.kind)?'Corrected transcript':'Transcript':'Recording';
      kind.textContent=type+(version?` · v${version.number}`:'');card.append(heading,kind);
      const observed=asset.transcript;
      if(observed?.state==='available'){const summary=document.createElement('p');summary.className='session-asset-meta';const speakers=(observed.participants||[]).map(person=>person.name||person.id);summary.textContent=[speakers.join(', '),observed.unassignedSegments?`${observed.unassignedSegments} unassigned segments`:'',observed.reviewStatus].filter(Boolean).join(' · ');if(summary.textContent)card.append(summary);}
      group.append(card);
    }
    renderLiveSessionEntries();list.hidden=liveReaderOpen;
    if (page.cursor) {
      const more = document.createElement("button");
      more.type = "button"; more.className = "load-more"; more.textContent = `Load more ${section}`;
      more.addEventListener("click", () => {
        more.disabled = true; more.textContent = "Loading more…";
        void loadLibrary(section, epoch, assets, page.cursor);
      });
      list.append(more);
      if (!selected.length) status.textContent = `No ${section} to display in these entries. More entries are available.`;
    }
  } catch (error) {
    if (current()) status.textContent = section === "videos" ? (error.status===403?"You cannot access finished videos in this game.":`Finished videos unavailable: ${error.message}`) : `${error.message}. Reload the page to try again.`;
  }
}

// A read-time projection only: never rewrite the exact stored sourceKeys graph.
function finishedAssetConnections(assets, key, gameId) {
  const valid = k => typeof k === "string" && k.startsWith(`games/${gameId}/assets/`)
    && !k.split("/").includes("..") && !/[\\\x00-\x1f]/.test(k);
  const index = new Map(assets.filter(a => valid(a.key)).map(a => [a.key, a]));
  const aliases = new Map(), recordingParts = new Map();
  const bind = (child, parent) => {
    if (!index.has(child) || child === parent) return;
    if (!recordingParts.has(child)) recordingParts.set(child, new Set());
    recordingParts.get(child).add(parent);
  };
  for (const a of index.values()) {
    if (!(a.recording?.partCount > 0)) continue;
    const prefix = a.key.slice(0, a.key.lastIndexOf("/") + 1);
    for (const part of a.sourceKeys || []) {
      if (part.startsWith(prefix) && /^part-\d{4}\.flac$/.test(part.slice(prefix.length))) bind(part, a.key);
    }
  }
  for (const a of index.values()) {
    if (a.playback && index.get(a.playback.recordingKey)?.recording?.partCount > 0) {
      bind(a.key, a.playback.recordingKey);
      bind(a.playback.audioKey, a.playback.recordingKey);
    }
  }
  for (const [child, parents] of recordingParts) if (parents.size === 1) aliases.set(child, [...parents][0]);
  const transcripts = new Set(["transcript", "raw-transcript", "corrected-transcript", "edited-transcript"]);
  for (const a of index.values()) {
    if (a.key.endsWith(".md") && (transcripts.has(a.kind) || a.kind === "novel-chapter")) {
      const json = index.get(a.key.slice(0, -3) + ".json");
      if (json?.kind === a.kind && !json.lineageWarning) aliases.set(a.key, json.key);
    }
  }
  const canonical = k => aliases.get(k) || k;
  const stages = new Set(["context", "correction", "capture-health", "recording-checkpoint", "recording-manifest",
    "recording-playback-manifest", "novel-brief", "novel-options", "novel-outline", "novel-draft",
    "novel-developmental-edit", "novel-revision", "novel-continuity", "novel-line-copyedit", "novel-proof",
    "video-treatment", "video-screenplay", "video-script-edit", "video-shooting-script", "video-breakdown",
    "video-design", "video-reference-plan", "video-voice-casting", "video-blocking", "video-shot-list",
    "video-storyboards", "video-generation-packets", "video-edit-sound-vfx", "video-production-plan", "video-preflight"]);
  const finished = a => {
    if (!a || a.lineageWarning || a.metadata?.extra?.relationshipRole === "intermediate") return false;
    if (a.recording?.partCount > 0) return true;
    if (stages.has(a.kind) || a.kind?.startsWith("editorial-") || a.kind?.includes("provenance")) return false;
    if (a.metadata?.extra?.relationshipRole === "finished") return true;
    return transcripts.has(a.kind) || ["novel-chapter", "novel", "story", "portrait", "map", "document", "game-context", "model-3d", "music"].includes(a.kind)
      || /^(audio|video|image)\//.test(a.contentType || "")
      || /\.(mp3|flac|wav|m4a|ogg|mp4|webm|mov|m4v|png|jpg|jpeg|webp|gif|glb|blend|pdf)$/i.test(a.name || "");
  };
  const inputs = new Map(), outputs = new Map();
  const edge = (map, from, to) => { if (!map.has(from)) map.set(from, new Set()); map.get(from).add(to); };
  let incomplete = false;
  for (const a of index.values()) {
    for (const source of a.sourceKeys || []) {
      if (!valid(source)) continue;
      if (!index.has(source)) { incomplete = true; continue; }
      const from = canonical(a.key), to = canonical(source);
      if (from === to) continue;
      edge(inputs, from, to); edge(outputs, to, from);
    }
  }
  const label = a => {
    const type = a.recording?.partCount > 0 ? "Audio"
      : ["transcript", "raw-transcript"].includes(a.kind) ? "Original transcript"
      : ["corrected-transcript", "edited-transcript"].includes(a.kind) ? "Corrected transcript"
      : a.kind === "novel-chapter" ? "Novel chapter"
      : (a.contentType || "").startsWith("video/") ? "Video" : a.kind?.replaceAll("-", " ") || "Asset";
    const title = a.metadata?.title;
    return title && title !== a.kind && title !== a.name ? title : `${type}${a.metadata?.sessionId ? " · " + a.metadata.sessionId : ""}`;
  };
  const root = canonical(key);
  const walk = graph => {
    const visited = new Set([root]), found = new Map(), pending = [...(graph.get(root) || [])];
    while (pending.length) {
      const next = pending.pop();
      if (visited.has(next)) continue;
      visited.add(next);
      const a = index.get(next);
      if (finished(a)) found.set(next, {...a, connectionLabel: label(a)});
      else for (const neighbor of graph.get(next) || []) pending.push(neighbor);
    }
    return [...found.values()].sort((a,b) => a.connectionLabel.localeCompare(b.connectionLabel) || a.key.localeCompare(b.key));
  };
  return {inputs: walk(inputs), outputs: walk(outputs), incomplete};
}

function appendFinishedConnections(host, connections) {
  for (const [title, records] of [["Inputs", connections.inputs], ["Outputs", connections.outputs]]) {
    if (!records.length) continue;
    const heading = document.createElement("h3"); heading.textContent = title;
    const list = document.createElement("ul"); list.dataset.connections = title.toLowerCase();
    for (const record of records) {
      const li = document.createElement("li"), jobId = record.metadata?.extra?.jobId;
      li.append(record.kind === "novel-chapter" && /^[a-f0-9]{64}$/.test(jobId || "")
        ? novelLink(record.connectionLabel, jobId) : assetLink(record, record.connectionLabel));
      list.append(li);
    }
    host.append(heading, list);
  }
}

async function renderAssetLinks(key, epoch, resolved = null) {
  const host = document.getElementById("asset-links"), gameId = state.gameId;
  const current = () => epoch === previewEpoch && gameId === state.gameId && state.tokens;
  if (!sameGameKey(key)) { host.textContent = "Connections are available for game assets."; return; }
  try {
    const assets = [...await allAssets(gameId)];
    if (!current()) return;
    // A resolved file is already an asset. Catalog pages project metadata and may omit
    // raw recording parts; their absence must not invalidate an existing file.
    if (!assets.some(a => a.key === key) && resolved?.key === key) assets.push(resolved);
    host.replaceChildren();
    const connections = finishedAssetConnections(assets, key, gameId);
    appendFinishedConnections(host, connections);
    const companions = assets.filter(a => a.key !== key && a.key.split("/")[3] === key.split("/")[3]);
    if (companions.length) {
      const list = document.createElement("ul");
      for (const asset of companions) { const li = document.createElement("li"); li.append(assetLink(asset)); list.append(li); }
      host.append(optionalInfoDialog("Technical files and original exports", list).host);
    }
    const warnings = assets.filter(a => a.lineageWarning).length;
    if (warnings || connections.incomplete) { const warning = document.createElement("p"); warning.textContent = "Some provenance is missing or unreadable; finished-asset connections may be incomplete."; host.append(warning); }

  } catch (error) { if (current()) host.textContent = `Connections unavailable: ${error.message}. Close and reopen to retry.`; }
}

async function renderAssetVersions(key, epoch) {
  const host = document.getElementById("asset-versions"), gameId = state.gameId;
  const current = () => epoch === previewEpoch && gameId === state.gameId && state.tokens;
  if (!sameGameKey(key)) { host.textContent = "Versions are available for game assets."; return; }
  try {
    const assets = await allAssets(gameId);
    if (!current()) return;
    const item = assets.find(asset => asset.key === key);
    const version = item?.metadata?.extra?.version;
    if (!version || version.schemaVersion !== 1) { host.replaceChildren(); return; }
    const series = assets.filter(asset => asset.metadata?.extra?.version?.seriesId === version.seriesId)
      .sort((a, b) => a.metadata.extra.version.number - b.metadata.extra.version.number);
    const heading = document.createElement("h3"), list = document.createElement("ol");
    heading.textContent = "Versions";
    for (const asset of series) {
      const li = document.createElement("li"), record = asset.metadata.extra.version;
      li.append(assetLink(asset, `Version ${record.number} · ${asset.metadata?.title || asset.name}`));
      if (asset.key === key) li.append(document.createTextNode(" · viewing now"));
      list.append(li);
    }
    host.replaceChildren(heading, list);
  } catch (error) { if (current()) host.textContent = `Versions unavailable: ${error.message}. Close and reopen to retry.`; }
}

function closeOptionalInfoDialogs() {
  for (const dialog of [...document.querySelectorAll(".optional-info-dialog[open]")].reverse()) dialog.close();
}

// Native modal dialogs supply focus containment and Escape dismissal; closing
// restores focus to the opener while it remains in the active view.
function optionalInfoDialog(title, content, onOpen = () => {}) {
  const host = document.createElement("div"), button = document.createElement("button"), dialog = document.createElement("dialog");
  const header = document.createElement("header"), heading = document.createElement("h2"), close = document.createElement("button");
  host.className = "optional-info"; dialog.className = "optional-info-dialog";
  button.type = close.type = "button"; button.className = close.className = "quiet-button";
  button.textContent = heading.textContent = title; close.textContent = "Close";
  dialog.setAttribute("aria-label", title); close.onclick = () => dialog.close();
  header.append(heading, close); dialog.append(header, content); host.append(button, dialog);
  button.onclick = () => { dialog.showModal(); onOpen(); };
  dialog.addEventListener("close", () => { if (button.isConnected && !button.closest("[hidden]")) button.focus({preventScroll:true}); });
  return {host, dialog, button};
}

function detailBlock(title, value) {
  const pre = document.createElement("pre"); pre.textContent = JSON.stringify(value, null, 2);
  return optionalInfoDialog(title, pre).host;
}

// Movie review is intentionally separate from the paid local generation CLI.
function movieNode(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function movieButton(text, action, className = "quiet-button") {
  const button = movieNode("button", text, className); button.type = "button";
  button.addEventListener("click", action); return button;
}
function movieMoney(value) { return value === null || value === undefined ? "Not quoted" : `$${Number(value).toFixed(2)}`; }

async function loadMovies(assets, epoch) {
  const host = document.getElementById("movie-workspace"), gameId = state.gameId;
  const current = () => epoch === routeEpoch && gameId === state.gameId && state.tokens;
  host.hidden = false; host.replaceChildren();
  const plans = assets.filter(a => a.kind === "movie-review-plan" && sameGameKey(a.key));
  const key = new URLSearchParams(location.search).get("project");
  if (!key) {host.hidden=true;return;}
  showLoading(host, "Reading the screenplay, shots and budget review…");
  try {
    if (!sameGameKey(key)) throw new Error("This movie plan does not belong to the selected game");
    const data = await api("/movie-review", {gameId, key});
    if (!current()) return;
    if (data.plan?.gameId !== gameId || data.plan?.entityType !== "MovieReviewPlan") throw new Error("Invalid movie plan");
    drawMovieWorkspace(host, data, key, assets, current);
  } catch (error) {
    if (!current()) return;
    host.replaceChildren(movieNode("p", `${error.message}. Reload the page to try again.`, "error"),
      movieButton("← All videos", () => navigate(gamePath("videos"))));
  }
}

function drawMovieWorkspace(host, data, key, assets, current) {
  const plan = data.plan, reviewed = new Set(), notes = new Map();
  let selected = 0, tab = "Storyboard", saving = false;
  host.replaceChildren();
  document.getElementById("library-title").textContent = "Movie review";
  const header = movieNode("header", undefined, "movie-hero");
  header.append(movieButton("← All videos", () => navigate(gamePath("videos")), "back-button"));
  const heading = movieNode("div", undefined, "movie-hero-heading");
  const title = movieNode("div");
  title.append(movieNode("p", `PRE-PRODUCTION / ${plan.revisionId}`, "eyebrow"), movieNode("h2", plan.title), movieNode("p", plan.summary, "movie-synopsis"));
  heading.append(title, movieNode("span", "No generation started", "movie-tag")); header.append(heading);
  const stats = movieNode("div", undefined, "movie-stats");
  stats.append(movieNode("span", `${plan.shots.length} planned shots`), movieNode("span", `${data.readiness.durationSeconds}s planned runtime`),
    movieNode("span", `${movieMoney(plan.budget.capUsd)} budget ceiling`), movieNode("span", "AI adaptation · not a verbatim record"));
  header.append(stats); host.append(header);
  if (plan.scope === "campaign") header.append(movieNode("p", "Campaign-wide storyboard · review at your own pace", "movie-muted"));
  if (plan.narratorSampleKey && plan.sourceKeys.includes(plan.narratorSampleKey) && sameGameKey(plan.narratorSampleKey)) {
    const sample = movieNode("p", "Separate voice audition: ", "movie-narrator-sample");
    sample.append(assetLink(assets.find(a=>a.key===plan.narratorSampleKey) || {key:plan.narratorSampleKey, metadata:{title:"Listen to narrator sample"}}));
    header.append(sample);
  }
  const layout = movieNode("div", undefined, "movie-layout"), main = movieNode("div", undefined, "movie-main"), aside = movieNode("aside", undefined, "movie-budget");
  aside.setAttribute("aria-label", "Budget and approval");
  const tabs = movieNode("nav", undefined, "movie-tabs"); tabs.setAttribute("aria-label", "Movie plan views");
  const content = movieNode("div", undefined, "movie-content");
  main.append(tabs, content); layout.append(main, aside); host.append(layout);
  const feedbackStatus = movieNode("p", "", "movie-feedback-status"); feedbackStatus.setAttribute("role", "status");
  const galleryKeys = [...new Set([...plan.shots.map(s => s.frameKey), ...plan.characters.map(c => c.portraitKey)])]
    .filter(key => key && sameGameKey(key) && plan.sourceKeys.includes(key));
  let galleryPromise = null, galleryExpires = 0, galleryGeneration = 0;
  function galleryLinks(failedGeneration) {
    if (failedGeneration === galleryGeneration) galleryPromise = null;
    if (!galleryPromise || Date.now() >= galleryExpires) {
      const generation = ++galleryGeneration;
      galleryExpires = Date.now() + 240000;
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
      galleryPromise = api("/image-links", {}, {body: {gameId: plan.gameId, keys: galleryKeys}, signal: controller.signal})
        .then(result => {
          galleryExpires = Date.now() + Math.max(0, Number(result.expiresIn) - 30) * 1000;
          return {...result, generation};
        }).finally(() => clearTimeout(timer));
    }
    return galleryPromise;
  }
  const retryImages = movieButton("Retry gallery images", () => {
    galleryPromise = null; retryImages.hidden = true; renderContent();
  });
  retryImages.hidden = true; header.append(retryImages);
  async function attachImage(container, assetKey, alt) {
    if (!assetKey || !sameGameKey(assetKey) || !plan.sourceKeys.includes(assetKey)) return;
    // Let cast cards be inserted before checking whether their view is still active.
    await Promise.resolve();
    let failedGeneration;
      for (let attempt = 0; attempt < 3; attempt++) {
        if (!current() || !container.isConnected) return;
        showLoading(container, attempt ? "Refreshing gallery access…" : "Loading gallery image…");
        try {
          const pending = galleryLinks(failedGeneration);
          failedGeneration = galleryGeneration;
          const gallery = await pending;
          const file = gallery.images[assetKey];
          if (!file?.url) throw new Error(file?.error || "Image link unavailable");
          if (!current() || !container.isConnected) return;
          const img = movieNode("img"); img.alt = alt;
          // Start bytes now: lazy images can outlive their short-lived signed URL.
          await new Promise((resolve, reject) => {
            const timer = setTimeout(() => finish(new Error("Image timed out")), 20000);
            function finish(error) {
              clearTimeout(timer); img.onload = null; img.onerror = null;
              if (error) { img.removeAttribute("src"); reject(error); } else resolve();
            }
            img.onload = () => finish(); img.onerror = () => finish(new Error("Image request failed"));
            img.src = file.url;
          });
          if (current() && container.isConnected) { container.replaceChildren(img); container.classList.add("has-image"); }
          return;
        } catch {
          if (!current() || !container.isConnected) return;
          if (attempt < 2) await new Promise(resolve => setTimeout(resolve, 800));
        }
      }
      if (current() && container.isConnected) {
        container.textContent = "Image could not load. Use Retry gallery images above.";
        container.classList.remove("has-image");
        retryImages.hidden = false;
      }
  }
  function renderAside() {
    aside.replaceChildren(movieNode("p", "STORYBOARD APPROVAL", "eyebrow"), movieNode("h3", "Review before you spend"));
    const cost = movieNode("div", undefined, "movie-cost");
    cost.append(movieNode("strong", data.readiness.costComplete ? movieMoney(data.readiness.knownCostUsd) : "Unquoted"),
      movieNode("span", "estimated generation cost", "movie-muted")); aside.append(cost);
    aside.append(movieNode("p", `${movieMoney(plan.budget.capUsd)} total budget ceiling · USD`, "movie-cap"));
    const budgetBar = movieNode("div", undefined, "movie-budget-bar");
    const fill = movieNode("span"); fill.style.width = `${Math.min(100, Number(data.readiness.knownCostUsd) / Number(plan.budget.capUsd) * 100)}%`; budgetBar.append(fill); aside.append(budgetBar);
    aside.append(movieNode("p", plan.budget.notes || "Includes retries. Quotes must be refreshed before approval. Unknown costs are not zero.", "movie-small"));
    const count = movieNode("p", `${reviewed.size} of ${plan.shots.length} shots reviewed`, "movie-reviewed-count"); aside.append(count);
    if (data.readiness.blockers.length) {
      const details = movieNode("section", undefined, "movie-blockers");
      details.append(movieNode("h4", `${data.readiness.blockers.length} items need attention`));
      const list = movieNode("ul"); for (const blocker of data.readiness.blockers) list.append(movieNode("li", blocker)); details.append(list); aside.append(details);
    }
    if (data.review) {
      const saved = movieNode("div", undefined, "movie-saved-review");
      saved.append(movieNode("strong", data.review.action === "approved" ? "This revision was approved" : "Changes requested"),
        movieNode("p", new Date(data.review.createdAt*1000).toLocaleString(), "movie-small"));
      for (const comment of data.review.comments || []) saved.append(movieNode("p", `${comment.shotId || "Overall"}: ${comment.text}`));
      aside.append(saved);
    }
    const feedback = movieButton("Save change requests", () => save("changes-requested"), "quiet-button movie-wide");
    feedback.disabled = saving || ![...notes.values()].some(v => v.trim()); aside.append(feedback);
    const approve = movieButton("Review approval…", approvalDialog, "primary-button movie-wide");
    approve.disabled = saving || !data.canApprove || !data.readiness.ready || reviewed.size !== plan.shots.length || [...notes.values()].some(v=>v.trim());
    aside.append(approve, movieNode("p", !data.canApprove ? "An owner must approve the budget." : "Resolve blockers, review each shot, and save any requested changes first.", "movie-small"),
      movieNode("p", "Approval records your decision only. It does not start generation or charge your account.", "movie-safety"), feedbackStatus);
  }
  async function save(action, confirmation) {
    if (saving || !current()) return;
    saving = true; feedbackStatus.textContent = "Saving your review…"; renderAside();
    try {
      const result = await api("/movie-review", {}, {body:{gameId:plan.gameId, key, sha256:data.sha256,
        expectedReviewId:data.review?.id || null, action, capUsd:plan.budget.capUsd,
        reviewedShotIds:[...reviewed], comments:[...notes].filter(([,v])=>v.trim()).map(([shotId,text])=>({shotId,text:text.trim()}))}});
      if (!current()) return;
      data.review = result.review; notes.clear(); feedbackStatus.textContent = "Review saved. No generation was started.";
      confirmation?.close(); confirmation?.remove(); renderContent();
    } catch (error) { if (current()) feedbackStatus.textContent = `${error.message} Your notes are still here; copy them before refreshing.`; }
    finally { if (current()) { saving = false; renderAside(); } }
  }
  function approvalDialog() {
    const dialog = movieNode("dialog", undefined, "movie-confirm");
    dialog.setAttribute("aria-label", "Confirm movie plan approval");
    dialog.append(movieNode("p", "EXACT REVISION APPROVAL", "eyebrow"), movieNode("h2", "Ready for production?"),
      movieNode("p", `Approve ${plan.revisionId}, ${plan.shots.length} shots, with a hard ceiling of ${movieMoney(plan.budget.capUsd)} USD including retries.`),
      movieNode("p", "Content, model, references or cost changes require a new plan and fresh approval. This button will not generate footage."));
    const label = movieNode("label", undefined, "movie-check"), check = document.createElement("input"); check.type = "checkbox";
    label.append(check, "I approve this exact plan and budget ceiling."); dialog.append(label);
    const confirm = movieButton("Approve this plan", () => { confirm.disabled=true; void save("approved", dialog); }, "primary-button");
    confirm.disabled = true; check.onchange = () => {confirm.disabled=!check.checked;};
    dialog.append(movieButton("Keep reviewing", () => {dialog.close(); dialog.remove();}), confirm);
    dialog.addEventListener("cancel", () => dialog.remove()); host.append(dialog); dialog.showModal();
  }
  function renderContent() {
    tabs.replaceChildren(); content.replaceChildren();
    for (const name of ["Storyboard", "Screenplay", "Cast & sources"]) {
      const button = movieButton(name, () => {tab=name; renderContent();}); button.setAttribute("aria-pressed", String(tab===name)); tabs.append(button);
    }
    if (tab === "Screenplay") {
      const paper = movieNode("article", undefined, "movie-script"); paper.setAttribute("aria-label", "Movie screenplay");
      paper.append(movieNode("p", "SHOOTING DRAFT · CREATIVE ADAPTATION", "eyebrow"), movieNode("h3", plan.title));
      const prose = movieNode("div"); proseMarkdown(prose, plan.screenplay); paper.append(prose); content.append(paper); return;
    }
    if (tab === "Cast & sources") {
      content.append(movieNode("h3", "The selected cast"), movieNode("p", "These are pinned visual references, not final shot compositions.", "movie-muted"));
      const cast = movieNode("div", undefined, "movie-cast");
      for (const character of plan.characters) {
        const card = movieNode("article"), image = movieNode("div", "Portrait unavailable", "movie-portrait");
        card.append(image, movieNode("h4", character.name)); cast.append(card);
        void attachImage(image, character.portraitKey, `Selected portrait of ${character.name}`);
      }
      content.append(cast, movieNode("h3", "Source material"), movieNode("p", "Open the original evidence to check story choices. Adaptations are not new factual evidence.", "movie-muted"));
      const list = movieNode("ul", undefined, "movie-sources");
      for (const source of plan.sourceKeys) if (sameGameKey(source)) {
        const li = movieNode("li"); li.append(assetLink(assets.find(a=>a.key===source) || {key:source})); list.append(li);
      }
      content.append(list); return;
    }
    const grid = movieNode("div", undefined, "movie-shot-grid");
    plan.shots.forEach((shot, index) => {
      const button = movieButton("", () => {selected=index; renderContent(); content.querySelector('.movie-inspector').scrollIntoView({block:"start"});}, "movie-shot");
      button.setAttribute("aria-label", `Inspect shot ${index+1}: ${shot.title}`); button.setAttribute("aria-pressed", String(selected===index));
      const frame = movieNode("div", undefined, "movie-frame");
      const placeholder = movieNode("div", undefined, "movie-frame-placeholder");
      placeholder.append(movieNode("span", String(index+1).padStart(2,"0"), "movie-frame-number"),
        movieNode("span", shot.frameKey ? "Loading starting frame" : "Composition to be prepared", "movie-frame-label")); frame.append(placeholder);
      const meta = movieNode("div", undefined, "movie-shot-meta");
      meta.append(movieNode("span", `SHOT ${String(index+1).padStart(2,"0")} · ${shot.durationSeconds}s`, "eyebrow"),
        movieNode("h3", shot.title), movieNode("p", `${shot.model} · ${movieMoney(shot.costUsd)}`, "movie-small"),
        movieNode("span", reviewed.has(shot.id) ? "Reviewed" : shot.warnings?.some(w=>w.severity==="blocker") ? "Needs attention" : "To review", "movie-shot-state"));
      if (shot.footagePlan) meta.append(movieNode("p", shot.footagePlan, "movie-footage-plan"));
      if (shot.narration) {
        meta.append(movieNode("p", "ACTION", "eyebrow"), movieNode("p", shot.description, "movie-action"), movieNode("p", "NARRATION", "eyebrow"), movieNode("p", shot.narration, "movie-narration"));
      }
      button.append(frame,meta); grid.append(button);
    });
    content.append(grid);
    // Images are fetched after insertion so stale routes cannot attach them.
    grid.querySelectorAll(".movie-frame").forEach((frame,i)=>{ if(plan.shots[i].frameKey) void attachImage(frame,plan.shots[i].frameKey,`Starting composition: ${plan.shots[i].title}`); });
    const shot = plan.shots[selected], inspector = movieNode("section", undefined, "movie-inspector"); inspector.setAttribute("aria-label", "Selected shot details");
    inspector.append(movieNode("p", `SHOT ${String(selected+1).padStart(2,"0")} / ${plan.shots.length}`, "eyebrow"), movieNode("h3", shot.title), movieNode("p", shot.description));
    const facts = movieNode("dl", undefined, "movie-shot-facts");
    for (const [label,value] of [["Characters",shot.characterIds.map(id=>plan.characters.find(c=>c.id===id)?.name || id).join(", ") || "No named characters"],["Footage plan",shot.footagePlan || "See shot description"],["Narration",shot.narration || "No voiceover specified"],["Camera",shot.camera],["Continuity",shot.continuity],["Model choice",`${shot.model} — ${shot.modelReason}`],["Dialogue",shot.dialogue || "No spoken dialogue planned."]]) {
      const row = movieNode("div"); row.append(movieNode("dt",label),movieNode("dd",value)); facts.append(row);
    } inspector.append(facts);
    for (const warning of shot.warnings || []) inspector.append(movieNode("p", `${warning.severity==="blocker" ? "Needs attention" : "Production note"}: ${warning.message}`, "movie-warning"));
    const checkLabel = movieNode("label", undefined, "movie-check"), check = document.createElement("input"); check.type="checkbox"; check.checked=reviewed.has(shot.id);
    check.onchange = () => {check.checked ? reviewed.add(shot.id) : reviewed.delete(shot.id);
      grid.children[selected].querySelector('.movie-shot-state').textContent=check.checked ? 'Reviewed' : 'To review'; renderAside();};
    checkLabel.append(check, "I have reviewed this shot"); inspector.append(checkLabel);
    const noteLabel=movieNode("label","Request a change to this shot", "movie-note-label"); noteLabel.htmlFor="movie-shot-note";
    const note=document.createElement("textarea"); note.id="movie-shot-note"; note.maxLength=2000; note.rows=3; note.value=notes.get(shot.id)||""; note.placeholder="Wrong character, unclear action, a line to change…";
    note.oninput = () => { notes.set(shot.id,note.value); feedbackStatus.textContent="Unsaved changes — use Save change requests."; renderAside(); };
    inspector.append(noteLabel,note,movieNode("p","Notes are saved only when you choose Save change requests.","movie-small")); content.append(inspector);
    inspector.append(movieButton("Back to storyboard", () => {grid.children[selected].scrollIntoView({block:"center"}); grid.children[selected].focus({preventScroll:true});}));
  }
  renderContent(); renderAside();
}

function timestamp(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "Unknown time";
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2,"0")}`;
}

function attachMediaRecovery(audio, key, current) {
  audio.preload = "metadata";
  const activity=document.createElement("p"), warning=document.createElement("p");audio.after(activity,warning);warning.hidden=true;warning.className="error";
  let recovering=false, attempts=0;
  const waiting=()=>{if(current()){activity.hidden=false;showLoading(activity,"Loading playback");}};
  const ready=()=>{activity.hidden=true;activity.replaceChildren();};
  audio.addEventListener("loadstart",waiting);audio.addEventListener("waiting",waiting);
  for(const event of ["loadedmetadata","canplay","playing","ended","error"])audio.addEventListener(event,ready);
  audio.addEventListener("playing",()=>{attempts=0;warning.hidden=true;});
  audio.addEventListener("error",async()=>{
    if(!current() || recovering)return;
    if(attempts>=1){warning.textContent="Playback unavailable. You can download the original.";warning.hidden=false;return;}
    recovering=true;attempts++;const position=audio.currentTime, resume=!audio.paused;waiting();
    try {
      const result=await api("/object-url",{key});if(!current())return;
      audio.src=result.url;
      audio.addEventListener("loadedmetadata",()=>{if(current()){audio.currentTime=position;if(resume)void audio.play().catch(()=>{});}},{once:true});
      warning.hidden=true;
    }catch{if(current()){warning.textContent="Playback unavailable. You can download the original.";warning.hidden=false;ready();}}
    finally{recovering=false;}
  });
}

function renderStructuredAsset(asset, epoch) {
  const doc = asset.document;
  if (!doc) { elements.previewBody.textContent = "Structured preview unavailable. Use Open original; the source is unchanged."; return; }
  const host = document.createElement("div"); host.className = "structured-asset";
  const transcript = ["PlayerTranscript", "BrowserTranscript"].includes(doc.entityType) ? doc : ["corrected-transcript", "edited-transcript"].includes(doc.stage) ? doc.payload?.transcript : null;
  if (transcript && Array.isArray(transcript.segments)) {
    const notice = document.createElement("p"); notice.className = "novel-notice";
    const edited = [asset.kind, doc.stage, doc.artifactType].some(kind => ["corrected-transcript", "edited-transcript"].includes(kind));
    notice.textContent = `${edited ? "Corrected transcript" : "Raw transcript"}${doc.reviewStatus ? ` · ${doc.reviewStatus}` : ""}`;
    if (doc.publicationStatus === "accepted-with-notes") notice.textContent += " Working draft with unresolved review notes.";
    if (doc.entityType === "BrowserTranscript") {notice.textContent = `Browser transcript${doc.reviewStatus ? ` · ${doc.reviewStatus}` : ""}`;notice.title="Speakers are unassigned; timestamps mark transcription windows.";}
    host.append(notice);
    if (transcript.captureIntegrity) host.append(detailBlock("Capture integrity and warnings", transcript.captureIntegrity));
    const people = new Map((transcript.players || []).map(p => [p.id, p.name]));
    const bundle=transcript.entityType==='EditorialTranscriptBundle';
    if(bundle)notice.textContent+=' Times belong to each source session; this collection has no shared audio timeline.';
    const navigation = bundle ? {
      add(line,segment) {if(sameGameKey(segment.sourceKey)){const source=assetLink({key:segment.sourceKey},'Source transcript');line.append(source);}},
      finish() {},
    } : transcriptNavigation(host, asset, transcript, epoch, people);
    for (const segment of transcript.segments) {
      const line = document.createElement("section"); line.className = "transcript-segment";
      const heading = document.createElement("h3"), text = document.createElement("p");
      heading.textContent = `${timestamp(segment.start)}–${timestamp(segment.end)} · ${people.get(segment.playerId) || segment.playerId || "Unassigned speaker"}`;
      text.textContent = typeof segment.text === "string" ? segment.text : "[Missing text]";
      line.append(heading, text);
      navigation.add(line, segment);
      const annotations = Object.fromEntries(Object.entries(segment).filter(([k]) => !["start","end","text","playerId"].includes(k)));
      if (Object.keys(annotations).length) line.append(detailBlock("Evidence and annotations", annotations));
      host.append(line);
    }
    if (doc.payload?.review) host.append(detailBlock("Correction review", doc.payload.review));
    host.append(detailBlock("Transcript corrections, uncertainty and provenance", Object.fromEntries(
      Object.entries(transcript).filter(([key]) => key !== "segments")
    )));
    if (doc.revisionHistory) host.append(detailBlock("Editorial revision history", doc.revisionHistory));
    navigation.finish();
  } else if (["Recording", "BrowserRecording"].includes(doc.entityType) && Array.isArray(doc.parts)) {
    const audio = document.createElement("audio"); audio.controls = true; audio.preload = "metadata";
    const status = document.createElement("p"); status.setAttribute("role", "status"); showLoading(status, "Finding the continuous audio playback file…");
    host.append(audio, status);
    if (doc.captureIntegrity) host.append(detailBlock("Capture integrity and warnings",doc.captureIntegrity));
    if (doc.captureWarnings?.length) host.append(detailBlock("Capture warnings",doc.captureWarnings));
    const gameId = state.gameId, current = () => epoch === previewEpoch && gameId === state.gameId && state.tokens;
    void (async () => {
      try {
        const assets = await allAssets(gameId);
        if (!current()) return;
        const copies = assets.filter(a => a.playback?.recordingKey === asset.key && sameGameKey(a.playback.audioKey)
          && assets.some(file => file.key === a.playback.audioKey && file.kind === "recording-playback"));
        copies.sort((a,b) => b.lastModified.localeCompare(a.lastModified) || a.key.localeCompare(b.key));
        if (!copies.length) {
          audio.hidden = true;
          status.textContent = "Playback is not ready yet.";
          return;
        }
        const copy = copies[0].playback;
        const result = await api("/object-url", {key:copy.audioKey});
        if (!current()) return;
        audio.src = result.url;
        attachMediaRecovery(audio, copy.audioKey, current);
        status.replaceChildren(); status.hidden=true;
      } catch (error) { if (current()) status.textContent = `${error.message}. Close and reopen to retry. Original parts are retained.`; }
    })();
  } else {
    const pre = document.createElement("pre"); pre.textContent = JSON.stringify(doc,null,2); host.append(pre);
  }
  elements.previewBody.replaceChildren(host);
}

function transcriptNavigation(host, asset, transcript, epoch, people) {
  const gameId = state.gameId, current = () => epoch === previewEpoch && gameId === state.gameId && state.tokens;
  const sessionId = asset.metadata?.sessionId || transcript.sessionId;
  const tools = document.createElement("section"); tools.className = "transcript-tools"; tools.setAttribute("aria-label", "Transcript navigation");
  const navigationPicker = optionalInfoDialog("Transcript tools", tools); host.append(navigationPicker.host);
  const label = document.createElement("label"), search = document.createElement("input"), results = document.createElement("p"), previous = document.createElement("button"), next = document.createElement("button");
  label.textContent = "Search speech or player names"; search.type = "search"; search.maxLength = 500; search.id = "transcript-search"; label.htmlFor = search.id;
  search.placeholder = "Find a name, place or phrase…"; results.setAttribute("role", "status");
  previous.type = next.type = "button"; previous.className = next.className = "quiet-button";
  previous.textContent = "Previous match"; next.textContent = "Next match";
  tools.append(label, search, previous, next, results);
  const versionLabel = document.createElement("label"), versions = document.createElement("select");
  versions.id = "transcript-version"; versions.disabled = true; versionLabel.htmlFor = versions.id; versionLabel.textContent = "Session transcript version";
  versions.add(new Option("Finding saved versions…", asset.key)); tools.append(versionLabel, versions);
  const selection = document.createElement("div"), selectionStatus = document.createElement("p");
  selectionStatus.setAttribute("role", "status"); selectionStatus.textContent = sessionId ? "Checking the explicit canonical selection…" : "Canonical selection unavailable: this transcript has no session identity.";
  selection.append(selectionStatus); tools.append(selection);
  const source = document.createElement("section"), sourceHeading = document.createElement("h3"), sourceStatus = document.createElement("p"), audio = document.createElement("audio");
  sourceHeading.textContent = "Recording";
  sourceStatus.setAttribute("role", "status"); sourceStatus.textContent = "Finding the exact source recording and its continuous listening copy…";
  audio.controls = true; audio.preload = "metadata"; audio.hidden = true;
  source.append(sourceHeading, sourceStatus, audio); tools.append(source);
  const lines = []; let matches = [], position = -1;
  const update = () => {
    const query = search.value.trim().toLocaleLowerCase();
    matches = []; position = -1;
    lines.forEach((entry,index) => {
      entry.line.classList.remove("transcript-match", "transcript-current-match");
      if (query && entry.search.includes(query)) { matches.push(index); entry.line.classList.add("transcript-match"); }
    });
    previous.disabled = next.disabled = matches.length === 0;
    results.textContent = query ? `${matches.length} matching ${matches.length === 1 ? "line" : "lines"}.` : "";
  };
  const move = direction => {
    if (!matches.length) return;
    lines.forEach(entry => entry.line.classList.remove("transcript-current-match"));
    position = position < 0 ? (direction > 0 ? 0 : matches.length - 1) : (position + direction + matches.length) % matches.length;
    const line = lines[matches[position]].line;
    line.classList.add("transcript-current-match"); line.tabIndex = -1;
    line.scrollIntoView({block:"center", behavior:"instant"}); line.focus({preventScroll:true});
    results.textContent = `Match ${position+1} of ${matches.length}.`;
  };
  search.addEventListener("input", update);
  search.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); move(event.shiftKey ? -1 : 1); } });
  previous.onclick = () => move(-1); next.onclick = () => move(1);
  versions.onchange = () => { const chosen = versions.value; if (sameGameKey(chosen)) void previewFile({key:chosen,name:versions.selectedOptions[0].textContent}); };
  const seeks = [];
  let duration = null;
  const seek = async seconds => {
    if (!current() || duration === null || !Number.isFinite(seconds) || seconds < 0 || seconds >= duration) return;
    if (!navigationPicker.dialog.open) navigationPicker.dialog.showModal();
    try { audio.currentTime = seconds; await audio.play(); }
    catch { if (current()) sourceStatus.textContent = "Playback could not start. Use the source audio controls or refresh its link; transcript evidence is unchanged."; }
  };
  const configure = async () => {
    try {
      const assets = await allAssets(gameId);
      if (!current()) return;
      const variants = assets.filter(a => a.metadata?.sessionId === sessionId && ["transcript","raw-transcript","corrected-transcript","edited-transcript"].includes(a.kind) && a.key.endsWith(".json"));
      variants.sort((a,b) => b.lastModified.localeCompare(a.lastModified) || a.key.localeCompare(b.key));
      versions.replaceChildren();
      for (const variant of variants) {
        const v = variant.metadata?.extra?.version;
        versions.add(new Option(`${variant.kind.replaceAll("-"," ")} · ${v ? `v${v.number}` : "version unavailable"} · ${variant.metadata?.title || variant.name}`, variant.key));
      }
      if (!variants.some(a => a.key === asset.key)) versions.add(new Option("Viewed version · not present in the catalog", asset.key));
      versions.value = asset.key; versions.disabled = versions.options.length < 2;
      const index = new Map(assets.map(a => [a.key,a])), visited = new Set(), pending = [asset.key], recordings = new Map();
      while (pending.length) {
        const key = pending.pop(); if (visited.has(key) || !sameGameKey(key)) continue; visited.add(key);
        const candidate = index.get(key); if (!candidate) continue;
        if (candidate.recording?.partCount > 0) { recordings.set(key,candidate); continue; }
        pending.push(...(candidate.sourceKeys || []));
      }
      if (recordings.size !== 1) { sourceStatus.textContent = recordings.size ? "Multiple source recordings are associated. Open Inputs to choose one; no source is guessed." : "No exact source recording is linked. Original evidence remains available in Inputs."; return; }
      const [recordingKey, recording] = [...recordings][0];
      source.append(assetLink(recording, "Open source recording"));
      const copies = assets.filter(a => a.playback?.recordingKey === recordingKey && sameGameKey(a.playback.audioKey) && index.get(a.playback.audioKey)?.kind === "recording-playback");
      copies.sort((a,b) => b.lastModified.localeCompare(a.lastModified) || a.key.localeCompare(b.key));
      if (!copies.length) { sourceStatus.textContent = "The linked source recording has no completed continuous listening copy yet. Open the source recording for status and original files."; return; }
      const copy = copies[0].playback, signed = await api("/object-url", {key:copy.audioKey});
      if (!current()) return;
      audio.hidden = false; audio.src = signed.url;
      attachMediaRecovery(audio, copy.audioKey, current);
      const ready = () => { if (current()) { duration = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : null; seeks.forEach(({button,start}) => { button.disabled = duration === null || !Number.isFinite(start) || start < 0 || start >= duration; }); } };
      audio.addEventListener("loadedmetadata", ready);
      if (audio.readyState >= 1) ready();
      sourceStatus.textContent = ""; sourceStatus.hidden = true;
    } catch (error) { if (current()) { versions.replaceChildren(new Option("Version navigation unavailable",asset.key)); sourceStatus.textContent = `Source navigation unavailable: ${error.message}. Use Inputs or reopen to retry.`; } }
  };
  void configure();
  if (sessionId && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(sessionId)) void (async () => {
    try {
      let chosen = await api("/transcript-selection", {gameId,sessionId});
      if (!current()) return;
      const report = () => {
        selectionStatus.textContent = chosen.warning || (chosen.selection
          ? `${chosen.selection.key === asset.key ? "Viewing the canonical reading version" : "Viewing a non-canonical version"}.`
          : "No canonical reading version has been designated.");
        selection.querySelector('[data-canonical-link]')?.remove();
        if (chosen.selection?.key && chosen.selection.key !== asset.key && sameGameKey(chosen.selection.key)) {
          const link = assetLink({key:chosen.selection.key}, "Open canonical reading version"); link.dataset.canonicalLink = "true"; selection.append(link);
        }
      };
      report();
      const details = document.createElement("section"), heading = document.createElement("h3"), explanation = document.createElement("p"), reasonLabel = document.createElement("label"), reason = document.createElement("input"), confirmLabel = document.createElement("label"), confirm = document.createElement("input"), button = document.createElement("button"), status = document.createElement("p");
      heading.textContent = "Choose this canonical reading version";
      explanation.textContent = "This changes a session pointer only. It does not correct raw text, verify speakers, approve game facts or regenerate adaptations. Previous selections are retained.";
      reason.id = "canonical-reason"; reason.maxLength = 500; reasonLabel.htmlFor = reason.id; reasonLabel.textContent = "Selection reason";
      confirm.type = "checkbox"; confirmLabel.append(confirm, " I understand this is a reading selection, not human verification.");
      button.type = "button"; button.className = "quiet-button"; button.textContent = "Use this version as canonical"; button.disabled = true;
      status.setAttribute("role", "status");
      const enable = () => { button.disabled = !confirm.checked || !reason.value.trim(); };
      reason.addEventListener("input", enable); confirm.addEventListener("change", enable);
      let request;
      button.onclick = async () => {
        request ||= {gameId, sessionId, key:asset.key, expectedRevision:chosen.selection?.revision || null,
          reason:reason.value.trim(), operationId:crypto.randomUUID().replaceAll("-","")};
        reason.disabled = confirm.disabled = button.disabled = true; status.textContent = "Saving the guarded selection…";
        try {
          await api("/transcript-selection", {}, {body:request});
          chosen = await api("/transcript-selection", {gameId,sessionId});
          if (!current()) return;
          report(); status.textContent = "Selection saved. Immutable transcripts and review state are unchanged.";
        } catch (error) { if (current()) { status.textContent = `Selection not confirmed: ${error.message}. An exact retry uses the same operation identity; reload if another selection changed.`; button.disabled = false; } }
      };
      details.append(explanation, reasonLabel, reason, confirmLabel, button, status); selection.append(optionalInfoDialog(heading.textContent, details).host);
    } catch (error) { if (current()) selectionStatus.textContent = `Canonical selection unavailable: ${error.message}. No version is assumed canonical.`; }
  })();
  return {
    add(line, segment) {
      lines.push({line, search:`${people.get(segment.playerId) || segment.playerId || "Unassigned speaker"} ${segment.text || ""}`.toLocaleLowerCase()});
      const button = document.createElement("button"); button.type = "button"; button.className = "quiet-button transcript-seek";
      button.textContent = `Listen from ${timestamp(segment.start)}`; button.disabled = true;
      button.onclick = () => { void seek(segment.start); }; line.append(button); seeks.push({button,start:segment.start});
    },
    finish: update,
  };
}

document.getElementById("library-refresh").addEventListener("click", () => { assetIndex = null; void renderRoute(); });
novel.refresh.addEventListener("click", () => { assetIndex = null; void renderRoute(); });
document.getElementById("character-create").addEventListener("click", createCharacter);
novel.back.addEventListener("click", () => navigate(gamePath("novel") + (currentNovelBook ? `?book=${encodeURIComponent(currentNovelBook.id)}&bookRevision=${encodeURIComponent(currentNovelBook.revision)}` : "")));
novel.read.addEventListener("click", () => novelView(false));
novel["show-details"].addEventListener("click", () => novelView(true));
novel.download.addEventListener("click", () => {
  if (!currentChapter) return;
  const url = URL.createObjectURL(new Blob([`# ${currentChapter.title}\n\n${currentChapter.markdown}\n`], {type: "text/markdown;charset=utf-8"}));
  const link = document.createElement("a"); link.href = url; link.download = `chapter-${currentChapter.id.slice(0, 12)}.md`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});

elements.login.addEventListener("click", login);
elements.logout.addEventListener("click", logout);
elements.refresh.addEventListener("click", () => { assetIndex = null; return loadPrefix(state.currentPrefix); });
elements.loadMore.addEventListener("click", () => loadPrefix(state.currentPrefix, state.nextCursor));
elements.previewClose.addEventListener("click", closePreview);
elements.previewDialog.addEventListener("cancel", event => { event.preventDefault(); closePreview(); });
elements.previewDialog.addEventListener("click", (event) => {
  if (event.target === elements.previewDialog) closePreview();
});
// Room capture v1. IndexedDB retains closed PCM parts before any network request.
class RoomRecorder {
  constructor() {
    this.host=document.getElementById('room-recorder');this.controls=this.host.querySelector('.room-controls'); this.recording=false; this.draft=null; this.liveEnabled=false;
    this.writeChain=Promise.resolve(); this.uploadChain=Promise.resolve(); this.nodes=new Map();
    this.el=Object.fromEntries(['start','stop','status','state','timer','level','live-toggle','live','live-text','recovery','resume','download','result','result-name','audio','audio-status','capture-warning','final-status','final-link'].map(id=>[id,document.getElementById('room-'+id)]));
    this.el.audio=document.createElement('audio');this.el.audio.id='room-audio';this.el.audio.controls=true;this.el.audio.preload='metadata';this.el.audio.hidden=true;
    this.liveDialog=document.createElement('dialog');this.liveDialog.className='preview room-live-dialog';this.liveDialog.setAttribute('aria-label','Live transcript');this.liveDialog.title='Provisional recognition; speakers are unassigned';
    const closeLive=document.createElement('button');closeLive.type='button';closeLive.className='icon-button';closeLive.textContent='×';closeLive.setAttribute('aria-label','Close live transcript');closeLive.onclick=()=>this.liveDialog.close();this.liveDialog.append(closeLive,this.el.live);document.body.append(this.liveDialog);
    this.viewLive=document.createElement('button');this.viewLive.type='button';this.viewLive.className='quiet-button';this.viewLive.textContent='View transcript';this.viewLive.hidden=true;this.viewLive.onclick=()=>this.liveDialog.showModal();this.host.querySelector('.room-controls').append(this.viewLive);
    this.el.start.onclick=()=>this.start(); this.el.stop.onclick=()=>this.stop();
    this.el['live-toggle'].onclick=()=>{this.liveEnabled=!this.liveEnabled; this.buttons(); this.say(this.liveEnabled?'Live transcription enabled for new audio.':'New live requests paused. A full pass will still run after Stop.');};
    this.el.resume.onclick=()=>this.retrySave();
    this.el.result.append(this.el.recovery);
    this.retained=document.createElement('section');this.retained.id='room-retained';this.retained.setAttribute('aria-label','Unsaved recordings');this.retained.hidden=true;this.host.append(this.retained);
    this.el.download.onclick=()=>this.download();
    window.addEventListener('beforeunload',event=>{if(this.recording){event.preventDefault();event.returnValue='';}});
  }
  owner() {if(!state.tokens?.id_token) return null;try {const claims=decodeToken(state.tokens.id_token);return claims.sub || claims["cognito:username"] || null;} catch {return null;}}
  async db() {
    if(!this.database) this.database=new Promise((resolve,reject)=>{
      const request=indexedDB.open('panther-room-audio-v1',1);
      request.onupgradeneeded=()=>{request.result.createObjectStore('drafts',{keyPath:'id'});request.result.createObjectStore('parts',{keyPath:'id'});};
      request.onsuccess=()=>resolve(request.result); request.onerror=()=>reject(new Error('Browser storage is unavailable. Recording has not started.'));
    });
    return this.database;
  }
  async store(store, operation, value) {
    const db=await this.db(); return new Promise((resolve,reject)=>{
      const tx=db.transaction(store,['put','delete'].includes(operation)?'readwrite':'readonly'), request=tx.objectStore(store)[operation](value);
      tx.oncomplete=()=>resolve(request.result); tx.onerror=()=>reject(new Error('Could not save audio in this browser. Stop and download retained parts.')); tx.onabort=tx.onerror;
    });
  }
  persist() {const draft=this.draft; this.writeChain=this.writeChain.then(()=>this.store('drafts','put',structuredClone(draft))); return this.writeChain;}
  say(text,error=false) {this.el.status.textContent=text;this.el.status.hidden=!error;if(error)(this.el.result.hidden?this.host:this.el.result).append(this.el.status);}
  async retrySave() {
    if(this.recording || this.stopping || this.archiving) return;
    this.uploadError=false;this.storageError=null;this.writeChain=Promise.resolve();this.el.resume.disabled=true;this.say('');this.showResult('Saving audio…');
    try {await this.archive();} catch(error) {this.saveFailed(error);}
    finally {this.el.resume.disabled=false;this.buttons();await this.listRetained();}
  }
  saveFailed(error) {
    this.showResult('Not saved','error');this.el.recovery.hidden=false;this.el.resume.hidden=false;
    const network=['TypeError','TimeoutError','AbortError'].includes(error?.name);
    this.say(network?'Could not upload audio. It is safe in this browser. Retry saving or download it.':error.message,true);
    this.buttons();
  }
  async listRetained() {
    const drafts=await this.store('drafts','getAll');this.retained.replaceChildren();
    const pending=drafts.filter(d=>d.gameId===state.gameId && d.owner===this.owner() && d.status!=='archived' && d.parts.length && d.id!==this.draft?.id);
    this.retained.hidden=!pending.length;
    for(const draft of pending) {
      const row=document.createElement('div'),name=document.createElement('span'),save=document.createElement('button'),download=document.createElement('button');name.textContent=draft.sessionName;
      for(const [button,text] of [[save,'Save recording'],[download,'Download']]) {button.type='button';button.className='quiet-button';button.textContent=text;button.disabled=this.recording || !!this.archiving || !!this.stopping;}
      const activate=()=>{clearTimeout(this.pollTimer);this.draft=draft;this.writeChain=Promise.resolve();this.uploadChain=Promise.resolve();this.nodes.clear();this.liveDialog.close();this.viewLive.hidden=true;this.el.live.hidden=true;this.el['live-text'].replaceChildren();this.el.audio.pause();this.el.audio.hidden=true;this.el.audio.removeAttribute('src');this.audioKey=null;this.el['final-status'].hidden=true;this.el['final-link'].hidden=true;this.showResult('Not saved','error');this.el.recovery.hidden=false;this.el.resume.hidden=false;};
      save.onclick=async()=>{if(this.recording || this.archiving || this.stopping)return;activate();await this.retrySave();};
      download.onclick=async()=>{if(this.recording || this.archiving || this.stopping)return;activate();await this.download();await this.listRetained();};
      row.append(name,save,download);this.retained.append(row);
    }
  }
  buttons() {
    this.host.dataset.recording=String(this.recording); this.el.start.hidden=this.recording; this.el.stop.hidden=!this.recording;
    this.el.start.disabled=!!this.archiving || !!this.stopping;
    this.el.resume.disabled=this.recording || !!this.archiving || !!this.stopping;
    this.el['live-toggle'].disabled=!this.capabilities?.transcriptionAvailable;this.el['live-toggle'].hidden=!this.recording || !this.capabilities?.transcriptionAvailable;
    this.el['live-toggle'].setAttribute('aria-pressed',String(this.liveEnabled)); this.el['live-toggle'].textContent=this.liveEnabled?'Live text on':'Live text off';
    this.el.state.textContent=this.stopping?'Finishing…':'Recording';this.el.state.hidden=!this.recording && !this.stopping;this.el.timer.hidden=!this.recording && !this.stopping;this.el.level.hidden=!this.recording;
    elements.gameSelector.disabled=this.recording || !!this.stopping || !!this.archiving;
  }
  async render(section,epoch) {
    if(section!=='sessions')this.liveDialog.close();
    const visible=section==='sessions' || this.recording || this.stopping;
    this.controls.hidden=!visible;this.host.hidden=!visible; if(!visible) {this.el.audio.pause();return;}
    if(section==='sessions'){const heading=document.querySelector('#session-library > .explorer-heading');heading.append(this.controls);heading.after(this.host);}
    else {this.host.prepend(this.controls);document.getElementById('game-context').after(this.host);}
    try {
      this.capabilities ||= await api('/browser-recording/capabilities');
      if(epoch!==routeEpoch) return;
      if((this.recording || this.stopping || this.archiving) && this.draft?.owner!==this.owner()) {this.host.hidden=true;this.controls.hidden=true;return;}
      if(!this.capabilities.canRecord) {this.host.hidden=true;this.controls.hidden=true; return;}
      if(!this.loadedGame || this.loadedGame!==state.gameId || this.loadedOwner!==this.owner()) {
        this.loadedGame=state.gameId;this.loadedOwner=this.owner();clearTimeout(this.pollTimer);this.nodes.clear();this.liveDialog.close();this.viewLive.hidden=true;this.el['live-text'].replaceChildren();this.el.live.hidden=true;this.el.result.hidden=true;this.el.audio.pause();this.el.audio.remove();this.el.audio.hidden=true;this.el.audio.removeAttribute('src');this.audioKey=null;this.el['final-status'].hidden=true;this.el['final-link'].hidden=true;this.el.recovery.hidden=true;this.el.resume.hidden=false;
        const held=await navigator.locks?.query();
        if(held?.held.some(lock=>lock.name==='panther-room-capture')) {this.say('Another tab is using the room recorder.',true);this.el.start.disabled=true;return;}
        const drafts=await this.store('drafts','getAll');
        this.draft=drafts.filter(d=>d.gameId===state.gameId && d.owner===this.owner()).sort((a,b)=>b.startedAt.localeCompare(a.startedAt))[0] || null;
        if(this.draft) {if(this.draft.status==='archived'){this.processingStarted=this.draft.processingStarted || Date.now();this.showResult('Audio saved','ready');this.el.resume.hidden=true;this.el.recovery.hidden=false;this.el.download.hidden=false;this.transcriptionAvailability();this.schedulePoll();}else {if(this.draft.status==='recording'){this.draft.status='interrupted';this.draft.captureWarnings.push('Capture did not finish in this tab; only persisted parts are available.');}await this.persist();this.showResult('Not saved','error');this.el.recovery.hidden=false;this.say('Audio is saved in this browser. Retry saving or download it.',true);}}
        await this.listRetained();
        this.liveEnabled=!!this.capabilities.transcriptionAvailable;
      }
      this.buttons();
      if (this.draft?.status === 'archived' && this.capabilities.playbackAvailable === false) this.processingUnavailable();
    } catch(error) {this.say(error.message,true);this.el.start.disabled=true;}
  }
  async start() {
    if(this.recording || this.stopping || !this.capabilities?.canRecord || this.el.start.disabled) return;
    if(!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode || !navigator.locks) {this.say('Use a current browser on HTTPS or localhost with microphone, AudioWorklet and Web Locks support.',true);return;}
    await navigator.locks.request('panther-room-capture',{ifAvailable:true},async lock=>{
      if(!lock) {this.say('Another tab is already recording. Return to that tab to stop it.',true);return;}
      this.el.start.disabled=true;
      try {
        await this.db();
        this.stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,sampleRate:32000,echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});
        this.context=new AudioContext({sampleRate:32000});
        if(this.context.sampleRate!==32000) throw new Error('This browser cannot provide the supported 32 kHz capture format.');
        await this.context.audioWorklet.addModule(document.querySelector('meta[name="panther-pcm-worklet"]').content);
        const track=this.stream.getAudioTracks()[0];
        this.draft={owner:this.owner(),id:'recording-'+crypto.randomUUID().replaceAll('-',''),gameId:state.gameId,sessionId:'session-'+new Date().toISOString().slice(0,10)+'-'+crypto.randomUUID().slice(0,8),sessionName:'Session · '+new Date().toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}),startedAt:new Date().toISOString(),device:track.label || 'Browser microphone',status:'recording',parts:[],captureWarnings:['Browser capture does not verify hardware continuity or identify speakers.']};
        this.writeChain=Promise.resolve(); this.storageError=null; await this.persist(); this.uploadError=false; this.nodes.clear(); this.liveDialog.close();this.viewLive.hidden=true;this.el['live-text'].replaceChildren(); this.el.result.hidden=true;this.el.audio.pause();this.el.audio.remove();this.el.audio.hidden=true;this.el.audio.removeAttribute('src');this.audioKey=null;this.el['final-status'].hidden=true; this.el.recovery.hidden=true;this.el.resume.hidden=false;this.el['final-link'].hidden=true;
        this.node=new AudioWorkletNode(this.context,'panther-pcm-capture-v1'); this.source=this.context.createMediaStreamSource(this.stream);
        this.node.port.onmessage=event=>{
          if(event.data.type==='level') {const db=20*Math.log10(Math.max(event.data.peak,0.000001));this.el.level.value=Math.max(0,Math.min(1,(db+60)/60));this.el.level.title=`${Math.round(db)} dBFS`;this.el.level.setAttribute('aria-valuetext',`${Math.round(db)} decibels below full scale`);}
          if(event.data.type==='part') this.writeChain=this.writeChain.then(()=>this.savePart(event.data.samples)).catch(error=>{this.storageError=error;this.say(error.message,true);void this.stop('Browser storage failed; the active part may be incomplete.');});
          if(event.data.type==='stopped') {if(this.stopping) this.stopped?.();else if(this.recording) void this.stop('The supported recording length was reached; captured parts are retained.',true);}
        };
        this.node.onprocessorerror=()=>void this.stop('The audio processor failed; the unfinished part may be missing.');
        track.onended=()=>{if(this.recording) void this.stop('The microphone disconnected.');};
        this.source.connect(this.node);this.node.connect(this.context.destination);await this.context.resume();
        this.context.onstatechange=()=>{if(this.recording && this.context.state==='suspended') {this.draft.captureWarnings.push('The browser suspended capture; audio may be missing.');this.say('Audio capture is suspended by the browser. Return to this tab and Stop to retain captured parts.',true);}};
        this.recording=true;this.el.timer.textContent='0:00'; this.started=performance.now(); this.buttons();await this.listRetained();this.say('');
        this.timer=setInterval(()=>{this.el.timer.textContent=timestamp((performance.now()-this.started)/1000);},1000);
        await new Promise(resolve=>{this.unlock=resolve;});
      } catch(error) {
        this.stream?.getTracks().forEach(track=>track.stop());try{await this.context?.close();}catch{/* A prior capture context may already be closed. */}this.recording=false;this.el.start.disabled=false;if(this.draft && !this.draft.parts.length){await this.store('drafts','delete',this.draft.id);this.draft=null;}
        this.say(error.name==='NotAllowedError'?'Microphone access was denied. Allow microphone access to start recording.':error.message,true);this.buttons();
      }
    });
  }
  async savePart(buffer) {
    const count=buffer.byteLength/2, blob=this.wav(new Int16Array(buffer));
    const bytes=await blob.arrayBuffer(), hash=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));
    const sha=Array.from(hash,b=>b.toString(16).padStart(2,'0')).join('');
    const index=this.draft.parts.length, start=this.draft.parts.reduce((sum,p)=>sum+p.duration,0);
    const part={file:`part-${String(index).padStart(4,'0')}.wav`,start,duration:count/32000,size:blob.size,sha256:sha,sampleRate:32000,channels:1,bitsPerSample:16,uploaded:false,liveWanted:this.liveEnabled};
    await this.store('parts','put',{id:this.draft.id+'#'+index,blob});this.draft.parts.push(part);
    await this.store('drafts','put',structuredClone(this.draft));
    void this.upload();
    if(this.draft.parts.length>=this.capabilities.maxParts && this.recording) void this.stop('The supported recording length was reached; captured audio is retained.');
  }
  wav(samples) {
    const bytes=new ArrayBuffer(44+samples.length*2), view=new DataView(bytes);
    const text=(at,value)=>{for(let i=0;i<value.length;i++) view.setUint8(at+i,value.charCodeAt(i));};
    text(0,'RIFF');view.setUint32(4,bytes.byteLength-8,true);text(8,'WAVE');text(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,32000,true);view.setUint32(28,64000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);text(36,'data');view.setUint32(40,samples.length*2,true);
    samples.forEach((sample,i)=>view.setInt16(44+i*2,sample,true));return new Blob([bytes],{type:'audio/wav'});
  }
  async put(blob,filename,kind,extra,sources=[]) {
    const bytes=await blob.arrayBuffer(), hash=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));
    const sha=btoa(String.fromCharCode(...hash)), key=`games/${this.draft.gameId}/assets/${this.draft.id}/original/${filename}`;
    try {const old=await api('/object-url',{key});if(old.size===blob.size && old.metadata?.extra?.sha256===sha) return {key,hex:Array.from(hash,b=>b.toString(16).padStart(2,'0')).join('')};throw new Error('An existing archive object differs. Retained audio will not be overwritten.');} catch(error) {if(error.status!==404) throw error;}
    const signed=await api('/uploads',{}, {body:{gameId:this.draft.gameId,assetId:this.draft.id,kind,filename,size:blob.size,sha256:sha,contentType:blob.type,metadata:{title:kind==='recording-manifest'?this.draft.sessionName:filename,sessionId:this.draft.sessionId,category:kind==='recording'?'canonical-source':'unclassified',characterIds:[],sourceKeys:sources,extra:{...extra,sha256:sha,chunkSetId:this.draft.id,generation:{schemaVersion:1,method:kind==='recording'?'capture':'procedural',inference:'not-applicable',execution:'local',tool:kind==='recording'?'Browser Web Audio PCM capture':'Panther browser recording manifest',cost:{status:'not-applicable'}}}}}});
    const headers={...signed.headers};delete headers['Content-Length'];
    const response=await fetch(signed.url,{method:'PUT',headers,body:blob,signal:AbortSignal.timeout(45000)});
    if(!response.ok) throw new Error('Audio backup did not finish. Retained browser audio can be saved again.');
    return {key,hex:Array.from(hash,b=>b.toString(16).padStart(2,'0')).join('')};
  }
  upload() {
    this.uploadChain=this.uploadChain.then(async()=>{
      if(this.uploadError || !this.draft) return;
      if(this.draft.owner!==this.owner()) throw new Error('Sign in to the capturing account to save retained audio.');
      for(let i=0;i<this.draft.parts.length;i++) {
        const part=this.draft.parts[i];
        if(!part.uploaded) {
          const saved=await this.store('parts','get',this.draft.id+'#'+i);
          const original={recordingId:this.draft.id,...Object.fromEntries(Object.entries(part).filter(([key])=>!['uploaded','liveWanted','liveSubmitted'].includes(key)))};
          const uploaded=await this.put(saved.blob,part.file,'recording',{browserPart:original,recordingId:this.draft.id});
          part.key=uploaded.key;part.uploaded=true;await this.persist();
        }
        if(part.liveWanted && this.liveEnabled && !part.liveSubmitted && this.capabilities.transcriptionAvailable) {
          try {await api('/browser-transcriptions',{}, {body:{gameId:this.draft.gameId,recordingId:this.draft.id,mode:'live',inputKey:part.key}});part.liveSubmitted=true;await this.persist();this.schedulePoll();}
          catch {this.say('Live transcription is unavailable for this part. Source audio is retained for the full pass.',true);}
        }
      }
    }).catch(error=>{this.uploadError=true;this.saveFailed(error);});
    return this.uploadChain;
  }
  async stop(warning=null,alreadyStopped=false) {
    if(!this.recording || this.stopping) return;
    this.stopping=true;this.el.stop.disabled=true;this.buttons();this.showResult('Saving audio…');let flushFailed=false,failed=false;if(warning)this.draft.captureWarnings.push(warning);
    try {
      if(!alreadyStopped) await new Promise(resolve=>{const timeout=setTimeout(()=>{flushFailed=true;this.draft.captureWarnings.push('The processor did not confirm its final flush; the active part may be missing.');resolve();},2000);this.stopped=()=>{clearTimeout(timeout);resolve();};this.node.port.postMessage('stop');});
      this.recording=false;await this.writeChain;
      if(this.storageError)throw this.storageError;
      if(!this.draft.parts.length){await this.store('drafts','delete',this.draft.id);this.draft=null;this.el.recovery.hidden=true;this.el.result.hidden=true;this.say('No audio was captured.',true);return;}
      this.draft.status=warning || flushFailed?'interrupted':'complete';await this.persist();
    } catch(error) {failed=true;this.saveFailed(error);}
    finally {
      this.recording=false;this.el.level.value=0;clearInterval(this.timer);this.stream?.getTracks().forEach(track=>track.stop());
      this.source?.disconnect();this.node?.disconnect();try{await this.context?.close();}catch{/* Capture is stopped; retain persisted originals. */}
      this.unlock?.();this.unlock=null;this.stopping=false;this.el.stop.disabled=false;this.buttons();
    }
    if(failed)return;
    this.el.recovery.hidden=false;this.el.download.hidden=false;
    try {await this.archive();} catch(error) {this.saveFailed(error);} finally {await this.listRetained();}
  }
  interrupt() {this.liveDialog.close();this.viewLive.hidden=true;if(this.recording) void this.stop('Sign-in ended during capture. Retained parts need to be saved after signing in again.');this.capabilities=null;}
  async archive() {
    if(this.archiving) return this.archiving;
    this.archiving=this.saveArchive().finally(()=>{this.archiving=null;this.buttons();});this.buttons();return this.archiving;
  }
  async saveArchive() {
    if(this.recording || this.stopping || !this.draft?.parts.length) {this.say('No completed audio parts to save yet.',true);return;}
    if(this.draft.owner!==this.owner()) throw new Error('Sign in to the capturing account to save retained audio.');
    await this.upload();if(this.uploadError) return;
    const doc=this.draft.manifestDoc || {schemaVersion:1,entityType:'BrowserRecording',id:this.draft.id,gameId:this.draft.gameId,sessionId:this.draft.sessionId,sessionName:this.draft.sessionName,startedAt:this.draft.startedAt,device:this.draft.device,status:this.draft.status==='interrupted'?'interrupted':'complete',sourceFormat:'wav',captureWarnings:this.draft.captureWarnings,parts:this.draft.parts.map(part=>Object.fromEntries(Object.entries(part).filter(([key])=>!['uploaded','liveWanted','liveSubmitted','key'].includes(key))))};
    this.draft.manifestDoc=doc;await this.persist();
    const manifest=await this.put(new Blob([JSON.stringify(doc)],{type:'application/json'}),'recording.json','recording-manifest',{recordingId:this.draft.id});
    const completed=await api('/browser-recording/complete',{}, {body:{gameId:this.draft.gameId,recordingKey:manifest.key,manifestSha256:manifest.hex,status:'COMPLETE'}});
    this.draft.status='archived';this.draft.playbackJobId=completed.jobId;this.draft.processingStarted=Date.now();this.processingStarted=this.draft.processingStarted;await this.persist();this.buttons();this.say('Audio saved.');this.showResult(this.capabilities?.playbackAvailable===false?'Audio saved':'Preparing audio…',this.capabilities?.playbackAvailable===false?'ready':'processing');this.transcriptionAvailability();
    this.el.recovery.hidden=true;this.el.resume.hidden=true;this.el.download.hidden=false;
    if (this.capabilities?.playbackAvailable === false) this.processingUnavailable();
    this.schedulePoll();
    if(this.capabilities?.transcriptionAvailable) {
      this.el['final-status'].hidden=false;this.el['final-status'].dataset.state='processing';this.el['final-status'].textContent='Transcribing…';
      try {await api('/browser-transcriptions',{}, {body:{gameId:this.draft.gameId,recordingId:this.draft.id,mode:'final',playbackJobId:completed.jobId}});this.draft.finalRequested=true;await this.persist();this.schedulePoll();}
      catch(error) {this.draft.status='complete';await this.persist();this.el.recovery.hidden=false;this.el.resume.hidden=false;this.el['final-status'].dataset.state='error';this.el['final-status'].textContent='Transcription unavailable';this.say(`Audio saved. ${error.message || 'Transcription request failed.'} Retry to finish transcription.`,true);this.buttons();}
    }
  }
  processingUnavailable() {
    this.processingUnavailableShown=true;
    this.showResult('Audio saved', 'ready');
    this.say(this.capabilities?.playbackUnavailableReason || 'Audio processing is unavailable. Your recording is saved and can be downloaded.', true);
    this.el.recovery.hidden = false; this.el.resume.hidden = true; this.el.download.hidden = false;
  }
  transcriptionAvailability() {if(!this.capabilities?.transcriptionAvailable){this.el['final-status'].hidden=false;this.el['final-status'].dataset.state='unavailable';this.el['final-status'].textContent=config.development?'Transcription unavailable locally':'Transcription not configured';this.el['final-status'].title=this.capabilities?.transcriptionUnavailableReason || 'Server transcription is not configured.';}}
  showResult(text,state='processing') {this.el.result.hidden=false;const libraryStatus=document.getElementById('library-status');if(libraryStatus.dataset.empty==='true' && !libraryStatus.querySelector('.loading-state')) libraryStatus.hidden=true;this.el['result-name'].textContent=this.draft.sessionName;this.el['audio-status'].textContent=text;this.el['audio-status'].dataset.state=state;this.el['capture-warning'].hidden=true;this.el['capture-warning'].title=this.draft.captureWarnings.at(-1);}
  schedulePoll() {clearTimeout(this.pollTimer);this.pollTimer=setTimeout(()=>void this.poll(),1000);}
  async poll() {
    if(!this.draft || !state.tokens) return;
    const draft=this.draft;
    try {
      let pending=false;
      for(const mode of ['live',...(this.draft.finalRequested?['final']:[])]) {
        const result=await api('/browser-transcriptions',{gameId:draft.gameId,recordingId:draft.id,mode,...(draft.playbackJobId?{playbackJobId:draft.playbackJobId}:{})});
        if(this.draft!==draft || state.gameId!==draft.gameId || !state.tokens) return;
        if(this.pollError){this.pollError=false;this.say('');}
        if (mode === 'live' && draft.playbackJobId && !result.playback) {
          this.processingUnavailableShown=true;
          this.showResult('Audio saved · Status unavailable', 'waiting');
          this.say('The processing job could not be found. Your original audio is saved and can be downloaded.', true);
          this.el.recovery.hidden=false; this.el.resume.hidden=true; this.el.download.hidden=false;
        }
        if(result.playback) {
          if(result.playback.status==='DONE' && this.processingUnavailableShown){this.processingUnavailableShown=false;this.say('');}
          const playback=result.playback, blocked=['FAILED','BLOCKED','DEFERRED'].includes(playback.status), queued=['SUBMITTED','QUEUED'].includes(playback.status), delayed=Date.now()-(this.processingStarted || Date.now())>600000;pending ||= !['DONE','FAILED','BLOCKED','DEFERRED'].includes(playback.status);
          this.showResult(playback.status==='DONE'?'Audio ready':blocked?'Audio saved':queued?'Audio saved · Waiting for processing':delayed?'Audio saved · Processing delayed':'Preparing audio…',playback.status==='DONE'||blocked?'ready':queued||delayed?'waiting':'processing');
          if(blocked){this.say(playback.message || 'Audio processing failed. Original audio is saved and can be downloaded.',true);this.el.recovery.hidden=false;this.el.resume.hidden=true;this.el.download.hidden=false;}
          if(playback.audioKey && this.audioKey!==playback.audioKey) {const link=await api('/object-url',{key:playback.audioKey});if(this.draft!==draft || state.gameId!==draft.gameId) return;this.audioKey=playback.audioKey;this.el.audio.src=link.url;this.el.audio.hidden=false;this.el.result.insertBefore(this.el.audio,this.el['final-link']);}
        }
        pending ||= result.jobs.some(job=>['SUBMITTED','RUNNING'].includes(job.status));
        if(mode==='live') {
          for(const job of result.jobs) if(job.status==='DONE' && !this.nodes.has(job.id)) {
            this.el.live.hidden=false;this.viewLive.hidden=false;const line=document.createElement('p'), time=document.createElement('small'), text=document.createElement('span');time.textContent='~'+timestamp(job.start);text.textContent=job.text;line.append(time,text);this.el['live-text'].append(line);this.nodes.set(job.id,line);
          }
          if(result.jobs.some(job=>job.status==='UNKNOWN')) this.say('Some live transcription outcomes are unknown. Audio is retained; paid requests will not be repeated automatically.',true);
        } else {
          const blocked=['FAILED','BLOCKED','DEFERRED'].includes(result.playback?.status) || result.jobs.some(job=>['UNKNOWN','FAILED'].includes(job.status));
          pending ||= !result.transcriptKey && !blocked;
          this.el['final-status'].hidden=false;this.el['final-status'].dataset.state=result.transcriptKey?'ready':blocked?'error':Date.now()-(this.processingStarted || Date.now())>120000?'waiting':'processing';this.el['final-status'].textContent=result.transcriptKey?'Transcript ready':blocked?'Transcription unavailable':Date.now()-(this.processingStarted || Date.now())>120000?'Audio saved · Transcription delayed':'Transcribing…';
          if(result.transcriptKey) {this.el['final-link'].hidden=false;this.el['final-link'].href=`/games/${this.draft.gameId}/media?asset=${encodeURIComponent(result.transcriptKey)}`;}
        }
      }
      if(this.recording || pending) this.pollTimer=setTimeout(()=>void this.poll(),5000);
    } catch(error) {if(this.draft===draft && state.tokens){if(draft.playbackJobId){this.pollError=true;this.showResult('Audio saved · Status unavailable','waiting');this.say(`Unable to check processing. ${error.message || 'Service unavailable.'} Checking again automatically.`,true);}else if(this.recording)this.say('Live transcription is temporarily unavailable. Recording continues.',true);this.pollTimer=setTimeout(()=>void this.poll(),15000);}}
  }
  async download() {
    if(!this.draft) return;
    // Separate closed originals are retained; no listening derivative is assembled by the uploader.
    for(let i=0;i<this.draft.parts.length;i++) {
      const saved=await this.store('parts','get',this.draft.id+'#'+i);const link=document.createElement('a');link.href=URL.createObjectURL(saved.blob);link.download=this.draft.parts[i].file;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),30000);
    }
  }
}
roomCapture = new RoomRecorder();

elements.characterBack.addEventListener("click", () => navigate(gamePath("characters")));
elements.gameSelector.addEventListener("change", () => {
  const section = location.pathname.endsWith("/media") ? "media" : elements.primaryNav.querySelector("[aria-current]")?.dataset.section || "dashboard";
  navigate(`/games/${encodeURIComponent(elements.gameSelector.value)}/${section}`);
});
elements.modelLoad.addEventListener("click", loadCharacterModel);
elements.modelReset.addEventListener("click", resetCharacterModel);
document.getElementById("model-version").addEventListener("change", showSelectedArtwork);
document.getElementById("appearance-state").addEventListener("change", ()=>{populateArtworkEditions();void showSelectedArtwork();});
document.getElementById("appearance-restore").addEventListener("click", restoreSelectedAppearance);
document.getElementById("model-zoom-in").addEventListener("click", () => zoomCharacterModel(0.8));
document.getElementById("model-zoom-out").addEventListener("click", () => zoomCharacterModel(1.25));
document.getElementById("model-pan-up").addEventListener("click", () => panCharacterModel(0, 1));
document.getElementById("model-pan-down").addEventListener("click", () => panCharacterModel(0, -1));
document.getElementById("model-pan-left").addEventListener("click", () => panCharacterModel(-1, 0));
document.getElementById("model-pan-right").addEventListener("click", () => panCharacterModel(1, 0));
elements.characterModel.addEventListener("progress", (event) => {
  const progress = Math.max(0, Math.min(1, event.detail.totalProgress || 0));
  elements.modelProgressBar.style.transform = `scaleX(${progress})`;
  elements.modelStatus.textContent = elements.characterModel.loaded && progress === 1
    ? "Model ready. Drag, zoom, or use the keyboard to explore."
    : `Loading the 3D model… ${Math.round(progress * 100)}%`;
});
function characterModelReady() {
  if (!elements.characterModel.loaded || !state.selectedModelKey) return;
  elements.modelProgressBar.style.transform = "scaleX(1)";
  elements.modelStatus.textContent = "Model ready. Drag, zoom, or use the keyboard to explore.";
  elements.modelReset.disabled = false;
  setModelControls(true);
  configureModelAnimation();
}
// Geometry/environment are ready before the final load event's shader/rAF wait.
// Initialize controls at that boundary, including on slow software-rendered devices.
elements.characterModel.addEventListener("before-render", characterModelReady);
elements.characterModel.addEventListener("load", characterModelReady);
elements.characterModel.addEventListener("error", () => {
  resetModelAnimation();
  showModelFallback("The 3D model could not be displayed. The portrait is shown instead.");
});
elements.primaryNav.addEventListener("click", (event) => {
  const link = event.target.closest("a");
  if (!link || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigate(link.getAttribute("href"));
});
document.querySelector(".brand").addEventListener("click", (event) => {
  if (!state.tokens || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigate(gamePath("dashboard"));
});
window.addEventListener("popstate", renderRoute);
window.addEventListener("storage", (event) => {
  if (event.key === LOGOUT_MARKER && event.newValue === "true") {
    clearSession();
    showWelcome("Signed out.");
  }
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.tokens) {
    ensureSession().catch(error => showWelcome(error.message));
  }
});

// Live previews are ephemeral, game-scoped projections; never add them to the asset catalog.
let liveGame = null, liveTimer = null, liveController = null, liveSerial = 0;
let liveRecords = [], liveFetchedAt = 0, liveFailure = false, liveRenderKey = null;
const liveHistory = new Map(), liveHistoryControllers = new Set();
function historyKey(record) { return `${record.recordingId}:${record.previewId}`; }
async function loadLiveHistory(record, position = "live", cursor) {
  const key = historyKey(record), game = liveGame;
  let view = liveHistory.get(key);
  if (!view) { view = {chunks:[],mode:"live",request:0,error:null}; liveHistory.set(key,view); }
  const request = ++view.request, controller = new AbortController();
  liveHistoryControllers.add(controller);
  const timeout = setTimeout(() => controller.abort(),12000);
  view.loading = true; view.error = null;
  // Freeze historical pages while new speech arrives; Live explicitly rejoins the tail.
  view.mode = position === "live" ? "live" : "history";
  drawLive();
  try {
    const query = {gameId:game,recordingId:record.recordingId,previewId:record.previewId,position};
    if (cursor !== undefined) query.cursor = String(cursor);
    const result = await api("/recordings/live/history",query,{signal:controller.signal});
    if (liveHistory.get(key)!==view || view.request!==request || game!==liveGame || !state.tokens) return;
    if (!Array.isArray(result.chunks)) throw new Error("Invalid live history");
    if (!result.chunks.length && ["before","after"].includes(position)) {
      view.error = "No more transcribed history is available in that direction yet.";
    } else {
      view.chunks = result.chunks; view.loaded = true; view.jump = position !== "live";
      view.position = position;
    }
  } catch {
    if (liveHistory.get(key)!==view || view.request!==request || game!==liveGame || !state.tokens) return;
    view.error = "Transcript history unavailable. Retry with Beginning or Live; recording may still continue.";
  } finally {
    clearTimeout(timeout); liveHistoryControllers.delete(controller);
    if (liveHistory.get(key)===view && view.request===request && game===liveGame && state.tokens) {
      view.loading = false; drawLive();
    }
  }
}
function resetLive() {
  liveSerial += 1; clearTimeout(liveTimer); liveController?.abort(); liveController = null;
  liveGame = null; liveRecords = []; liveRenderKey = null; liveFailure = false;
  for (const controller of liveHistoryControllers) controller.abort();
  liveHistoryControllers.clear(); liveHistory.clear();
  document.getElementById("recording-badge").hidden = true;
  document.getElementById("episode-create-action")?.remove();
  document.getElementById("live-recordings").replaceChildren();
  showLoading(document.getElementById("live-status"), "Checking for active recording sessions…");
}
function liveState(record) {
  if (!liveFailure && record.captureState === "stopped") return "stopped";
  if (liveFailure || record.connectionStale || record.heartbeatAgeSeconds + (Date.now() - liveFetchedAt) / 1000 > 75) return "lost";
  return record.captureState;
}
function drawLive() {
  if (!state.tokens || !liveGame || liveGame !== state.gameId) return;
  const badge = document.getElementById("recording-badge"), status = document.getElementById("live-status");
  const section=elements.primaryNav.querySelector("[aria-current]")?.dataset.section;
  document.getElementById("live-transcript").hidden = section!=="sessions" || !liveReaderOpen;
  const active = liveRecords.find(r => liveState(r) === "recording");
  const current = active || liveRecords[0];
  const mode = current ? liveState(current) : liveFailure ? "lost" : "none";
  const labels = {recording:"Recording in progress", stalled:"Recording progress stalled", stopped:"Recording stopped", lost:"Recording signal lost"};
  badge.hidden = !current || section!=="sessions" || ["none","stopped"].includes(mode); badge.dataset.state = mode; badge.href = gamePath("sessions");
  document.getElementById("recording-label").textContent = labels[mode] || "";
  status.textContent=liveFailure?'Live feed unavailable. Recording may still be running locally. Retrying automatically.':'';status.hidden=!liveFailure;renderLiveSessionEntries();
  const projected = liveRecords.map(r => ({recordingId:r.recordingId, previewId:r.previewId, sessionId:r.sessionId, mode:liveState(r), previewState:r.previewState, segments:r.segments, omittedChunks:r.omittedChunks, history:liveHistory.get(historyKey(r))}));
  const key = JSON.stringify(projected);
  if (key === liveRenderKey) return;
  liveRenderKey = key;
  const host = document.getElementById("live-recordings"), positions = new Map();
  const focusAction = host.contains(document.activeElement) ? document.activeElement.dataset.historyAction : null;
  for (const el of host.querySelectorAll(".live-lines")) positions.set(el.dataset.recording, {top:el.scrollTop, bottom:el.scrollHeight-el.scrollTop-el.clientHeight<30});
  host.replaceChildren();
  for (const record of projected.filter(record=>!liveReaderRecording||record.recordingId===liveReaderRecording)) {
    const article = document.createElement("article"), heading = document.createElement("h3"), note = document.createElement("p"), lines = document.createElement("div");
    heading.textContent=record.sessionId;heading.hidden=true;note.hidden=true;
    const view = record.history, controls = document.createElement("div"), historyNote = document.createElement("p");
    controls.className = "live-history-controls"; controls.setAttribute("role","group"); controls.setAttribute("aria-label","Transcript history navigation");
    const chunks = view?.chunks || [], first = chunks[0]?.partIndex, last = chunks.at(-1)?.partIndex;
    for (const [label,position,cursor,disabled] of [
      ["Beginning","beginning",undefined,false], ["Earlier","before",first,first===undefined || first===0],
      ["Later","after",last,last===undefined], ["Live","live",undefined,false],
    ]) {
      const button = document.createElement("button"); button.type = "button"; button.title=label;button.setAttribute('aria-label',label);button.className='icon-button';button.innerHTML=({Beginning:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4v16M18 5l-9 7 9 7z"/></svg>',Earlier:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5-8 7 8 7"/></svg>',Later:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 5 8 7-8 7"/></svg>',Live:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/></svg>'})[label];if(label==='Live')button.setAttribute('aria-pressed',String(view?.mode!=='history'));
      button.dataset.historyAction = `${record.recordingId}:${label}`; button.disabled = disabled;
      button.addEventListener("click",()=>loadLiveHistory(record,position,cursor)); controls.append(button);
    }
    historyNote.className = "live-history-status";
    historyNote.textContent = view?.error || (view?.loading ? "Loading transcript history…"
      : view?.loaded && !chunks.length ? "History is being uploaded from the recording laptop."
      : view?.position === "beginning" && first>0 ? "The beginning is still being transcribed. Retry Beginning shortly."
      : "");
    historyNote.hidden=!historyNote.textContent;
    if (view?.loading && !view?.error) showLoading(historyNote, "Fetching transcript history…");
    lines.className = "live-lines"; lines.dataset.recording = record.recordingId; lines.tabIndex = 0;
    lines.setAttribute("role", "region"); lines.setAttribute("aria-label", `Provisional transcript for ${record.sessionId}`);
    const displayed = view?.loaded ? chunks.flatMap((chunk,index) => {
      const previous = chunks[index-1];
      const missing = previous && chunk.partIndex > previous.partIndex+1
        ? [{kind:"history-pending",start:previous.end,text:"Earlier audio in this interval is still being transcribed or uploaded."}] : [];
      return [...missing,...(chunk.segments.length ? chunk.segments : [{kind:"no-speech",start:chunk.start,
        text:"No speech recognized in this audio chunk (not proof of silence)."}])];
    }) : record.segments;
    for (const segment of displayed) {
      const p = document.createElement("p"), timestamp = document.createElement("time"), seconds = Math.floor(segment.start);
      timestamp.textContent = `${segment.approximateTiming ? "~" : ""}${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,"0")}`;
      if (segment.approximateTiming) timestamp.title = "Approximate timing: recognizer end time was clipped to the audio chunk boundary. Original output retained.";
      const gap = segment.kind === "preview-gap";
      if (segment.playerId && segment.attribution === "provisional-enrolled-voice") {
        const speaker = document.createElement("span");
        const person = state.gameDetail?.players?.find(p => p.id === segment.playerId);
        speaker.textContent = `${person?.name || "Unknown player"} (provisional): `;
        speaker.className = "live-speaker";
        p.append(speaker);
      }
      if (gap || ["history-pending","no-speech"].includes(segment.kind)) { p.className = "live-gap"; p.setAttribute("role", "note"); }
      p.append(timestamp, document.createTextNode(gap
        ? "Preview gap: invalid recognizer output for this audio chunk. Original audio retained; not silence."
        : segment.text)); lines.append(p);
    }
    if (!displayed.length) lines.textContent = "No recognized speech in this view yet. This does not prove silence or confirm microphone quality.";
    article.append(heading, note, controls, historyNote, lines); host.append(article);
    const previous = positions.get(record.recordingId);
    lines.scrollTop = view?.jump ? 0 : !previous || previous.bottom ? lines.scrollHeight : previous.top;
    if (view) view.jump = false;
  }
  if (focusAction) {
    const buttons = Array.from(host.querySelectorAll("button"));
    const target = buttons.find(b=>b.dataset.historyAction===focusAction && !b.disabled)
      || buttons.find(b=>b.dataset.historyAction===`${focusAction.split(":")[0]}:Beginning`);
    target?.focus({preventScroll:true});
  }
}
async function refreshLive() {
  clearTimeout(liveTimer);
  if (!state.tokens || !liveGame || document.hidden) return;
  liveController?.abort();
  const controller = new AbortController(), serial = ++liveSerial, game = liveGame;
  liveController = controller;
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const result = await api("/recordings/live", {gameId:game}, {signal:controller.signal});
    if (serial !== liveSerial || game !== state.gameId || !state.tokens) return;
    if (!Array.isArray(result.recordings)) throw new Error("Invalid live feed");
    liveRecords = result.recordings; liveFetchedAt = Date.now(); liveFailure = false;
  } catch {
    if (serial !== liveSerial || game !== state.gameId || !state.tokens) return;
    liveFailure = true;
  } finally {
    clearTimeout(timeout);
    if (serial === liveSerial && game === state.gameId && state.tokens) {
      drawLive(); liveTimer = setTimeout(refreshLive, 20000);
      if (!document.getElementById("live-transcript").hidden) for (const record of liveRecords) {
        const view = liveHistory.get(historyKey(record));
        if (!view || (view.mode === "live" && !view.loading)) void loadLiveHistory(record);
      }
    }
  }
}
document.getElementById("recording-badge").addEventListener("click", event => {
  if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();const record=liveRecords.find(item=>liveState(item)==="recording")||liveRecords[0];if(record)openLiveReader(record.recordingId);
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { clearTimeout(liveTimer); liveController?.abort(); }
  else { drawLive(); void refreshLive(); }
});
setInterval(() => { if (!document.hidden) drawLive(); }, 5000);

async function start() {
  if (!config?.apiUrl || !config?.clientId || !config?.cognitoDomain || !config?.redirectUri) {
    showWelcome("The media explorer is not configured yet.");
    return;
  }
  try {
    const initial = document.getElementById("page-loading"); initial.hidden = false;
    showLoading(initial, "Restoring your Panther session…");
    await completeLogin();
    if (location.pathname === "/account/recovery") { await renderRoute(); return; }
    await ensureSession();
    await renderRoute();
  } catch (error) {
    document.getElementById("page-loading").hidden = true;
    // Offline/5xx failures must not discard a valid remembered session or route.
    showWelcome(error.message);
  }
}

// Creation requests select immutable sources; subscription workers own every editorial stage.
const editorialComposers = new Map();
const editorialPolls = new WeakMap();
async function restoreSceneVideoProgress(scene,host,gameId,epoch) {
  const current=()=>state.gameId===gameId&&routeEpoch===epoch&&host.isConnected;
  try{const result=await api('/editorial-jobs',{gameId});if(!current())return;
    const matches=(result.jobs||[]).filter(job=>job.creation?.target==='video'&&job.creation.sceneRef?.episodeId===scene.episodeId&&job.creation.sceneRef?.sceneId===scene.id);
    matches.sort((a,b)=>Number(b.createdAt||0)-Number(a.createdAt||0));
    const exact=matches.find(job=>job.creation.sceneRef.revision===scene.revision),job=exact||matches[0];if(!job)return;
    if(!exact){const note=document.createElement('p');note.textContent='Earlier scene version';host.append(note);}
    const progress=document.createElement('section');progress.className='editorial-project-progress';progress.setAttribute('aria-label','Video progress');host.append(progress);await showEditorialProgress(job.jobId,progress,gameId,'video');
  }catch{/* A bounded page that cannot be read is not evidence that no generation exists. */}
}

function openSceneVideoComposer(scene, epoch, onSceneSaved) {
  renderEditorialComposer('video', epoch, scene, onSceneSaved);
}
function transcriptSourceChoice(asset,destination,selected,updateSubmit,gameId,current) {
  const row=document.createElement('div');row.className='editorial-source-choice';
  const label=document.createElement('label'),input=document.createElement('input'),copy=document.createElement('span'),title=document.createElement('strong'),meta=document.createElement('span'),summary=document.createElement('span');
  let name='Session';input.type='checkbox';input.value=asset.key;input.setAttribute('aria-label',name);title.textContent=name;copy.className='editorial-source-copy';meta.className='editorial-source-meta';copy.append(title,meta,summary);label.append(input,copy);row.append(label);
  input.onchange=()=>{input.checked?selected.add(asset.key):selected.delete(asset.key);updateSubmit();};
  let record=null,reviewSummary=null,reviewCaption=null,review=null,observedSessionName=null,summaryError='';
  const humanTitle=value=>typeof value==='string'&&value.trim()&&!/\.(json|md|txt|wav|mp3|flac)$/i.test(value.trim())&&!/^[a-f0-9-]{24,}$/i.test(value.trim())?value.trim():null;
  const render=()=>{
    const recordedAt=record?.recordedAt||asset.metadata?.recordedAt,date=recordedAt||asset.lastModified,timestamp=date?new Date(date):null;
    const formatted=timestamp&&!Number.isNaN(timestamp.valueOf())?timestamp.toLocaleString():null;
    name=humanTitle(record?.summary?.title)||humanTitle(observedSessionName)||humanTitle(asset.metadata?.sessionName)||humanTitle(asset.metadata?.title)||(recordedAt&&formatted?`Session · ${formatted}`:'Session');
    title.textContent=name;input.setAttribute('aria-label',name);review?.setAttribute('aria-label',`Review ${name}`);if(reviewCaption?.isConnected)reviewCaption.textContent=name;
    const participants=record?.participants||asset.transcript?.participants||[],characters=record?.characters||[];
    meta.textContent=[formatted?`${recordedAt?'Recorded':'Uploaded'} ${formatted}`:null,participants.map(person=>person.name||person.id).filter(Boolean).join(', '),characters.map(character=>character.name||character.id).filter(Boolean).join(', ')].filter(Boolean).join(' · ');
    summary.textContent=record?.summary?.summary||summaryError||(['QUEUED','GENERATING'].includes(record?.status)?'Preparing summary…':record?.status==='ATTENTION'?'Summary needs attention':'');if(reviewSummary?.isConnected)reviewSummary.textContent=summary.textContent;
  };render();
  review=document.createElement('button');review.type='button';review.className='quiet-button editorial-source-review';review.textContent='Review';review.setAttribute('aria-label',`Review ${name}`);row.append(review);destination.append(row);
  const load=async()=>{if(!current()||!row.isConnected||row.closest('form')?.hidden)return;try{const result=await api('/transcript-summaries',{gameId,key:asset.key});if(!current()||!row.isConnected)return;record=result;summaryError='';render();if(result.status==='MISSING'){record=await api('/transcript-summaries',{},{body:{gameId,key:asset.key}});if(current())render();}if(['QUEUED','GENERATING'].includes(record?.status))window.setTimeout(load,4000);}catch{summaryError='Summary unavailable';render();}};void load();
  review.onclick=async()=>{
    const dialog=document.createElement('dialog');dialog.className='transcript-source-review';const heading=document.createElement('header'),caption=document.createElement('h2'),close=document.createElement('button'),description=document.createElement('p'),regenerate=document.createElement('button'),speech=document.createElement('div'),status=document.createElement('p');caption.textContent=name;reviewCaption=caption;close.type='button';close.className='quiet-button';close.textContent='Close';close.onclick=()=>dialog.close();heading.append(caption,close);description.textContent=record?.summary?.summary||'';reviewSummary=description;regenerate.type='button';regenerate.className='quiet-button';regenerate.textContent='Regenerate summary';speech.className='source-utterances';status.setAttribute('role','status');dialog.append(heading,description,regenerate,status,speech);document.body.append(dialog);dialog.onclose=()=>dialog.remove();dialog.showModal();
    let pendingRegeneration=null;
    regenerate.onclick=async()=>{regenerate.disabled=true;pendingRegeneration||={gameId,key:asset.key,operationId:crypto.randomUUID().replaceAll('-','')};try{record=await api('/transcript-summaries',{},{body:pendingRegeneration});pendingRegeneration=null;regenerate.textContent='Regenerate summary';if(!current()||!dialog.isConnected)return;render();description.textContent=record.summary?.summary||'';status.textContent=record.status==='READY'?'':'Summary queued';if(['QUEUED','GENERATING'].includes(record.status))window.setTimeout(load,4000);}catch(error){if(error.status===400)pendingRegeneration=null;status.textContent=error.message;regenerate.textContent='Retry summary';}finally{regenerate.disabled=false;}};
    try{const detail=await api('/asset-document',{gameId,key:asset.key});if(!current()||!dialog.isConnected){dialog.close();return;}const doc=detail.document,transcript=doc?.payload?.transcript||doc;observedSessionName=transcript?.sessionName||doc?.sessionName;render();const players=new Map((transcript?.players||[]).map(person=>[person.id,person.name]));for(const segment of transcript?.segments||[]){const p=document.createElement('p'),speaker=document.createElement('strong');speaker.textContent=players.get(segment.playerId)||segment.playerId||'';if(speaker.textContent)p.append(speaker,document.createTextNode(': '));p.append(document.createTextNode(segment.text||''));speech.append(p);}if(!speech.children.length)status.textContent='Transcript text unavailable';}catch(error){status.textContent=error.message;}
  };
}

function renderEditorialComposer(target, epoch, scene = null, onSceneSaved = () => {}) {
  if(target==='video'&&!scene){const old=document.getElementById('editorial-video-composer');if(old)old.hidden=true;return;}
  const gameId=state.gameId, key=`${gameId}:${target}:${scene?.sceneId||scene?.id||''}`;
  let host=document.getElementById(`editorial-${target}-composer`);
  if(!host) {host=document.createElement('section');host.id=`editorial-${target}-composer`;host.className='editorial-composer';}
  const parent=target==='novel'?document.getElementById('novel'):(scene.host||document.getElementById('scene-video-composer'));
  if(!parent)return;
  if(target==='novel')parent.querySelector('.explorer-heading').after(host);else parent.append(host);
  host.hidden=target==='novel'&&Boolean(currentChapter);
  if(host.dataset.key===key) {
    const existing=editorialComposers.get(key);
    if(existing)void showEditorialProgress(existing.jobId,existing.progress,gameId,target);
    return;
  }
  if(target==='novel')parent.querySelector('.explorer-heading > button[data-generation-action]')?.remove();
  host.dataset.key=key;host.replaceChildren();
  const current=()=>state.gameId===gameId&&host.dataset.key===key&&host.isConnected;
  const open=document.createElement('button');open.type='button';open.className='primary-button';open.dataset.generationAction='true';open.textContent=target==='novel'?'Generate chapter':'Generate video';host.append(open);if(target==='novel')parent.querySelector('.explorer-heading').append(open);
  const panel=document.createElement('div');panel.className='editorial-creation-panel';panel.hidden=true;host.append(panel);
  const projects=document.createElement('div');projects.className='editorial-existing-projects';host.append(projects);
  const loadProjects=async(cursor)=>{
    try {const result=await api('/editorial-jobs',{gameId,cursor});if(!current())return;
      for(const job of result.jobs||[])if(!job.creation||job.creation.target===target){
        const button=document.createElement('button');button.type='button';button.className='quiet-button';button.textContent=job.creation?.title||`Session ${job.sessionId||'adaptation'} · automatic`;
        button.onclick=()=>{panel.hidden=false;panel.dataset.project='true';panel.replaceChildren();const progress=document.createElement('section');progress.className='editorial-project-progress';panel.append(progress);editorialComposers.set(key,{jobId:job.jobId,progress});if(target==='novel')syncNovelEmptyState();void showEditorialProgress(job.jobId,progress,gameId,target);};projects.append(button);
      }
      if(result.cursor){const more=document.createElement('button');more.type='button';more.className='text-link-button';more.textContent='More projects';more.onclick=()=>{more.remove();void loadProjects(result.cursor);};projects.append(more);}
    }catch{/* Creation remains available if the optional project list is unavailable. */}
  };
  if(target==='novel')void loadProjects();
  open.onclick=async()=>{
    if(panel.dataset.project==='true'){panel.replaceChildren();panel.dataset.project='false';panel.hidden=true;}
    panel.hidden=!panel.hidden;open.setAttribute('aria-expanded',String(!panel.hidden));
    if(target==='novel'){open.hidden=!panel.hidden;syncNovelEmptyState();}
    if(panel.hidden||panel.childNodes.length)return;
    const form=document.createElement('form'), fields=document.createElement('div'), status=document.createElement('p');status.setAttribute('role','status');
    const field=(label,multiline=false)=>{const wrapper=document.createElement('label'), caption=document.createElement('span'), input=document.createElement(multiline?'textarea':'input');caption.textContent=label;wrapper.append(caption,input);fields.append(wrapper);return input;};
    const isVideo=target==='video';
        const brief=field('Prompt',true);brief.maxLength=4000;brief.required=true;
    const isMap=isVideo&&scene.type==='map';
    brief.placeholder=isMap?'The travelers move from the city to the badlands…':isVideo?'Describe the scene you want to create…':'Describe the chapter you want to create…';
    if(isVideo)brief.value=[scene.name||scene.title,scene.description].filter(Boolean).join('\n\n');
    const selected=new Set(), selectedContext=new Set(), selectedCharacters=new Set();
    const cast=document.createElement('fieldset'),castLegend=document.createElement('legend'),castOptions=document.createElement('div'),castPreview=document.createElement('p');
    castLegend.textContent='Characters';castOptions.className='editorial-cast-options';castPreview.className='editorial-cast-preview';castPreview.setAttribute('aria-live','polite');cast.append(castLegend,castOptions,castPreview);
    const sources=document.createElement('fieldset'), legend=document.createElement('legend');legend.textContent='Transcripts';sources.append(legend);
    const referenceContents=document.createElement('div'), contexts=document.createElement('div'), referenceStatus=document.createElement('p'); referenceStatus.setAttribute('role','status'); referenceContents.append(referenceStatus,isVideo?sources:contexts);
    const referencePicker=optionalInfoDialog(isVideo?'Choose sources':'Add context', referenceContents);
    const references=referencePicker.host;
    const submit=document.createElement('button');submit.type='submit';submit.className='primary-button';submit.textContent=isVideo?'Generate':'Generate chapter';submit.disabled=true;
    const note=document.createElement('small');note.className='editorial-generation-note';note.textContent='Prepares prompts and a video plan. Rendering requires approval.';
    const map=isMap?sceneMapPicker(gameId,scene.mapAssetKey,current,()=>updateSubmit()):null;
    if(isMap)referenceContents.insertBefore(cast,sources);
    if(isVideo){const actions=document.createElement('div');actions.className='scene-generation-actions';actions.append(references,submit);form.append(fields,...(map?[map.host]:[]),...(isMap?[]:[cast]),actions,note,status);}else {const cancel=document.createElement('button');cancel.type='button';cancel.className='quiet-button';cancel.textContent='Cancel';cancel.onclick=()=>{panel.hidden=true;open.hidden=false;open.setAttribute('aria-expanded','false');syncNovelEmptyState();};const actions=document.createElement('div');actions.className='editorial-form-actions';actions.append(submit,cancel);form.append(fields,sources,references,actions,status);}
    if (!isVideo) {
      const write = document.createElement('button'); write.type = 'button'; write.className = 'text-link-button'; write.textContent = 'Write manually';
      write.onclick = () => manualChapterEditor(); form.append(write);
    }
    panel.append(form);if(target==='novel')syncNovelEmptyState();
    const updateSubmit=()=>{submit.disabled=isVideo?!brief.value.trim()||Boolean(map&&!map.value()):!brief.value.trim();};brief.addEventListener('input',updateSubmit);if(map)map.start();
    const choices=(assets,destination,set)=>{for(const asset of assets){if(!isVideo&&destination===sources){transcriptSourceChoice(asset,destination,set,updateSubmit,gameId,current);continue;}const label=document.createElement('label'), input=document.createElement('input'), text=document.createElement('span');input.type='checkbox';input.value=asset.key;text.textContent=asset.metadata?.title||asset.name||asset.key.split('/').at(-1);input.onchange=()=>{input.checked?set.add(asset.key):set.delete(asset.key);updateSubmit();};label.className='editorial-source-choice';label.append(input,text);destination.append(label);}};
    const page=async(section,destination,set,predicate,cursor)=>{
      showLoading(status,'Loading sources…');if(referencePicker.dialog.open)showLoading(referenceStatus,'Loading sources…');
      try{const result=await api('/assets',{gameId,section,cursor});if(!current())return;
        choices(result.assets.filter(predicate),destination,set);status.textContent='';referenceStatus.textContent='';
        if(result.cursor){const more=document.createElement('button');more.type='button';more.className='quiet-button';more.textContent='Load more';more.onclick=()=>{more.remove();void page(section,destination,set,predicate,result.cursor);};destination.append(more);}
        if(!destination.querySelector('label')){const empty=document.createElement('p');empty.textContent=section==='transcripts'?'No completed transcripts yet.':'No context sources yet.';destination.append(empty);}
      }catch(error){if(current()){status.textContent=error.message;referenceStatus.textContent=error.message;}}
    };
    const loadCast=async(cursor)=>{
      try{const result=await api('/characters',{gameId,cursor});if(!current())return;
        for(const character of result.characters||[]){const id=character.characterId||character.id;if(!id)continue;
          const label=document.createElement('label'),input=document.createElement('input'),name=document.createElement('span');label.className='editorial-source-choice editorial-character-choice';input.type='checkbox';input.value=id;name.textContent=character.name;
          input.onchange=()=>{input.checked?selectedCharacters.add(id):selectedCharacters.delete(id);label.dataset.selected=String(input.checked);castPreview.textContent=[...castOptions.querySelectorAll('input:checked')].map(input=>input.nextElementSibling.textContent).join(' · ');};if(scene.characterIds?.includes(id)){input.checked=true;selectedCharacters.add(id);label.dataset.selected='true';}
          label.append(input,name);castOptions.append(label);castPreview.textContent=[...castOptions.querySelectorAll('input:checked')].map(input=>input.nextElementSibling.textContent).join(' · ');
        }
        if(result.cursor){const more=document.createElement('button');more.type='button';more.className='quiet-button';more.textContent='More characters';more.onclick=()=>{more.remove();void loadCast(result.cursor);};castOptions.append(more);}
        if(!castOptions.childNodes.length)cast.hidden=true;
      }catch(error){if(current()){status.textContent=error.message;referenceStatus.textContent=error.message;}}
    };
    if(isVideo){updateSubmit();if(!isMap)void loadCast();let castStarted=false;referencePicker.button.addEventListener('click',()=>{if(isMap&&!castStarted){castStarted=true;void loadCast();}if(!sources.querySelector('label,p'))void page('transcripts',sources,selected,a=>a.kind==='raw-transcript'&&a.key.endsWith('.json'));});}
    else {
      await page('transcripts',sources,selected,a=>a.kind==='raw-transcript'&&a.key.endsWith('.json'));
      referencePicker.button.addEventListener('click',()=>{if(!contexts.childNodes.length)void page('all',contexts,selectedContext,a=>['.json','.md','.txt'].some(ext=>a.key.endsWith(ext))&&!['raw-transcript','reading-script','test-script','holdout','provenance','migration-report','audit-report','generation-metadata'].includes(a.kind)&&!/(?:^|[\/_-])(audit|migration|provenance|manifest|processing)(?:[\/_.-]|$)/i.test(a.key)&&!['grounded-adaptation','creative-reimagining','playful-derivative'].includes(a.metadata?.category)&&(a.metadata?.extra?.contextUse==='creative-evidence'||['game-context','lore','character-profile','corrected-transcript'].includes(a.kind)));});
    }
    let pendingMap=null;
    form.onsubmit=async event=>{
      event.preventDefault();if(isVideo?!brief.value.trim()||Boolean(map&&!map.value()):!brief.value.trim())return;
      if(selected.size>8||selectedContext.size>12||selectedCharacters.size>12){status.textContent='Choose up to 8 transcripts and 12 characters.';return;}
      const controls=[...form.querySelectorAll('input,textarea,select,button')];for(const control of controls)control.disabled=true;status.textContent=isVideo?'Preparing video…':'Starting chapter…';
      try {
        if(map&&(pendingMap||map.value()!==scene.mapAssetKey)){
          pendingMap||={gameId,id:scene.id,episodeId:scene.episodeId,name:scene.name,description:scene.description||'',type:'map',mapAssetKey:map.value(),selectedOutputKey:scene.selectedOutputKey||null,expectedRevision:scene.revision,operationId:crypto.randomUUID().replaceAll('-','')};
          const saved=await api('/scenes',{},{body:pendingMap});if(!current())return;scene=saved.record;pendingMap=null;onSceneSaved(scene);
        }
        const creation=isVideo?{schemaVersion:2,target,brief:brief.value.trim(),characterIds:[...selectedCharacters],sourceKeys:[...selected],contextKeys:[],sceneRef:{episodeId:scene.episodeId,sceneId:scene.sceneId||scene.id,revision:scene.revision}}:{schemaVersion:3,target,brief:brief.value.trim(),sourceKeys:[...selected],contextKeys:[...selectedContext]};
        const job=await api('/editorial-jobs',{}, {body:{gameId,creation}});
        if(!current())return;form.hidden=true;status.textContent='';panel.dataset.project='true';open.hidden=true;if(isVideo)document.getElementById('scene-work-progress')?.replaceChildren();
        const progress=document.createElement('section');progress.className='editorial-project-progress';progress.setAttribute('aria-label',isVideo?'Video progress':'Chapter progress');panel.append(progress);if(target==='novel')syncNovelEmptyState();
        editorialComposers.set(key,{jobId:job.jobId,progress});void showEditorialProgress(job.jobId,progress,gameId,target);
      }catch(error){if(current()){status.textContent=error.status===409?'This scene changed. Reopen it before generating.':error.message;if(error.status===400)pendingMap=null;for(const control of controls)control.disabled=false;if(map&&pendingMap)map.select.disabled=true;updateSubmit();if(error.status===409)submit.disabled=true;}}
    };
  };
  if(target==='video'){open.hidden=true;void open.onclick();}
}

async function showEditorialProgress(jobId, host, gameId, target) {
  clearTimeout(editorialPolls.get(host));
  if(state.gameId!==gameId||host.closest('[hidden]')||!host.isConnected)return;
  try {
    const result=await api('/editorial-jobs',{jobId});if(state.gameId!==gameId||!host.isConnected)return;
    if(!result.job)throw new Error('The generation job could not be found.');
    if(target==='novel'){const create=document.querySelector('#novel .explorer-heading [data-generation-action]');if(create)create.hidden=false;}
    const heading=document.createElement('h2'), copy=document.createElement('p'), stages=document.createElement('ol');
    heading.textContent=result.job.creation?.title||(result.job.sessionId?`Session ${result.job.sessionId} · automatic`:(target==='video'?'Video':'Chapter'));
    const tasks=result.tasks || [], failed=['FAILED','BLOCKED','ATTENTION','DEFERRED'].includes(result.job.status);
    const terminal=failed||['NOVEL_READY','READY_FOR_VIDEO_DISCUSSION'].includes(result.job.status);
    const running=tasks.some(task=>task.status==='RUNNING')||result.job.status==='RUNNING';
    const finished=tasks.filter(task=>task.status==='DONE').length;
    copy.textContent=result.job.status==='NOVEL_READY'?'Chapter ready':result.job.status==='READY_FOR_VIDEO_DISCUSSION'?'Video plan ready':failed?(result.job.status==='FAILED'?'Generation failed':'Generation unavailable'):running?'Generating…':'Waiting for worker';
    host.replaceChildren(heading,copy);if(target==='novel')syncNovelEmptyState();
    if (failed) {
      const error=document.createElement('p');error.className='error-text';error.setAttribute('role','alert');
      error.textContent=result.job.message || result.job.error || tasks.find(task=>task.status==='FAILED')?.error || 'Generation stopped before completion.';host.append(error);
      if(target==='novel' && config.development){const write=document.createElement('button');write.type='button';write.className='quiet-button';write.textContent='Write manually';write.onclick=()=>manualChapterEditor();host.append(write);}
    } else if(!terminal && (tasks.length || running)) {
      const progress=document.createElement('progress');progress.className='editorial-stage-progress';progress.setAttribute('aria-label','Generation stages');progress.max=1;
      if(!running)progress.value=0;
      host.append(progress);
      const count=document.createElement('small');count.textContent=finished?`${finished} steps complete`:running?'Working on the current step':'Waiting for the next step';host.append(count);
    } else if(!terminal) {
      const waiting=document.createElement('p');waiting.className='muted';waiting.textContent='Generation starts when the processing worker is available.';host.append(waiting);
    }
    if(tasks.length){const activity=document.createElement('section'), heading=document.createElement('h3');heading.textContent='Stages';activity.dataset.section='stages';activity.append(heading,stages);host.append(activity);}
    if(result.job.creation?.brief){const inputs=document.createElement('section'),label=document.createElement('h3'),prompt=document.createElement('p');label.textContent='Prompt';inputs.dataset.section='prompt';prompt.textContent=result.job.creation.brief;inputs.append(label,prompt);host.append(inputs);}
    if(target==='video'&&result.job.status==='READY_FOR_VIDEO_DISCUSSION'){const note=document.createElement('p');note.className='editorial-generation-note';note.textContent='Prompts prepared. Rendering requires approval.';host.append(note);}
    for(const task of tasks){const item=document.createElement('li');item.textContent=task.stage.replace(/^(novel|video)-/,'').replaceAll('-',' ')+' · '+({DONE:'Ready',RUNNING:'Working',QUEUED:'Queued',FAILED:'Failed'}[task.status]||task.status);
      if(task.status==='DONE'&&task.output?.key){const link=document.createElement('a');link.textContent='View';link.href=`/games/${gameId}/media?asset=${encodeURIComponent(task.output.key)}`;item.append(' ',link);}stages.append(item);}
    if(target==='video'&&result.tasks.some(t=>t.stage==='video-storyboards'&&t.status==='DONE')) {
      const task=result.tasks.find(t=>t.stage==='video-storyboards');
      const link=await api('/object-url',{key:task.output.key});const response=await fetch(link.url);if(!response.ok)throw new Error('Storyboard unavailable');
      const bytes=await response.arrayBuffer();if(bytes.byteLength!==task.output.size||bytes.byteLength>2*1024**2)throw new Error('Storyboard size mismatch');
      const checksum=btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))));if(checksum!==task.output.sha256)throw new Error('Storyboard changed');
      const artifact=JSON.parse(new TextDecoder().decode(bytes));if(artifact.jobId!==jobId||artifact.gameId!==gameId||artifact.stage!=='video-storyboards')throw new Error('Invalid storyboard');
      if(state.gameId!==gameId||!host.isConnected)return;
      const boardKey=artifact.payload?.storyboardKey;
      if(sameGameKey(boardKey)) {
        const boardLink=await api('/object-url',{key:boardKey});if(state.gameId!==gameId||!host.isConnected)return;
        const image=document.createElement('img');image.className='editorial-storyboard-image';image.alt='Schematic storyboard panels';image.src=boardLink.url;host.append(image);
      }
      const grid=document.createElement('div');grid.className='editorial-storyboard-grid';
      for(const shot of artifact.payload?.shots||artifact.payload?.review?.shots||[]){const card=document.createElement('article'), title=document.createElement('h3'), description=document.createElement('p');title.textContent=shot.shotId;description.textContent=shot.description;card.append(title,description);grid.append(card);}host.append(grid);
    }
    if(!terminal)editorialPolls.set(host,setTimeout(()=>void showEditorialProgress(jobId,host,gameId,target),5000));
  } catch(error) {if(host.isConnected&&state.gameId===gameId){host.textContent=error.message;editorialPolls.set(host,setTimeout(()=>void showEditorialProgress(jobId,host,gameId,target),15000));}}
}

// Account operations use the first-party HttpOnly session. Credentials never go
// into storage, URLs, generic asset APIs, or browser logs.
let accountSettingsEpoch = 0;
let accountReturnPath = "/";
function closeAccountSettings() {
  accountSettingsEpoch += 1;
  document.getElementById("account-page").hidden = true;
  document.getElementById("account-settings-body").replaceChildren();
  document.getElementById("account-section-nav").replaceChildren();
  document.getElementById("account-settings-button").removeAttribute("aria-current");
}

function visitAccount(recovery = false) {
  if (!location.pathname.startsWith("/account")) accountReturnPath = location.pathname + location.search;
  navigate(recovery ? "/account/recovery" : "/account");
}

function leaveAccount() {
  const recovery = location.pathname === "/account/recovery";
  navigate(recovery ? "/" : accountReturnPath);
  if (recovery) document.getElementById("password-recovery-button").focus();
}

async function accountRequest(action, values = {}, recovery = false) {
  if (!recovery) await ensureSession();
  return withSessionLock(async () => {
    if (!recovery && logoutPending()) throw new Error("Sign in again to manage your account.");
    const response = await fetch(recovery ? "/auth/recovery" : "/auth/account", {
      method:"POST", credentials:"same-origin", headers:{"content-type":"application/json"},
      body:JSON.stringify({action,...values}), signal:AbortSignal.timeout(30000),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Account operation failed. Please retry.");
    return result;
  });
}

function accountSection(host, title, description) {
  const section=document.createElement("section"), heading=document.createElement("h3"), copy=document.createElement("p");
  section.className="account-section";
  section.id="account-"+title.toLowerCase().replace(/[^a-z0-9]+/g,"-");
  heading.textContent=title; copy.textContent=description; section.append(heading,copy); host.append(section);
  const link=document.createElement("a"); link.href="#"+section.id; link.textContent=title;
  document.getElementById("account-section-nav").append(link);
  return section;
}

function accountField(form, label, type="text", value="") {
  const wrapper=document.createElement("label"), input=document.createElement("input"), caption=document.createElement("span");
  caption.textContent=label; input.type=type; input.value=value; input.maxLength=type==="password"?256:254;
  input.autocomplete=type==="password"?"new-password":"off"; wrapper.append(caption,input); form.insertBefore(wrapper,form.querySelector("button")); return input;
}

function accountForm(section, title, action) {
  const form=document.createElement("form"), button=document.createElement("button"), status=document.createElement("p");
  button.type="submit"; button.className="quiet-button"; button.textContent=title; status.setAttribute("role","status");
  form.append(button,status); section.append(form);
  form.addEventListener("submit", async event => {
    event.preventDefault(); const epoch=accountSettingsEpoch;
    const buttons=[...form.querySelectorAll("button")]; buttons.forEach(b=>b.disabled=true);
    showLoading(status,"Saving your account changes…");
    try {
      const message=await action();
      if (epoch===accountSettingsEpoch) status.textContent=message || "Saved.";
    } catch(error) {
      if (epoch===accountSettingsEpoch) status.textContent=error.name==="TimeoutError"?"Request timed out. Reload account details before retrying.":error.message;
    } finally {
      form.querySelectorAll('input[type="password"]').forEach(input=>input.value="");
      buttons.forEach(b=>b.disabled=false);
    }
  });
  return form;
}

async function openAccountSettings(recovery=false) {
  closeAccountSettings(); const epoch=accountSettingsEpoch;
  const panel=document.getElementById("account-page"), host=document.getElementById("account-settings-body");
  document.getElementById("page-loading").hidden=true;
  clearLibrary(); closePreview(); clearNovel();
  for(const id of ["welcome","dashboard","game-settings","characters","explorer","novel","game-context"]) document.getElementById(id).hidden=true;
  elements.primaryNav.hidden=true;
  elements.gameToolbar.hidden=true;
  panel.hidden=false;
  document.getElementById("account-settings-title").textContent=recovery?"Password recovery":"Account";
  document.getElementById("account-page-subtitle").textContent=recovery?"Get back into your account.":"Manage your profile and security.";
  document.getElementById("account-settings-back").textContent=recovery?"Back to sign in":"Back to game";
  document.getElementById("account-settings-title").tabIndex=-1;
  document.getElementById("account-settings-title").focus({preventScroll:true});
  document.getElementById("account-settings-button").setAttribute("aria-current","page");
  if(!recovery) {
    try {await ensureSession();} catch(error) {if(epoch===accountSettingsEpoch)showWelcome(error.message);return;}
    if(epoch!==accountSettingsEpoch)return;
    elements.account.hidden=false;
  }
  if (recovery) {
    const section=accountSection(host,"Recover your account","Enter your username. Recovery requires a previously verified email address. We do not disclose whether an account exists.");
    let username;
    const request=accountForm(section,"Send recovery code",async()=>{
      await accountRequest("forgot",{username:username.value.trim()},true);
      return "If this account can recover by email, a code has been sent. Check your inbox and spam folder.";
    });
    username=accountField(request,"Username"); username.required=true; username.autocomplete="username";
    let code,password,confirmation;
    const confirm=accountForm(section,"Reset password",async()=>{
      if(password.value!==confirmation.value) throw new Error("The new passwords do not match.");
      await accountRequest("confirm",{username:username.value.trim(),code:code.value.trim(),password:password.value},true);
      return "Password reset. Return to sign in with your new password.";
    });
    code=accountField(confirm,"Recovery code"); code.required=true; code.autocomplete="one-time-code";
    password=accountField(confirm,"New password","password"); password.required=true; password.minLength=16;
    confirmation=accountField(confirm,"Confirm new password","password"); confirmation.required=true;
    return;
  }
  showLoading(host,"Loading your account details…");
  let profile;
  try {profile=await accountRequest("get");}
  catch(error) {
    if(epoch===accountSettingsEpoch) {host.textContent=error.message+" If you signed in before account self-service was enabled, sign out and sign in once to enable it.";}
    return;
  }
  if(epoch!==accountSettingsEpoch) return;
  host.replaceChildren();
  const identity=accountSection(host,"Profile",`Username: ${profile.username}`);
  let displayName,avatar;
  const profileForm=accountForm(identity,"Save profile",async()=>{
    const selected=["","panther","moon","star"].some(name=>avatar.value===(name?`${window.location.origin}/avatars/${name}.svg`:""));
    await accountRequest("profile",{name:displayName.value.trim(),picture:selected?avatar.value:null}); return "Profile saved.";
  });
  displayName=accountField(profileForm,"Display name","text",profile.name); displayName.maxLength=120;
  const avatarLabel=document.createElement("label"), avatarTitle=document.createElement("span"), avatarPreview=document.createElement("img");
  avatarTitle.textContent="Avatar"; avatar=document.createElement("select"); avatar.setAttribute("aria-label","Avatar");
  for(const [name,label] of [["","No avatar"],["panther","Panther"],["moon","Moon"],["star","Star"]]) {
    const option=document.createElement("option"); option.value=name?`${window.location.origin}/avatars/${name}.svg`:""; option.textContent=label; avatar.append(option);
  }
  const knownAvatar=[...avatar.options].some(o=>o.value===profile.picture);
  if(!knownAvatar&&profile.picture) {const existing=document.createElement("option");existing.value=profile.picture;existing.textContent="Existing avatar — choose a preset to replace it";avatar.append(existing);}
  avatar.value=profile.picture || "";
  avatarPreview.className="account-avatar"; avatarPreview.alt="Selected avatar";
  function showAvatar(){const permitted=["panther","moon","star"].some(name=>avatar.value===`${window.location.origin}/avatars/${name}.svg`);avatarPreview.hidden=!permitted;if(permitted)avatarPreview.src=avatar.value;else avatarPreview.removeAttribute("src");}
  avatar.addEventListener("change",showAvatar); showAvatar(); avatarLabel.append(avatarTitle,avatar,avatarPreview); profileForm.insertBefore(avatarLabel,profileForm.querySelector("button"));

  const emailSection=accountSection(host,"Email & recovery",`Current email: ${profile.email || "Not configured"} · ${profile.emailVerified?"Verified":"Not verified"}. A replacement address becomes active only after verification.`);
  let email;
  const emailForm=accountForm(emailSection,"Send email verification",async()=>{
    await accountRequest("email",{email:email.value.trim()}); return "Verification requested for the new address. Enter the code below; your old address remains active until verified.";
  });
  email=accountField(emailForm,"Email address","email",profile.email); email.required=true; email.autocomplete="email";
  let emailCode;
  const verifyForm=accountForm(emailSection,"Verify email",async()=>{
    await accountRequest("verify-email",{code:emailCode.value.trim()});
    if(epoch===accountSettingsEpoch) emailSection.querySelector("p").textContent="Email verification completed. Return to Account to see the active address.";
    return "Email verified. Return to Account to see the active address.";
  });
  emailCode=accountField(verifyForm,"Email verification code"); emailCode.required=true; emailCode.autocomplete="one-time-code";
  accountForm(emailSection,"Resend email code",async()=>{await accountRequest("resend-email");return "Verification requested. Check the pending or current address.";});

  const passwordSection=accountSection(host,"Password","At least 16 characters, including uppercase and lowercase letters, a number and a symbol.");
  let previous,proposed,confirmation;
  const passwordForm=accountForm(passwordSection,"Change password",async()=>{
    if(proposed.value!==confirmation.value) throw new Error("The new passwords do not match.");
    await accountRequest("password",{previousPassword:previous.value,proposedPassword:proposed.value}); return "Password changed. Other sessions are not automatically signed out.";
  });
  previous=accountField(passwordForm,"Current password","password"); previous.autocomplete="current-password"; previous.required=true;
  proposed=accountField(passwordForm,"New password","password"); proposed.required=true; proposed.minLength=16;
  confirmation=accountField(passwordForm,"Confirm new password","password"); confirmation.required=true;

  const mfaSection=accountSection(host,"Authenticator security",`Authenticator MFA is ${profile.totpEnabled?"enabled":"not enabled"}. Keep a secure backup in your authenticator. Email password recovery does not remove MFA; losing the authenticator requires administrator help. Panther does not issue recovery codes.`);
  if(!profile.totpEnabled) {
    const enrollment=document.createElement("div");
    const setupForm=accountForm(mfaSection,"Set up authenticator",async()=>{
      const result=await accountRequest("mfa-start"); if(epoch!==accountSettingsEpoch)return;
      enrollment.replaceChildren();
      const secretLabel=document.createElement("label"), secret=document.createElement("input"), label=document.createElement("span");
      label.textContent="Authenticator setup key"; secret.value=result.secretCode; secret.readOnly=true; secret.autocomplete="off";
      secretLabel.append(label,secret); enrollment.append(secretLabel);
      const help=document.createElement("p"); help.textContent="Add this key manually to your authenticator as a time-based (TOTP) account. This secret is only displayed here and is removed when you leave this page."; enrollment.append(help);
      let code;
      const confirmMfa=accountForm(enrollment,"Enable authenticator",async()=>{
        const result=await accountRequest("mfa-confirm",{code:code.value.trim()});
        if(result.verified===false)throw new Error("Authenticator code was not verified. Try a fresh code.");
        if(epoch!==accountSettingsEpoch)return;
        setupForm.hidden=true;
        mfaSection.querySelector("p").textContent="Authenticator MFA is enabled. Keep a secure authenticator backup. Email password recovery does not remove MFA; losing the authenticator requires administrator help.";
        const done=document.createElement("p"); done.textContent="Authenticator enabled. Return to Account to see the current status.";
        enrollment.replaceChildren(done); return "Authenticator enabled.";
      });
      code=accountField(confirmMfa,"Authenticator code"); code.required=true; code.inputMode="numeric"; code.pattern="[0-9]{6}"; code.autocomplete="one-time-code";
      return "Setup key ready below. MFA is not enabled until the code is verified.";
    });
    mfaSection.append(enrollment);
  } else {
    let acknowledge;
    const disable=accountForm(mfaSection,"Disable authenticator",async()=>{
      if(!acknowledge.checked)throw new Error("Confirm that you want to remove authenticator protection.");
      await accountRequest("mfa-disable");
      if(epoch===accountSettingsEpoch) mfaSection.querySelector("p").textContent="Authenticator MFA is disabled. Return to Account to enroll again.";
      return "Authenticator disabled. Return to Account for the current status.";
    });
    acknowledge=accountField(disable,"I understand this removes authenticator protection","checkbox");
  }
  const sessions=accountSection(host,"Sessions","Sign out everywhere revokes Cognito refresh credentials and prevents renewal. Existing Panther API tokens can remain usable until their one-hour expiry. It also signs out this browser.");
  let confirmed;
  const allSessions=accountForm(sessions,"Sign out everywhere",async()=>{
    if(!confirmed.checked)throw new Error("Confirm that you want to sign out all devices.");
    await accountRequest("sign-out-everywhere"); await logout();
  });
  confirmed=accountField(allSessions,"Sign out all my devices","checkbox");
  if(config.development === true) {
    const development=accountSection(host,"Development","Regenerate demo records. Uploaded files and authored chapters are kept.");
    accountForm(development,"Regenerate demo data",async()=>{
      const response=await fetch("/development/seed",{method:"POST",credentials:"same-origin",headers:{"content-type":"application/json"},body:"{}",signal:AbortSignal.timeout(30000)});
      const result=await response.json();
      if(!response.ok)throw new Error(result.error || "Could not regenerate demo data.");
      window.PantherUI?.clear();
      state.games=null; state.gameDetail=null; state.charactersLoaded=false; state.mediaLoaded=false;
      return "Demo data regenerated.";
    });
  }
}
document.getElementById("account-settings-button").addEventListener("click",()=>visitAccount());
document.getElementById("password-recovery-button").addEventListener("click",()=>visitAccount(true));
document.getElementById("account-settings-back").addEventListener("click",leaveAccount);

// A single bounded projection feeds both overview and detail; no source-storage
// enumeration or worker invocation happens while browsing the Workshop.
const workshop = (() => {
  const host=document.getElementById("workshop"), list=document.getElementById("workshop-list"), detail=document.getElementById("workshop-detail");
  const health=document.getElementById("workshop-health"), more=document.getElementById("workshop-more"), filters=document.getElementById("workshop-filters");
  const labels={"session-finalization":"Session finalization",editorial:"Story & screen planning",model:"3D modeling",playback:"Audio assembly",transcription:"Transcription","video-production":"Video finishing","video-generation":"Video generation"};
  let timer=null, controller=null, rows=[], cursor=null, filter="all", epoch=0, game=null, busy=false, selected=null, loadedCursors=[], generation=0;
  const groupOpen=new Map();let graphObserver=null;
  function node(tag,text,className) {const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(className)element.className=className;return element;}
  function observation(job,stage) {
    const now=Date.now()/1000;
    if(job.status==="failed") return {status:"failed",label:"Needs attention",live:false};
    if(stage?.notBefore>now) return {status:"paused",label:`Deferred until ${new Date(stage.notBefore*1000).toLocaleString()}`,live:false};
    if(stage?.status==="running" && stage.leaseUntil && stage.leaseUntil<=now) return {status:"paused",label:"Worker check-in overdue",live:false};
    if(job.source==="local-worker" && job.status==="running" && now-job.reportedAt>180) return {status:"paused",label:"Local worker signal lost",live:false};
    const state=stage?.status || job.status;
    const live=state==="running" && (stage?.leaseUntil>now || now-(job.reportedAt || job.observedAt)<180);
    return {status:state,label:({queued:"Waiting for a worker",pending:"Not started",running:live?"Working now":"Running · activity unconfirmed",done:"Complete",paused:"Paused",failed:"Needs attention",unknown:"Status uncertain"})[state] || "Status uncertain",live};
  }
  function lead(job) {return (job.activeStages || []).find(s=>s.status==="running") || (job.activeStages || [])[0];}
  function worker(kind,live) {
    const scene=node("div",undefined,`pixel-scene ${live?"is-working":"is-resting"}`);scene.setAttribute("aria-hidden","true");scene.dataset.kind=kind;
    scene.append(node("span",undefined,"pixel-star"),node("span",undefined,"pixel-cat"),node("span",undefined,"pixel-tool"),node("span",undefined,"pixel-desk"));return scene;
  }
  function badge(view) {const span=node("span",view.label,"workshop-badge");span.dataset.state=view.status;return span;}
  function meter(job) {
    const block=node("div",undefined,"workshop-progress"), count=node("span",`${job.completedStages} of ${job.totalStages} stages complete`);
    const progress=document.createElement("progress");progress.max=Math.max(1,job.totalStages);progress.value=job.completedStages;progress.setAttribute("aria-label",`${job.title}: completed stages`);block.append(progress,count);return block;
  }
  function matches(job) {const state=observation(job,lead(job)).status;return filter==="all" || (filter==="working"?state==="running":filter==="waiting"?["queued","paused","pending"].includes(state):filter==="done"?state==="done":["failed","unknown"].includes(state));}
  function row(job) {
    const stage=lead(job), view=observation(job,stage), link=node("a",undefined,"workshop-card");
    link.href=gamePath("workflows")+"?workflow="+encodeURIComponent(job.id);
    link.addEventListener("click",event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();navigate(link.pathname+link.search);});
    const text=node("div",undefined,"workshop-card-copy");text.append(node("p",`Run · ${new Date(job.createdAt*1000).toLocaleDateString()}`,"workshop-kind"),node("h3",job.title),badge(view),node("p",stage?.label || (job.status==="done"?"All reported stages finished":"Awaiting the first stage"),"workshop-current"),meter(job));
    link.append(worker(job.kind,view.live),text,node("span","↗","workshop-go"));return link;
  }
  function drawList() {
    list.replaceChildren();const visible=[...rows].sort((a,b)=>b.createdAt-a.createdAt).filter(matches);
    for(const [kind,label] of Object.entries(labels)) {
      const runs=visible.filter(job=>job.kind===kind), all=rows.filter(job=>job.kind===kind);
      const group=node("section",undefined,"workshop-group");group.dataset.kind=kind;
      const heading=node("header"), copy=node("div"), active=all.filter(job=>observation(job,lead(job)).live).length;
      copy.append(node("h2",label),node("p",`${all.length} loaded run${all.length===1?"":"s"}${active?` · ${active} working now`:""}${cursor?" · history continues":""}`));
      heading.append(worker(kind,active>0),copy);
      const contents=node("div",undefined,"workshop-group-runs");
      if(runs.length)contents.append(...runs.map(row));
      else contents.append(node("p",all.length?"No loaded runs match this filter.":cursor?"No runs loaded for this type yet. Load more history below.":"No reported runs for this type yet.","workshop-group-empty"));
      group.append(heading,contents);list.append(group);
    }
    const summary=document.getElementById("workshop-summary");summary.replaceChildren();
    for(const [title,states] of [["Working",["running"]],["Waiting",["queued","pending","paused"]],["Finished",["done"]],["Needs attention",["failed","unknown"]]]) {
      const panel=node("div");panel.append(node("strong",String(rows.filter(j=>states.includes(observation(j,lead(j)).status)).length)),node("span",title));summary.append(panel);
    }
    document.getElementById("workshop-intro").textContent=`Browse by workflow type, then choose a run. ${rows.length} loaded runs${cursor?" · more history available":""}.`;
    more.hidden=!cursor;more.disabled=busy;
  }
  function drawDetail(job) {
    const focusedStage=detail.contains(document.activeElement)?document.activeElement.closest("[data-stage]")?.dataset.stage:null;
    document.getElementById("workshop-intro").textContent="Follow this workflow’s reported stages.";
    detail.replaceChildren();const back=node("a","← All workflows","workshop-back");back.href=gamePath("workflows");back.addEventListener("click",event=>{if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();navigate(back.pathname);});
    const stage=lead(job), view=observation(job,stage), hero=node("div",undefined,"workshop-detail-hero");
    const text=node("div");text.append(node("p",labels[job.kind],"workshop-kind"),node("h2",job.title),badge(view),meter(job),node("p",job.note,"workshop-note"));hero.append(worker(job.kind,view.live),text);
    const facts=node("dl",undefined,"workshop-facts");
    for(const [name,value] of [["Source",job.source==="local-worker"?"Local laptop worker":"Durable Panther job"],["Workflow version",job.workflowVersion || "Not reported"],["Session",job.sessionId || "Not reported"],["Last observed",new Date((job.reportedAt || job.observedAt)*1000).toLocaleString()],["Source status",job.sourceStatus || job.status]]) {facts.append(node("dt",name),node("dd",String(value)));}
    graphObserver?.disconnect();
    const chart=node("div",undefined,"workshop-flowchart");chart.setAttribute("aria-label","Workflow step flowchart");
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.classList.add("workshop-flow-lines");svg.setAttribute("aria-hidden","true");chart.append(svg);
    const nodes=new Map(), topology=job.flow;
    for(const [index,part] of job.stages.entries()) {
      const state=part.status==="done"?{status:"done",label:"Complete",live:false}:part.status==="pending"?{status:"pending",label:"Not started",live:false}:observation(job,part);
      const item=node("li");item.dataset.state=state.status;const copy=node("div");copy.append(node("h3",part.label),badge(state));
      const parents=(topology?.edges || []).filter(edge=>edge.to===part.id).map(edge=>job.stages.find(s=>s.id===edge.from)?.label).filter(Boolean);
      copy.append(node("span",parents.length?`Depends on: ${parents.join(", ")}.`:"No preceding step in this chart.","sr-only"));
      if(part.attempts) copy.append(node("p",`Attempt ${part.attempts}`));
      if(part.outputKey && sameGameKey(part.outputKey)) {const output=node("button","View stage artifact","quiet-button");output.type="button";output.addEventListener("click",()=>previewFile({key:part.outputKey,name:part.outputKey.split("/").at(-1)}));copy.append(output);}
      item.append(node("span",part.status==="done"?"✓":String(index+1).padStart(2,"0"),"workshop-step-number"),copy);
      if(state.live)item.append(worker(job.kind,true));item.dataset.stage=part.id;nodes.set(part.id,item);
    }
    if(!topology || topology.schemaVersion!==1 || !topology.lanes?.length) {
      detail.append(back,hero,facts,node("p","Step topology unavailable. Check progress to retry.","workshop-note"));return;
    }
    chart.dataset.mode=topology.mode;
    for(const lane of topology.lanes) {
      const column=node("section",undefined,"workshop-flow-lane");column.dataset.lane=lane.id;
      column.append(node("h3",lane.label,"workshop-lane-label"));const steps=node("ol",undefined,"workshop-stages");
      for(const id of lane.stageIds)if(nodes.has(id))steps.append(nodes.get(id));column.append(steps);chart.append(column);
    }
    const legend=node("p","✓ Complete · animated worker: confirmed activity · muted node: not started","workshop-note");
    detail.append(back,hero,node("h2","Step flowchart","workshop-trail-heading"),node("p",topology.note,"workshop-note"),legend,chart,facts,node("p",`Run ${job.id}`,"workshop-run-id"));
    if(focusedStage)nodes.get(focusedStage)?.querySelector("button")?.focus({preventScroll:true});
    function connectors() {
      if(!chart.isConnected || host.hidden)return;
      svg.replaceChildren();const bounds=chart.getBoundingClientRect();svg.setAttribute("viewBox",`0 0 ${bounds.width} ${bounds.height}`);
      for(const edge of topology.edges) {
        const from=nodes.get(edge.from), to=nodes.get(edge.to);if(!from || !to)continue;
        const a=from.getBoundingClientRect(), b=to.getBoundingClientRect();
        const x=a.left+a.width/2-bounds.left,y=a.bottom-bounds.top,xx=b.left+b.width/2-bounds.left,yy=b.top-bounds.top;
        const line=document.createElementNS(svg.namespaceURI,"path"), arrow=document.createElementNS(svg.namespaceURI,"path");
        if(topology.mode==="independent") {
          const right=bounds.width-5, ay=a.top+a.height/2-bounds.top, by=b.top+b.height/2-bounds.top, end=b.right-bounds.left+7;
          line.setAttribute("d",`M ${a.right-bounds.left} ${ay} H ${right} V ${by} H ${end}`);
          arrow.setAttribute("d",`M ${end+5} ${by-4} L ${end} ${by} L ${end+5} ${by+4}`);
        } else if(innerWidth<=600 && from.closest(".workshop-flow-lane")!==to.closest(".workshop-flow-lane")) {
          line.setAttribute("d",`M ${a.left-bounds.left} ${a.top+a.height/2-bounds.top} H 5 V ${yy-20} H ${xx} V ${yy-7}`);
          arrow.setAttribute("d",`M ${xx-4} ${yy-12} L ${xx} ${yy-7} L ${xx+4} ${yy-12}`);
        } else {
          const middle=y+(yy-y)/2;line.setAttribute("d",`M ${x} ${y} V ${middle} H ${xx} V ${yy-7}`);
          arrow.setAttribute("d",`M ${xx-4} ${yy-12} L ${xx} ${yy-7} L ${xx+4} ${yy-12}`);
        }
        svg.append(line,arrow);
      }
    }
    graphObserver=new ResizeObserver(connectors);graphObserver.observe(chart);requestAnimationFrame(connectors);
  }
  async function refresh(append=false) {
    if(busy || document.hidden || host.hidden || epoch!==routeEpoch || state.gameId!==game)return;
    busy=true;document.getElementById("workshop-refresh").disabled=true;more.disabled=true;
    controller=new AbortController();const request=controller, version=generation;
    const signal=AbortSignal.any([controller.signal,AbortSignal.timeout(20000)]);
    const focused=document.activeElement?.closest(".workshop-card")?.getAttribute("href");
    try {
      if(selected) {
        const result=await api("/workflows",{gameId:game,id:selected},{signal});
        if(version!==generation || epoch!==routeEpoch || host.hidden)return;drawDetail(result.workflow);
      } else {
        const starts=append?[cursor]:loadedCursors.length?loadedCursors:[null];const collected=append?[...rows]:[];
        let next=null;
        for(const start of starts) {
          const result=await api("/workflows",{gameId:game,cursor:start},{signal});
          if(version!==generation || epoch!==routeEpoch || host.hidden)return;
          collected.push(...result.workflows);next=result.cursor;
        }
        if(append)loadedCursors.push(cursor);else if(!loadedCursors.length)loadedCursors=[null];
        rows=[...new Map(collected.map(job=>[job.id,job])).values()];cursor=next;drawList();
        if(focused)Array.from(list.querySelectorAll("a")).find(a=>a.getAttribute("href")===focused)?.focus({preventScroll:true});
      }
      health.textContent=`Checked ${new Date().toLocaleTimeString()} · checks every 15 seconds while this page is visible.`;
      health.dataset.state="ok";
    } catch(error) {
      if(request.signal.aborted || version!==generation || epoch!==routeEpoch)return;
      health.textContent=`Could not update progress: ${error.message}. Displayed information may be out of date. Use Check progress to retry.`;health.dataset.state="error";
    } finally {if(version===generation){busy=false;document.getElementById("workshop-refresh").disabled=false;more.disabled=false;}}
  }
  for(const [id,label] of [["all","All"],["working","Working"],["waiting","Waiting"],["done","Finished"],["attention","Needs attention"]]) {
    const button=node("button",label);button.type="button";button.dataset.filter=id;button.setAttribute("aria-pressed",String(id===filter));
    button.addEventListener("click",()=>{filter=id;for(const b of filters.children)b.setAttribute("aria-pressed",String(b===button));drawList();});filters.append(button);
  }
  more.addEventListener("click",()=>refresh(true));document.getElementById("workshop-refresh").addEventListener("click",()=>refresh());
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)void refresh();});
  return {
    stop(){generation++;clearInterval(timer);controller?.abort();graphObserver?.disconnect();},
    async open(route){epoch=route;game=state.gameId;selected=new URLSearchParams(location.search).get("workflow");rows=[];cursor=null;loadedCursors=[];busy=false;host.hidden=false;
      list.replaceChildren();detail.replaceChildren();list.hidden=Boolean(selected);detail.hidden=!selected;filters.hidden=Boolean(selected);document.getElementById("workshop-summary").hidden=Boolean(selected);more.hidden=true;
      health.textContent="Checking the workshop’s reported progress…";await refresh();if(epoch===routeEpoch)timer=setInterval(()=>void refresh(),15000);
    },
  };
})();

start();
