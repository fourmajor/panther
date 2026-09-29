const config = window.PANTHER_CONFIG;

// One loading treatment everywhere. Counts come from responses, never simulated percentages.
const loadingStates = new WeakMap();
function showLoading(host, message) {
  loadingStates.get(host)?.stop();
  const root = document.createElement("span"), spinner = document.createElement("span");
  const copy = document.createElement("span"), label = document.createElement("span"), detail = document.createElement("span");
  root.className = "loading-state"; root.setAttribute("role", "status");
  spinner.className = "loading-spinner"; spinner.setAttribute("aria-hidden", "true");
  label.className = "loading-label"; label.textContent = message;
  detail.className = "loading-detail"; detail.setAttribute("aria-live", "off");
  detail.textContent = "Waiting for Panther…";
  copy.append(label, detail); root.append(spinner, copy); host.replaceChildren(root);
  const started = Date.now();
  const observer = new MutationObserver(() => { if (!host.contains(root) || host.hidden) stop(); });
  const timer = setInterval(() => {
    if (!host.contains(root) || !host.isConnected || host.hidden) { stop(); return; }
    const seconds = Math.floor((Date.now() - started) / 1000);
    detail.textContent = seconds >= 15 ? `Taking longer than usual · ${seconds}s elapsed. You can refresh to retry.` : `${seconds}s elapsed · waiting for a response`;
  }, 1000);
  function stop() { clearInterval(timer); observer.disconnect(); }
  observer.observe(host, {childList:true, attributes:true, attributeFilter:["hidden"]});
  const control = {stop, update(text) { if (host.contains(root)) label.textContent = text; }};
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
  window.history.replaceState({}, "", saved.returnPath || "/media");
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

async function api(path, parameters = {}, options = {}) {
  await ensureSession();
  const url = new URL(path, config.apiUrl);
  for (const [key, value] of Object.entries(parameters)) {
    if (value) url.searchParams.set(key, value);
  }
  let response = await fetch(url, {
    signal: options.signal,
    method: options.body ? "POST" : "GET",
    body: options.body ? JSON.stringify(options.body) : undefined,
    headers: { authorization: `Bearer ${state.tokens.id_token}`, ...(options.body ? {"content-type":"application/json"} : {}) },
  });
  if (response.status === 401) {
    await ensureSession({ force: true });
    response = await fetch(url, { signal: options.signal, method: options.body ? "POST" : "GET",
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

function showWelcome(message = "") {
  document.getElementById("page-loading").hidden = true;
  clearLibrary();
  elements.gameToolbar.hidden = true;
  elements.welcome.hidden = false;
  elements.explorer.hidden = true;
  elements.characters.hidden = true;
  elements.novel.hidden = true;
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
    const button = document.createElement("button");
    button.className = "crumb";
    button.type = "button";
    button.textContent = accumulated === `games/${state.gameId}/` ? state.gameDetail?.game.name || segment : segment;
    button.addEventListener("click", () => loadPrefix(destination));
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
      option.textContent = game.name + (game.purpose === "test" ? " (Test)" : "");
      elements.gameSelector.append(option);
    }
  }
  let remembered = null;
  try { remembered = sessionStorage.getItem("panther.game"); } catch { /* Optional preference. */ }
  const selected = requested || state.gameId || remembered || state.games[0]?.id;
  if (!state.games.some(g => g.id === selected)) throw new Error("Game not found. Choose an available game.");
  elements.gameToolbar.hidden = false;
  if (selected !== state.gameId) {
    resetLive();
    state.gameId = selected;
    state.gameDetail = null;
    state.charactersLoaded = false;
    state.mediaLoaded = false;
    state.currentCharacter = null;
    state.currentPrefix = `games/${selected}/`;
    listingEpoch += 1;
    elements.entries.replaceChildren();
    elements.characterList.replaceChildren();
    elements.characterProfile.hidden = true;
    elements.playerRoster.replaceChildren();
    elements.gameRuleset.textContent = "";
    document.getElementById("game-style").hidden = true;
    elements.characterModel.removeAttribute("src");
    closePreview();
  }
  elements.gameSelector.value = selected;
  elements.gamePurpose.textContent = state.games.find(g => g.id === selected).purpose === "test" ? "Test game · separate from campaign material" : "";
  if (!state.gameDetail) {
    showLoading(document.getElementById("page-loading"), "Fetching the selected game and player roster…");
    const detail = await api("/game", { gameId: selected });
    if (epoch !== routeEpoch || state.gameId !== selected) return false;
    state.gameDetail = detail;
    for (const member of detail.memberships) {
      const person = detail.players.find(p => p.id === member.playerId);
      const names = member.characterIds.map(id => detail.characters.find(c => c.id === id)?.name || id);
      const li = document.createElement("li");
      li.textContent = `${person?.name || member.playerId} — ${member.role === "dungeon-master" ? "Dungeon Master" : names.join(", ") || "Player"}`;
      elements.playerRoster.append(li);
    }
  }
  try { sessionStorage.setItem("panther.game", selected); } catch { /* Optional preference. */ }
  elements.gameRuleset.textContent = state.gameDetail.game.ruleset ? `System: ${state.gameDetail.game.ruleset}` : "System not set";
  renderGameStyle();
  if (liveGame !== selected) { liveGame = selected; void refreshLive(); }
  return true;
}

function renderGameStyle() {
  const panel = document.getElementById("game-style");
  const form = document.getElementById("game-style-form");
  const select = document.getElementById("visual-style");
  const status = document.getElementById("style-status");
  const detail = state.gameDetail;
  panel.hidden = !detail?.visualStyles?.length;
  if (panel.hidden) return;
  const gameId = state.gameId;
  const expectedStyle = detail.game.visualStyle ?? null;
  select.replaceChildren();
  for (const style of detail.visualStyles) {
    const option = document.createElement("option");
    option.value = style.id;
    option.textContent = style.label;
    select.append(option);
  }
  if (!expectedStyle) {
    const unset = new Option("Choose a style", "", true, true);
    unset.disabled = true;
    select.prepend(unset);
  } else select.value = expectedStyle;
  select.disabled = false;
  form.querySelector("button").disabled = false;
  status.textContent = "";
  form.onsubmit = async event => {
    event.preventDefault();
    if (!select.value || select.disabled) return;
    const epoch = routeEpoch;
    select.disabled = true;
    form.querySelector("button").disabled = true;
    status.textContent = "Saving this game’s visual style…";
    try {
      const updated = await api("/game/style", {}, { body: { gameId, visualStyle: select.value, expectedStyle } });
      if (state.gameId !== gameId || routeEpoch !== epoch) return;
      state.gameDetail = updated;
      renderGameStyle();
      status.textContent = "Style saved. Existing assets are unchanged.";
    } catch (error) {
      if (state.gameId !== gameId || routeEpoch !== epoch) return;
      status.textContent = `Could not save style. ${error.message} Refresh before retrying.`;
      select.disabled = false;
      form.querySelector("button").disabled = false;
    }
  };
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
  copy.append(name, title);

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

function configureCharacter(profile) {
  resetModelAnimation();
  const { character, model, poster } = profile;
  state.selectedAppearance = profile;
  state.currentCharacter = { gameId: character.gameId, characterId: character.id };
  elements.characterName.textContent = character.name;
  const facts = state.currentCharacterFacts;
  elements.characterTitle.textContent = facts?.gameId === character.gameId && facts?.characterId === character.id ? facts.details.subtitle || "" : "";
  elements.characterSummary.textContent = "";
  document.querySelector("#character-model-area").hidden = !model;
  document.querySelector("#character-no-model").hidden = Boolean(model);
  const portraitOnly = document.querySelector("#character-portrait-only");
  portraitOnly.hidden = Boolean(model) || !poster;
  portraitOnly.removeAttribute("src");
  document.querySelector("#character-no-model").textContent = poster
    ? "Portrait ready. No 3D model has been published yet."
    : "No portrait or 3D model has been added yet.";
  if (!model && poster) { portraitOnly.src = poster.url; portraitOnly.alt = `Portrait of ${character.name}`; }
  if (!model) {
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
  elements.modelStatus.textContent = keepActive ? "Loading the selected model…" : "Portrait ready. Load the model when you want it.";
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
    state.appearanceVersions = result;
    const states = document.getElementById("appearance-state");
    states.replaceChildren();
    for (const appearance of result.appearances) states.add(new Option(appearance.name, appearance.id));
    const selected = state.selectedAppearance?.selection || result.selections.find(s=>s.id===result.current);
    states.value = selected?.appearanceId || result.appearances[0]?.id || "";
    states.disabled = result.appearances.length < 2 || Boolean(state.pendingAppearanceRestore);
    populateArtworkEditions(selected?.id);
    const events = document.getElementById("appearance-events");
    events.replaceChildren();
    for (const entry of result.activations) {
      const li=document.createElement("li");
      const recorded = Number.isNaN(Date.parse(entry.updatedAt)) ? "Unknown record time" : new Date(entry.updatedAt).toLocaleString();
      li.textContent = `${entry.activationKind==="artwork-selection"?"Artwork edition selected":"Physical appearance selected"} · recorded ${recorded} · ${entry.reason}`;
      events.append(li);
    }
    if (!events.children.length) {const li=document.createElement("li");li.textContent="Earlier imported selections have unknown original selection times.";events.append(li);}
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
      status.textContent=result.selections.length ? `${result.appearances.length} recorded physical states · ${result.selections.length} retained artwork pairs. Viewing never changes the current selection.` : "No official artwork has been selected.";
      renderAppearanceDownloads();
      updateAppearanceStory();
    }
    return true;
  } catch(error) {
    if (epoch===routeEpoch) status.textContent=`Appearance history unavailable: ${error.message}. Refresh to retry.`;
    return false;
  }
}

function populateArtworkEditions(preferred) {
  const data=state.appearanceVersions, menu=document.getElementById("model-version");
  const aid=document.getElementById("appearance-state").value;
  const pairs=(data?.selections||[]).filter(s=>s.appearanceId===aid);
  menu.replaceChildren();
  pairs.forEach((pair,index)=>menu.add(new Option(`${pair.id===data.current?"Current edition":`Retained edition ${index+1}`}${pair.modelKey?" · portrait + model":" · portrait only"}`,pair.id)));
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
    : "Story timing unknown. File and selection record times are not fictional dates.";
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
  const wasActive=elements.characterModel.loaded && !elements.characterModel.hidden;
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
    status.textContent=selected.warnings?.length ? "A pinned asset is unavailable. No other edition has been substituted." : selectionId===state.appearanceVersions?.current ? "Viewing the current official artwork pair." : "Viewing a retained edition. The current official selection is unchanged.";
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
    try { result = await api("/character-details", {gameId, characterId}, {signal:controller.signal}); }
    finally {clearTimeout(timer);}
    if (!current()) return;
    if (!result.character?.details || !result.character.revision) throw new Error("Structured character information is not ready. Refresh to retry.");
    const record = result.character;
    state.currentCharacterFacts = record;
    const render = () => {
      elements.characterTitle.textContent = record.details.subtitle || "";
      host.replaceChildren();
      const heading = document.createElement("div"); heading.className = "explorer-heading";
      const title = document.createElement("h2"); title.textContent = "Character information";
      const edit = document.createElement("button"); edit.type = "button"; edit.className = "quiet-button"; edit.textContent = "Edit character information";
      heading.append(title, edit); host.append(heading);
      const facts = document.createElement("dl"); facts.className = "character-fact-grid";
      const membership = state.gameDetail.memberships.filter(m => m.characterIds?.includes(characterId));
      const players = membership.map(m => state.gameDetail.players.find(p => p.id === m.playerId)?.name).filter(Boolean);
      for (const [label, value] of [["Played by", players.join(", ")], ["Aliases", record.details.aliases.join(", ")],
        ["Pronouns", record.details.pronouns], ["Role", record.details.role], ["Status", record.details.status]]) {
        const row = document.createElement("div"), dt = document.createElement("dt"), dd = document.createElement("dd");
        dt.textContent = label; dd.textContent = value || "Not recorded"; row.append(dt, dd); facts.append(row);
      }
      host.append(facts);
      for (const [field, label] of [["overview","Overview"],["backstory","Backstory"],["notes","Notes"]]) if (record.details[field]) {
        const h = document.createElement("h3"), p = document.createElement("p"); h.textContent = label; p.textContent = record.details[field]; p.className = "character-prose"; host.append(h,p);
      }
      if (record.details.statistics.length) {
        const h = document.createElement("h3"); h.textContent = "Statistics"; host.append(h);
        const list = document.createElement("dl"); list.className = "character-fact-grid";
        for (const stat of record.details.statistics) { const row = document.createElement("div"), name = document.createElement("dt"), value = document.createElement("dd");
          name.textContent = `${stat.group ? `${stat.group} · ` : ""}${stat.name}`; value.textContent = stat.value === null ? "Not recorded" : String(stat.value); row.append(name,value); list.append(row); }
        host.append(list);
      }
      if (record.details.relationships.length) {
        const h = document.createElement("h3"), list = document.createElement("ul"); h.textContent = "Connections";
        for (const ref of record.details.relationships) {
          const li = document.createElement("li"); li.append(document.createTextNode(`${ref.relation} · `));
          const target = ref.entityType === "Character" ? state.gameDetail.characters.find(c => c.id === ref.id) : ref.entityType === "Player" ? state.gameDetail.players.find(p => p.id === ref.id) : null;
          if (target && ref.entityType === "Character") { const a = document.createElement("a"); a.textContent = target.name; a.href = characterPath({...target, gameId}); li.append(a); }
          else if (ref.entityType === "Asset" && sameGameKey(ref.id)) li.append(assetLink({key:ref.id,name:ref.id.split("/").pop()}));
          else li.append(document.createTextNode(target?.name || "Unavailable connection"));
          list.append(li);
        }
        host.append(h,list);
      }
      edit.onclick = () => editor();
    };
    const editor = () => {
      host.replaceChildren();
      const form = document.createElement("form"); form.className = "character-edit-form";
      const h = document.createElement("h2"); h.textContent = "Edit character information"; form.append(h);
      const note = document.createElement("p"); note.textContent = "Leave unknown facts blank. This edits recorded facts, not the official portrait or model. Previous facts are retained."; form.append(note);
      const inputs = {};
      for (const [field,label,max,multi] of [["aliases","Aliases (one per line)",2500,true],["pronouns","Pronouns",80,false],["role","Role",120,false],["status","Status",120,false],["subtitle","Card subtitle",160,false],["overview","Overview",1000,true],["backstory","Backstory",8000,true],["notes","Notes",4000,true]]) {
        const wrapper = document.createElement("label"), input = document.createElement(multi ? "textarea" : "input");
        wrapper.textContent = label; input.maxLength = max; input.value = field === "aliases" ? record.details.aliases.join("\n") : record.details[field] || "";
        input.id = `character-edit-${field}`; wrapper.append(input); form.append(wrapper); inputs[field] = input;
      }
      const stats = document.createElement("fieldset"), legend = document.createElement("legend"); legend.textContent = "Statistics"; stats.append(legend);
      const rows = [];
      const addStat = (stat = {group:null,name:"",value:null}) => {
        const row = document.createElement("div"); row.className = "character-stat-editor";
        const controls = {};
        for (const label of ["Group","Name","Type","Value"]) { const wrap = document.createElement("label"); wrap.textContent = label; const input = document.createElement(label === "Type" ? "select" : "input");
          input.setAttribute("aria-label",label);
          if (label === "Type") for (const kind of ["Unknown","Text","Number","Boolean"]) { const option = document.createElement("option"); option.textContent = kind; input.append(option); }
          else input.maxLength = label === "Group" ? 80 : label === "Name" ? 120 : 500;
          wrap.append(input); row.append(wrap); controls[label] = input;
        }
        controls.Group.value = stat.group || ""; controls.Name.value = stat.name; controls.Value.value = stat.value === null ? "" : String(stat.value);
        controls.Type.value = stat.value === null ? "Unknown" : typeof stat.value === "number" ? "Number" : typeof stat.value === "boolean" ? "Boolean" : "Text";
        const remove = document.createElement("button"); remove.type = "button"; remove.className = "quiet-button"; remove.textContent = "Remove statistic"; remove.onclick = () => {row.remove();};
        row.append(remove); stats.append(row); rows.push({row, ...controls});
      };
      record.details.statistics.forEach(addStat);
      const add = document.createElement("button"); add.type = "button"; add.className = "quiet-button"; add.textContent = "Add statistic"; add.onclick = () => {if (rows.filter(r => r.row.isConnected).length < 100) addStat();}; form.append(stats,add);
      const relationshipsWrap = document.createElement("label"), relationships = document.createElement("textarea");
      relationshipsWrap.textContent = "Connections (structured JSON)";
      relationships.value = JSON.stringify(record.details.relationships,null,2); relationships.maxLength = 12000;
      const connectionHelp = document.createElement("p"); connectionHelp.textContent = 'Each connection uses entityType (Character, Player or Asset), id, and relation. Only existing records in this game are accepted. Use the CLI for larger structured edits.';
      relationshipsWrap.append(relationships); form.append(relationshipsWrap,connectionHelp);
      const coverWrap = document.createElement("label"), cover = document.createElement("select"); coverWrap.textContent = "Character-list thumbnail";
      const none = document.createElement("option"); none.value = ""; none.textContent = "No thumbnail"; cover.append(none);
      if (record.details.thumbnailAssetKey) {const selected = document.createElement("option"); selected.value = record.details.thumbnailAssetKey; selected.textContent = "Current selected thumbnail"; cover.append(selected);}
      cover.value = record.details.thumbnailAssetKey || ""; coverWrap.append(cover); form.append(coverWrap);
      void allAssets(gameId).then(assets=>{if (!current() || !cover.isConnected) return;
        for (const asset of assets) if (asset.contentType?.startsWith("image/") && asset.metadata?.characterIds?.includes(characterId) && ![...cover.options].some(o=>o.value===asset.key)) {
          const option = document.createElement("option"); option.value = asset.key; option.textContent = asset.metadata.title || asset.name; cover.append(option);
        }
      }).catch(()=>{if (cover.isConnected) connectionHelp.textContent += " Thumbnail inventory could not be loaded; existing selection remains available.";});
      const reasonWrap = document.createElement("label"), reason = document.createElement("input"); reasonWrap.textContent = "Reason for change"; reason.required = true; reason.maxLength = 500; reasonWrap.append(reason); form.append(reasonWrap);
      const buttons = document.createElement("div"), save = document.createElement("button"), cancel = document.createElement("button"), status = document.createElement("p");
      buttons.className = "model-control-row"; save.type = "submit"; save.className = "primary-button"; save.textContent = "Save character information";
      cancel.type = "button"; cancel.className = "quiet-button"; cancel.textContent = "Cancel edit"; status.setAttribute("role","status");
      cancel.onclick = render; buttons.append(save,cancel); form.append(buttons,status); host.append(form);
      let pending = null;
      form.onsubmit = async event => {
        event.preventDefault(); save.disabled = true;
        try {
          if (!pending) {
            const details = structuredClone(record.details);
            for (const [field,input] of Object.entries(inputs)) details[field] = field === "aliases" ? input.value.split("\n").map(s=>s.trim()).filter(Boolean) : input.value.trim() || null;
            details.relationships = JSON.parse(relationships.value);
            details.thumbnailAssetKey = cover.value || null;
            details.statistics = rows.filter(r=>r.row.isConnected).map(r => {
              let value = r.Value.value.trim();
              if (r.Type.value === "Unknown") value = null;
              else if (r.Type.value === "Number") { if (!value || !Number.isFinite(Number(value))) throw new Error("Enter a valid numeric statistic."); value = Number(value); }
              else if (r.Type.value === "Boolean") { if (!["true","false"].includes(value)) throw new Error("Boolean statistics must be true or false."); value = value === "true"; }
              return {group:r.Group.value.trim() || null,name:r.Name.value.trim(),value};
            });
            pending = {gameId,characterId,mode:"edit",details,expectedRevision:record.revision,expectedSourceHash:null,
              operationId:crypto.randomUUID().replaceAll("-",""),reason:reason.value.trim(),dryRun:false};
          }
          for (const control of form.querySelectorAll("input,textarea,select,fieldset,button")) control.disabled = true;
          showLoading(status,"Saving the guarded character revision…");
          const controller = new AbortController(), timer = setTimeout(()=>controller.abort(),30000);
          let response;
          try { response = await api("/character-details",{}, {body:pending,signal:controller.signal}); } finally {clearTimeout(timer);}
          if (!current()) return;
          Object.assign(record,response.character); render();
          const message = document.createElement("p"); message.setAttribute("role","status"); message.textContent = "Character information saved. Previous facts retained."; host.append(message);
        } catch (error) {
          if (!current()) return;
          if (!pending || error.status === 400) {
            pending = null;
            for (const c of form.querySelectorAll("input,textarea,select,fieldset,button")) c.disabled = false;
            save.textContent = "Save character information";
            status.textContent = `${error.message}. Correct the fields and try again.`;
            return;
          }
          status.textContent = error.status === 409 ? "Another update changed this character. Cancel and reload before editing again. Your edit was not substituted for that revision." : `${error.message}. Retry submits the exact same operation; cancel and reload before changing it.`;
          save.disabled = error.status === 409;
          save.textContent = "Retry exact save"; cancel.disabled = false;
          cancel.onclick = () => {void loadCharacterFacts(gameId,characterId,epoch);};
        }
      };
      inputs.aliases.focus();
    };
    render();
  } catch (error) {
    if (!current()) return;
    host.textContent = `${error.message}. Structured facts require the character migration; artwork remains separate.`;
    const retry = document.createElement("button"); retry.type = "button"; retry.className = "quiet-button"; retry.textContent = "Retry character information"; retry.onclick = () => {void loadCharacterFacts(gameId,characterId,epoch);}; host.append(retry);
  }
}

async function loadCharacter(gameId, characterId) {
  const epoch = routeEpoch;
  state.currentCharacterFacts = null;
  document.getElementById("characters-more").hidden = true;
  void loadCharacterFacts(gameId, characterId, epoch);
  document.getElementById("character-assets-list").replaceChildren();
  document.getElementById("appearance-history").hidden = true;
  state.appearanceVersions = null;
  state.selectedAppearance = null;
  state.pendingAppearanceRestore = null;
  appearanceRequest++;
  showLoading(document.getElementById("character-assets-status"), "Finding this character’s images, models and media…");
  elements.characterList.hidden = true;
  elements.characterProfile.hidden = true;
  elements.charactersStatus.hidden = false;
  showLoading(elements.charactersStatus, "Fetching character details and portrait…");
  try {
    const params=new URLSearchParams(location.search);
    const profile = await api("/character", { gameId, characterId,
      appearanceId:params.get("appearance"),selectionId:params.get("selection") });
    if (epoch !== routeEpoch) return;
    configureCharacter(profile);
    elements.characterProfile.hidden = false;
    elements.charactersStatus.hidden = true;
    void loadAppearanceVersions(gameId, characterId, epoch);
    void loadCharacterAssets(gameId, characterId, epoch);
  } catch (error) {
    if (epoch !== routeEpoch) return;
    if (error.message !== "Session expired") {
      elements.charactersStatus.textContent = error.message;
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
    matching.sort((a,b) => `${a.kind}:${a.metadata?.category || "Unclassified"}`.localeCompare(`${b.kind}:${b.metadata?.category || "Unclassified"}`) || b.lastModified.localeCompare(a.lastModified));
    for (const asset of matching) {
      const li = document.createElement("li");
      const purpose = asset.metadata?.category || "Unclassified";
      const group = `${asset.kind} · ${purpose}`;
      if (group !== previousGroup) {const header = document.createElement("li"), h = document.createElement("h3"); h.textContent = group; header.append(h); list.append(header); previousGroup = group;}
      li.append(assetLink(asset), document.createTextNode(` · ${asset.kind} · ${purpose}`));
      list.append(li);
    }
    status.textContent = matching.length ? "Assets explicitly tagged with this character, across all media types and versions."
      : "No assets have been tagged with this character yet. Untagged appearances are not inferred.";
  } catch (error) {
    if (current()) status.textContent = `${error.message}. Use Refresh assets to retry.`;
  }
}

async function loadCharacterModel() {
  const epoch = routeEpoch;
  if (!state.currentCharacter) return;
  if (!webGlAvailable()) {
    showModelFallback("This device cannot display WebGL, so the portrait is shown instead.");
    return;
  }
  elements.modelLoad.disabled = true;
  elements.modelLoad.textContent = "Loading…";
  showLoading(elements.modelStatus, "Preparing a secure link to the 3D model…");
  try {
    const pair = state.selectedAppearance?.selection;
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
    if (epoch !== routeEpoch) return;
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
  dismissNarrativePreview(true);
  const epoch = ++routeEpoch;
  const pageLoading = document.getElementById("page-loading");
  pageLoading.hidden = false; showLoading(pageLoading, "Checking your sign-in…");
  clearLibrary();
  closePreview();
  elements.novel.hidden = true;
  clearNovel();
  try { await ensureSession(); } catch (error) { if (epoch === routeEpoch) pageLoading.hidden = true; showWelcome(error.message); return; }
  if (epoch !== routeEpoch) return;
  showApplicationChrome();
  const gameRoute = window.location.pathname.match(/^\/games\/([a-z0-9]+(?:-[a-z0-9]+)*)\/(media|characters|novel|audio|transcripts|videos)(?:\/([a-z0-9]+(?:-[a-z0-9]+)*))?\/?$/);
  const characterMatch = window.location.pathname.match(
    /^\/characters\/([a-z0-9]+(?:-[a-z0-9]+)*)\/([a-z0-9]+(?:-[a-z0-9]+)*)\/?$/,
  );
  try {
    if (!await selectGame(gameRoute?.[1] || characterMatch?.[1], epoch)) return;
  } catch (error) {
    if (epoch !== routeEpoch) return;
    elements.characters.hidden = true;
    elements.explorer.hidden = false;
    elements.entries.replaceChildren();
    elements.status.hidden = false;
    elements.status.textContent = error.message;
    return;
  } finally {
    if (epoch === routeEpoch) pageLoading.hidden = true;
  }
  if (epoch !== routeEpoch) return;
  const section = gameRoute?.[2] || window.location.pathname.slice(1);
  if (["audio", "transcripts", "videos"].includes(section)) {
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
  setActiveNavigation("media");
  elements.characters.hidden = true;
  elements.explorer.hidden = false;
  if (!state.mediaLoaded) {
    state.mediaLoaded = true;
    await loadPrefix(state.currentPrefix);
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

async function loadPrefix(prefix, cursor = null) {
  if (!state.gameId || !prefix.startsWith(`games/${state.gameId}/`)) return;
  const epoch = ++listingEpoch;
  elements.status.hidden = false;
  showLoading(elements.status, cursor ? "Fetching the next files…" : "Fetching folders and files…");
  elements.loadMore.hidden = true;
  if (!cursor) {
    state.currentPrefix = prefix;
    elements.entries.replaceChildren();
    renderBreadcrumbs(prefix);
  }

  try {
    const result = await api("/objects", { prefix, cursor });
    if (epoch !== listingEpoch || !state.tokens) return;
    for (const childPrefix of result.prefixes) appendFolder(childPrefix);
    for (const file of result.objects) appendFile(file);
    state.nextCursor = result.nextCursor;
    elements.loadMore.hidden = !state.nextCursor;
    elements.status.hidden = true;
    if (!elements.entries.children.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "There is nothing in this folder yet.";
      elements.entries.append(empty);
    }
  } catch (error) {
    if (epoch !== listingEpoch) return;
    if (error.message !== "Session expired") {
      elements.status.textContent = error.message;
      elements.status.hidden = false;
    }
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
    renderGeneration(document.getElementById("asset-generation"), result.metadata);
    // Physical folders may change; connections/readers use the API's stable asset identity.
    const assetRef = result.key || file.key;
    download.disabled = false;
    download.onclick = () => downloadAsset(assetRef, download, document.getElementById("asset-download-status"), () => epoch === previewEpoch);
    const structured = assetRef.endsWith(".json") && sameGameKey(assetRef);
    if (structured) showLoading(elements.previewBody, "Reading the document and its metadata…");
    else elements.previewBody.replaceChildren(previewElement(result.contentType, result.url, file.name));
    elements.previewDetails.textContent = `${formatBytes(result.size)} · link valid for ${Math.round(result.expiresIn / 60)} minutes`;
    elements.openOriginal.href = result.url;
    if (/^(audio|video)\//.test(result.contentType)) attachMediaRecovery(elements.previewBody.firstChild, assetRef, () => epoch === previewEpoch);
    if (result.contentType.startsWith("video/")) configureVideoPreview({...result,key:assetRef},elements.previewBody.firstChild,epoch);
    void renderAssetLinks(assetRef, epoch);
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
  previewEpoch += 1;
  for (const media of elements.previewBody.querySelectorAll("audio, video")) { media.pause(); media.pantherCleanup?.(); media.removeAttribute("src"); media.load(); }
  elements.previewDialog.close();
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
  if (!g || g.schemaVersion !== 1) { host.append(heading, "Generation details unavailable."); return; }
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
  "details", "notice", "pagination", "read", "show-details", "download", "back", "refresh", "resume", "progress"]
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

const narrativeClassification = {"grounded-adaptation":"Grounded adaptation", "creative-reimagining":"Creative reimagining", "playful-derivative":"Playful derivative", "unclassified":"Creative classification not assigned"};

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
  const details = document.createElement("p"); details.textContent = [narrativeClassification[book.classification] || "Unclassified",book.authorCredit,
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
  const reviewTitle = document.createElement("h3"); reviewTitle.textContent = "Editorial review and notes";
  const review = document.createElement("div");
  proseMarkdown(review, chapter.details.review.markdown || "No review text recorded.");
  const notes = document.createElement("ul");
  for (const note of chapter.details.review.uncertainties || []) {
    const li = document.createElement("li"); li.textContent = note; notes.append(li);
  }
  const versionsTitle = document.createElement("h3"); versionsTitle.textContent = "Versions of this session";
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
    if (epoch === routeEpoch && state.gameId === gameId && state.tokens) sources.textContent = "Connections unavailable. Refresh chapters to retry.";
  });
  const provenance = document.createElement("details");
  const label = document.createElement("summary"); label.textContent = "Full provenance and revision history";
  const data = document.createElement("pre"); data.textContent = JSON.stringify(chapter.details, null, 2);
  provenance.append(label, data);
  novel.details.replaceChildren(heading, summary, creation, versionsTitle, versionList, reviewTitle, review, notes, sourceTitle, sources, provenance);
}

async function loadNovel(chapterId, epoch) {
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
      const sourceHeading=document.createElement("h2");sourceHeading.textContent="Session chapters · source editions";novel.list.append(sourceHeading);
      novel.status.hidden = Boolean(ordered.length || organization.stories.length);
      novel.status.textContent = "No chapters yet. Completed novel chapters will appear here automatically.";
      for (const [index, chapter] of ordered.entries()) {
        const card = document.createElement("div"); card.className = "novel-card";
        const number = document.createElement("p"); number.className = "eyebrow"; number.textContent = `Chapter ${index + 1} · not an approved book selection`;
        const title = document.createElement("h2"); title.append(novelLink(chapter.title, chapter.id));
        const meta = document.createElement("p"); meta.textContent = `${chapter.sessionId} · ${chapterDate(chapter)}${chapter.publicationStatus === "accepted-with-notes" ? " · Working draft" : ""}`;
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
    novel.notice.textContent = [chapter.notice,
      state.gameDetail.game.purpose === "test" ? "Test-game adaptation · not campaign canon." : "",
      chapter.publicationStatus === "accepted-with-notes" ? "Working draft · AI review left unresolved notes. See Details." : "",
      selectedBook ? `${selectedBook.title} · ${selectedBook.status === "approved" ? "Approved private selection" : "Private draft"} · ${narrativeClassification[selectedBook.classification]}.` : "Source edition · not an approved book selection.",
      sessions.get(chapter.sessionId)?.[0].id !== chapter.id ? "You are reading an earlier version. See Details for the latest." : "",
    ].filter(Boolean).join(" ");
    novel.notice.hidden = !novel.notice.textContent;
    novelView(false);
    novel.reader.hidden = false;
    novel.status.hidden = true;
    readingProgress(chapter,selectedBook,current);
    // Link enrichment is optional: a catalog outage must not prevent reading the manuscript.
    proseMarkdown(novel.prose, chapter.markdown, narrativeReferences(chapter, [], chapters));
    const collectionIds=[...new Set((chapter.readerReferences?.schemaVersion===1 && Array.isArray(chapter.readerReferences.mentions) && chapter.readerReferences.mentions.length<=200 ? chapter.readerReferences.mentions : [])
      .filter(m=>m?.target?.type==="collection" && (!m.target.gameId || m.target.gameId===gameId) && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(m.target.id)).map(m=>m.target.id))];
    const collectionReferences=(async()=>{const records=[];for(let offset=0;offset<collectionIds.length;offset+=8){if(!current())return records;const batch=await Promise.all(collectionIds.slice(offset,offset+8).map(id=>api("/video-collections",{gameId,id,metadataOnly:"true"}).then(r=>r.collection).catch(()=>null)));records.push(...batch.filter(Boolean));}return records;})();
    void Promise.all([allAssets(gameId),collectionReferences]).then(([assets,collections]) => {
      if (current()) proseMarkdown(novel.prose, chapter.markdown, narrativeReferences(chapter, assets, chapters,collections));
    }).catch(() => {
      if (current()) { novel.status.hidden = false; novel.status.textContent = "Some asset links could not be loaded. The story is available; Refresh chapters to retry."; }
    });
    const index = ordered.findIndex(c => selectedBook ? c.id === chapter.id : c.sessionId === chapter.sessionId);
    if (index > 0) novel.pagination.append(novelLink(`← ${ordered[index - 1].title}`, ordered[index - 1].id,selectedBook?.id));
    if (index >= 0 && index < ordered.length - 1) novel.pagination.append(novelLink(`${ordered[index + 1].title} →`, ordered[index + 1].id,selectedBook?.id));
  } catch (error) {
    if (!current()) return;
    novel.status.hidden = false;
    novel.list.replaceChildren();
    novel.status.textContent = `${error.message}. Use Refresh chapters to retry.`;
  }
}

let assetIndex = null;
function sameGameKey(key) {
  return typeof key === "string" && key.startsWith(`games/${state.gameId}/assets/`)
    && !key.split("/").includes("..") && !/[\x00-\x1f]/.test(key);
}

function clearLibrary() {
  currentTVEpisode = null;
  document.getElementById("movie-workspace").replaceChildren();
  document.getElementById("movie-workspace").hidden = true;
  document.getElementById("session-library").hidden = true;
  document.getElementById("library-list").replaceChildren();
  document.getElementById("library-list").hidden = false;
  document.getElementById("library-status").hidden = false;
  if (!state.tokens) {
    assetIndex = null; videoPlaylist = null;
    videoLibraryView = {gameId:null,search:"",category:"all",tag:"",character:"",collection:""};
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

let videoLibraryView = {gameId:null, search:"", category:"all", tag:"", character:"", collection:""};
let videoPlaylist = null;
let currentTVEpisode = null;

function setupTVLibrary(list,status,current,videoHost) {
  const gameId=state.gameId, nav=document.createElement("nav"), host=document.createElement("section");
  nav.className="novel-tabs";nav.setAttribute("aria-label","Video library views");host.className="tv-library";host.setAttribute("aria-label","TV episode library");
  const all=document.createElement("button"), tv=document.createElement("button");
  all.type=tv.type="button";all.className=tv.className="quiet-button";all.textContent="Video library";tv.textContent="TV episodes";
  nav.append(all,tv);list.append(nav,host,videoHost);
  let loaded=false,series=[],episodes=[],sequence=0;
  const alive=()=>current() && host.isConnected;
  const params=()=>new URLSearchParams(location.search);
  const url=(changes)=>{const next=new URL(location.href);for(const [key,value] of Object.entries(changes))if(value)next.searchParams.set(key,value);else next.searchParams.delete(key);history.replaceState(null,"",next);};
  const active=()=>!host.hidden;
  const ordered=(id)=>{const parent=series.find(s=>s.id===id),numbers=new Map(parent?.seasons.map(s=>[s.id,s.number]) || []);
    return episodes.filter(e=>e.seriesId===id).sort((a,b)=>(numbers.get(a.seasonId) || 10001)-(numbers.get(b.seasonId) || 10001)||a.number-b.number||a.id.localeCompare(b.id));};
  const setMode=(value)=>{host.hidden=!value;videoHost.hidden=value;status.hidden=value;all.setAttribute("aria-pressed",String(!value));tv.setAttribute("aria-pressed",String(value));};
  const paged=async(path)=>{const records=[],seen=new Set();let cursor;
    do{const page=await api(path,{gameId,cursor});if(!alive())return null;if(!Array.isArray(page.records))throw new Error("Episode catalog response is incomplete");records.push(...page.records);cursor=page.cursor;
      if(records.length>5000 || seen.size>=200 || (cursor && seen.has(cursor)))throw new Error("Episode catalog exceeds its reader limit or returned a repeated cursor; no partial catalog is shown");if(cursor)seen.add(cursor);
    }while(cursor);return records;};
  const episodeHref=(record,revision=record.revision)=>gamePath("videos")+`?view=episodes&series=${encodeURIComponent(record.seriesId)}&episode=${encodeURIComponent(record.id)}&episodeRevision=${encodeURIComponent(revision)}`;
  function references(parent,label,keys,byKey) {
    if(!keys.length)return;const heading=document.createElement("h3"),links=document.createElement("ul");heading.textContent=label;
    for(const key of keys){const item=document.createElement("li"),asset=byKey.get(key);if(asset)item.append(assetLink(asset));else item.textContent="Pinned reference unavailable";links.append(item);}parent.append(heading,links);
  }
  async function posters() {
    const images=[...host.querySelectorAll('[data-tv-poster]')],keys=[...new Set(images.map(i=>i.dataset.tvPoster))];
    for(let offset=0;offset<keys.length;offset+=60){if(!alive())return;const batch=keys.slice(offset,offset+60);
      try{const result=await api("/image-links",{},{body:{gameId,keys:batch}});if(!alive())return;for(const image of images.filter(i=>batch.includes(i.dataset.tvPoster))){const item=result.images?.[image.dataset.tvPoster];if(item?.url)image.src=item.url;else image.remove();}}
      catch{if(alive())for(const image of images.filter(i=>batch.includes(i.dataset.tvPoster)))image.remove();}}
  }
  function browse() {
    if(!alive())return;currentTVEpisode=null;host.replaceChildren();
    const heading=document.createElement("h2"),notice=document.createElement("p");heading.textContent="TV episodes";notice.textContent="Creative episodic reimaginings · private drafts and approved selections, not canonical session records.";host.append(heading,notice);
    if(!series.length){const empty=document.createElement("p");empty.textContent="No series organized yet. Panther CLI can create a series and explicitly select finished episode cuts.";host.append(empty);return;}
    const label=document.createElement("label"),select=document.createElement("select");label.textContent="Series";select.id="tv-series-select";label.htmlFor=select.id;
    for(const record of series)select.add(new Option(record.title,record.id));
    const selected=params().get("series") || series[0].id;
    if(!series.some(s=>s.id===selected))throw new Error("Selected series unavailable");select.value=selected;
    select.onchange=()=>{url({series:select.value,episode:null,episodeRevision:null});browse();};host.append(label,select);
    const parent=series.find(s=>s.id===selected),synopsis=document.createElement("p");synopsis.textContent=parent.synopsis || "No series synopsis supplied.";host.append(synopsis);
    const entries=ordered(selected);
    if(entries.some(e=>!parent.seasons.some(s=>s.id===e.seasonId)))throw new Error("An episode's season is unavailable; no incomplete series is shown");
    for(const season of parent.seasons){const section=document.createElement("section"),title=document.createElement("h3"),description=document.createElement("p"),cards=document.createElement("div");title.textContent=`Season ${season.number} · ${season.title}`;description.textContent=season.synopsis;cards.className="tv-episode-cards";section.append(title,description,cards);
      for(const episode of entries.filter(e=>e.seasonId===season.id)){const card=document.createElement("article");card.className="novel-card tv-episode-card";
        if(episode.posterAssetKey){const image=document.createElement("img");image.alt=`Episode poster for ${episode.title}`;image.dataset.tvPoster=episode.posterAssetKey;image.className="tv-poster";image.addEventListener("error",()=>image.remove());card.append(image);}
        const meta=document.createElement("p"),h=document.createElement("h4"),link=document.createElement("a"),summary=document.createElement("p"),runtime=document.createElement("p");meta.className="eyebrow";meta.textContent=`Episode ${episode.number} · ${episode.status === "approved" ? "Approved private selection" : "Private draft"}`;
        link.textContent=episode.title;link.href=episodeHref(episode);link.onclick=event=>{if(event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)return;event.preventDefault();void choose(episode.id,episode.revision);};h.append(link);summary.textContent=episode.synopsis || "No episode synopsis supplied.";
        const cut=episode.cuts.find(c=>c.id===episode.selectedCutId);runtime.textContent=cut?.durationSeconds ? `Reported runtime: ${cut.durationSeconds}s · ${episode.cuts.length} cut${episode.cuts.length===1?"":"s"}` : `Runtime not recorded · ${episode.cuts.length} cut${episode.cuts.length===1?"":"s"}`;card.append(meta,h,summary,runtime);cards.append(card);}
      if(!cards.childNodes.length){const empty=document.createElement("p");empty.textContent="No episodes organized in this season yet.";cards.append(empty);}host.append(section);}
    void posters();
  }
  async function choose(id,revision=null,play=false) {
    const generation=++sequence;host.replaceChildren();const loading=document.createElement("p");host.append(loading);const progress=showLoading(loading,"Reading the exact episode and pinned representations…");
    try{const result=await api("/tv-episodes",{gameId,id,revision});if(!alive() || generation!==sequence || !active())return;
      const episode=result.record,byKey=new Map(result.assets.map(a=>[a.key,a])),parent=series.find(s=>s.id===episode.seriesId);
      if(episode.gameId!==gameId || !parent || !parent.seasons.some(s=>s.id===episode.seasonId))throw new Error("Episode parent organization unavailable");
      url({view:"episodes",series:episode.seriesId,episode:episode.id,episodeRevision:episode.revision});host.replaceChildren();
      const back=document.createElement("button");back.type="button";back.className="back-button";back.textContent="← All episodes";back.onclick=()=>{sequence++;url({episode:null,episodeRevision:null});browse();};
      const title=document.createElement("h2"),notice=document.createElement("p"),synopsis=document.createElement("p");title.textContent=episode.title;notice.className="novel-notice";notice.textContent=`${parent.title} · Episode ${episode.number} · ${episode.status==="approved"?"Approved private selection":"Private draft"}. Creative reimagining, not a canonical session record.`;synopsis.textContent=episode.synopsis;host.append(back,title,notice,synopsis);
      if(result.warnings.length){const warning=document.createElement("p");warning.textContent=`${result.warnings.length} pinned assets are unavailable. No newer version was substituted.`;host.append(warning);}
      const label=document.createElement("label"),cuts=document.createElement("select"),button=document.createElement("button"),cutStatus=document.createElement("p");label.textContent="Episode cut";cuts.id="tv-cut-select";label.htmlFor=cuts.id;for(const cut of episode.cuts)cuts.add(new Option(cut.title+(cut.id===episode.selectedCutId?" · selected edition":""),cut.id));cuts.value=episode.selectedCutId;
      button.type="button";button.className="quiet-button";button.textContent="Play selected cut";cutStatus.setAttribute("role","status");
      const selected=()=>episode.cuts.find(c=>c.id===cuts.value);
      const update=()=>{const cut=selected();button.disabled=!byKey.has(cut.assetKey);cutStatus.textContent=button.disabled?"This pinned video is unavailable; no alternative was selected.":cut.durationSeconds?`Reported runtime ${cut.durationSeconds}s. Evidence: ${cut.durationEvidence}`:"Runtime is unknown until measured or played.";};
      const context={gameId,record:episode,assets:byKey,series:parent,episodes:ordered(parent.id),activate:choose};
      button.onclick=()=>{if(alive()){currentTVEpisode=context;videoPlaylist=null;const asset=byKey.get(selected().assetKey);if(asset)void previewFile({...asset,name:episode.title+" · "+selected().title});}};cuts.onchange=update;update();host.append(label,cuts,button,cutStatus);
      const history=document.createElement("p");history.textContent=`Organization revision ${episode.revision.slice(0,8)}. `;if(episode.previousRevision){const previous=document.createElement("a");previous.textContent="Previous episode revision";previous.href=episodeHref(episode,episode.previousRevision);previous.onclick=event=>{if(event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)return;event.preventDefault();void choose(episode.id,episode.previousRevision);};history.append(previous);}host.append(history);
      references(host,"Source references",episode.sourceAssetKeys,byKey);const sessions=[...new Set(episode.sourceAssetKeys.map(k=>byKey.get(k)?.metadata?.sessionId).filter(Boolean))];if(sessions.length){const session=document.createElement("p");session.textContent=`Source sessions recorded in asset metadata: ${sessions.join(", ")}`;host.append(session);}
      references(host,"Related finished media",episode.relatedAssetKeys,byKey);
      if(episode.preparationAssetKeys.length){const preparation=document.createElement("details"),summary=document.createElement("summary");summary.textContent="Production preparation · not finished Inputs/Outputs";preparation.append(summary);references(preparation,"Scripts, storyboards and planning references",episode.preparationAssetKeys,byKey);host.append(preparation);}
      const credits=document.createElement("section"),creditTitle=document.createElement("h3"),creditList=document.createElement("ul");creditTitle.textContent="Credits";for(const credit of episode.credits){const item=document.createElement("li");item.textContent=`${credit.role}: ${credit.name}`;creditList.append(item);}if(!episode.credits.length){const empty=document.createElement("li");empty.textContent="Credits not supplied.";creditList.append(empty);}credits.append(creditTitle,creditList);host.append(credits);
      currentTVEpisode=context;
      if(play && !button.disabled)button.click();
    }catch(error){if(alive() && generation===sequence){currentTVEpisode=null;loading.textContent=`${error.message}. Return to the video library or retry.`;const retry=document.createElement("button");retry.type="button";retry.textContent="Retry episode";retry.className="quiet-button";retry.onclick=()=>void choose(id,revision,play);host.append(retry);}}
  }
  async function load() {
    const loading=document.createElement("p");host.replaceChildren(loading);const progress=showLoading(loading,"Reading series and episode organization…");
    try{if(!loaded){series=await paged("/tv-series");episodes=await paged("/tv-episodes");if(!alive() || !series || !episodes)return;series.sort((a,b)=>a.title.localeCompare(b.title));loaded=true;}
      if(!active())return;if(params().get("episode"))await choose(params().get("episode"),params().get("episodeRevision"));else browse();
    }catch(error){if(alive()){loaded=false;host.replaceChildren(loading);loading.textContent=`${error.message}. The ordinary video library remains usable.`;const retry=document.createElement("button");retry.type="button";retry.className="quiet-button";retry.textContent="Retry TV library";retry.onclick=()=>void load();host.append(retry);}}
  }
  all.onclick=()=>{sequence++;currentTVEpisode=null;setMode(false);url({view:null,series:null,episode:null,episodeRevision:null});};
  tv.onclick=()=>{setMode(true);url({view:"episodes"});void load();};
  const requested=params().get("view")==="episodes" || params().has("series") || params().has("episode");setMode(requested);if(requested)void load();
}

function renderVideoLibrary(assets, list, status, current, loadMore) {
  const gameId = state.gameId;
  const videoHost=document.createElement("div");setupTVLibrary(list,status,current,videoHost);
  if (videoLibraryView.gameId !== gameId) videoLibraryView = {gameId,search:"",category:"all",tag:"",character:"",collection:new URLSearchParams(location.search).get("collection") || ""};
  const view = videoLibraryView;
  view.collection=new URLSearchParams(location.search).get("collection") || "";
  const controls = document.createElement("section"), cards = document.createElement("div"), collectionsStatus = document.createElement("p"), summary = document.createElement("p");
  controls.className = "video-library-controls"; controls.setAttribute("aria-label", "Filter videos");
  cards.className = "video-library-cards"; summary.setAttribute("role", "status"); collectionsStatus.setAttribute("role", "status");
  const field = (text, element, id) => { const label = document.createElement("label"); label.textContent = text; element.id = id; label.htmlFor = id; const wrap = document.createElement("div"); wrap.append(label,element); controls.append(wrap); return element; };
  const search = field("Search loaded videos",document.createElement("input"),"video-search"); search.type = "search"; search.maxLength = 300; search.value = view.search;
  const category = field("Relationship to the game",document.createElement("select"),"video-category");
  for (const [value,label] of [["all","All categories"],["playful-derivative","Playful derivatives"],["creative-reimagining","Creative reimaginings"],["grounded-adaptation","Grounded adaptations"],["canonical-source","Canonical sources"],["reference","References"],["unclassified","Unclassified / unknown"]]) category.add(new Option(label,value));
  category.value = view.category;
  const tag = field("Tag",document.createElement("select"),"video-tag"); tag.add(new Option("All tags",""));
  for (const name of [...new Set(assets.flatMap(a=>a.metadata?.tags || []))].sort()) tag.add(new Option(name,name));
  tag.value = view.tag;
  const character = field("Featuring character",document.createElement("select"),"video-character"); character.add(new Option("All characters",""));
  for (const c of state.gameDetail?.characters || []) character.add(new Option(c.name,c.id));
  character.value = view.character;
  const collection = field("Ordered collection",document.createElement("select"),"video-collection"); collection.add(new Option("Video library","")); collection.disabled = true;
  const retry = document.createElement("button"); retry.type = "button"; retry.className = "quiet-button"; retry.textContent = "Retry preview images"; retry.hidden = true;
  controls.append(collectionsStatus,retry,summary); videoHost.append(controls,cards);
  let displayed = assets, chosen = null, sequence = 0;
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
      && (view.category === "all" || (a.metadata?.category || "unclassified") === view.category)
      && (!view.tag || a.metadata?.tags?.includes(view.tag)) && (!view.character || a.metadata?.characterIds?.includes(view.character)));
    summary.textContent = `${selected.length} of ${displayed.length} ${chosen ? "collection members" : "loaded videos"} match. ${chosen ? "Collection order is preserved; playback never starts automatically." : "Load more to search additional catalog pages."}`;
    status.textContent = chosen ? `${chosen.name} · ${chosen.description || "No description supplied."}` : displayed.length ? "Episodes, experiments and playful derivatives share this private library. Classification is explicit, never inferred from appearance." : "No videos yet for this game.";
    more.hidden = Boolean(chosen) || !loadMore;
    videoPlaylist = chosen ? {gameId,collection:chosen,assets:displayed} : null;
    for (const asset of selected) {
      const card = document.createElement("article"); card.className = "novel-card session-card video-card";
      const poster = document.createElement("div"); poster.className = "video-card-poster"; poster.textContent = "No preview image selected";
      const imageKey = asset.metadata?.extra?.preview?.schemaVersion === 1 ? asset.metadata.extra.preview.imageKey : null;
      if (sameGameKey(imageKey) && /\.(png|jpe?g|webp|avif|gif|svg)$/i.test(imageKey)) {
        poster.textContent = "Loading selected preview…"; poster.dataset.alt = `Preview of ${asset.metadata?.title || asset.name}`;
        if (!posters.has(imageKey)) posters.set(imageKey,[]); posters.get(imageKey).push(poster);
      }
      const title = document.createElement("h2"); title.append(assetLink(asset));
      const description = document.createElement("p"); description.textContent = asset.metadata?.description || "No description supplied.";
      const categoryText = document.createElement("p"); categoryText.className = "video-category-label";
      categoryText.textContent = (asset.metadata?.category || "unclassified").replaceAll("-"," ");
      if (asset.metadata?.category === "playful-derivative") card.classList.add("playful-video");
      const info = document.createElement("p"); info.textContent = `${asset.kind} · ${new Date(asset.lastModified).toLocaleString()} · ${(asset.metadata?.tags || []).join(", ") || "No tags"}`;
      const creator = asset.metadata?.extra?.creator; const credit = document.createElement("p"); credit.textContent = `Creator: ${typeof creator === "string" ? creator : "Not recorded"}`;
      card.append(poster,categoryText,title,description,info,credit);
      const related = document.createElement("p");
      for (const id of asset.metadata?.characterIds || []) { const c = state.gameDetail?.characters.find(c=>c.id===id); if (!c) continue; const link=document.createElement("a"); link.href=gamePath("characters")+`/${encodeURIComponent(id)}`; link.textContent=c.name; related.append(link,document.createTextNode(" · ")); }
      if (asset.metadata?.sessionId) related.append(document.createTextNode(`Session: ${asset.metadata.sessionId}`));
      if (related.childNodes.length) card.append(related);
      cards.append(card);
    }
    void images();
  }
  search.oninput = () => { view.search=search.value; draw(); };
  category.onchange = () => { view.category=category.value; draw(); };
  tag.onchange = () => { view.tag=tag.value; draw(); };
  character.onchange = () => { view.character=character.value; draw(); };
  async function choose() {
    const generation=++sequence; view.collection=collection.value;
    const url=new URL(location.href);if(view.collection)url.searchParams.set("collection",view.collection);else url.searchParams.delete("collection");history.replaceState(null,"",url);
    if (!view.collection) { chosen=null; displayed=assets; collectionsStatus.textContent=""; draw(); return; }
    showLoading(collectionsStatus,"Loading exact collection members…");
    try {
      const result=await api("/video-collections",{gameId,id:view.collection});
      if (!current() || generation !== sequence) return;
      chosen=result.collection; displayed=result.assets;
      collectionsStatus.textContent=result.warnings?.length ? `${result.warnings.length} unavailable members are not substituted. Collection: ${chosen.assetKeys.length} saved members; ${displayed.length} playable catalog entries.` : `${displayed.length} saved members in explicit order.`;
      draw();
    } catch(error) { if(current() && generation===sequence) { chosen=null; displayed=[]; videoPlaylist=null; cards.replaceChildren(); summary.textContent="Collection not loaded; no partial playlist is presented."; collectionsStatus.textContent=`${error.message}. Select the library or refresh to retry.`; } }
  }
  collection.onchange=choose;
  void (async()=>{
    try {
      let cursor=null, seen=new Set(), count=0;
      const nextPage=async()=>{
        showLoading(collectionsStatus,"Fetching saved collections…");
        const result=await api("/video-collections",{gameId,cursor}); if(!current())return;
        for(const item of result.collections) { if([...collection.options].some(o=>o.value===item.id)) continue; collection.add(new Option(`${item.name} (${item.assetKeys.length})`,item.id)); count++; }
        cursor=result.cursor;
        if(cursor && seen.has(cursor)) throw new Error("Repeated collection cursor"); if(cursor)seen.add(cursor);
        collection.disabled=false;
        collectionsStatus.textContent=`${count} loaded collections. Saving collections uses Panther CLI; it does not classify videos or alter source assets.`;
        collectionMore.hidden=!cursor; collectionMore.disabled=false;
      };
      const collectionMore=document.createElement("button"); collectionMore.type="button"; collectionMore.className="quiet-button"; collectionMore.textContent="Load more collections"; collectionMore.hidden=true; controls.append(collectionMore);
      collectionMore.onclick=async()=>{ collectionMore.disabled=true; try{await nextPage();}catch(error){if(current())collectionsStatus.textContent=`Collections unavailable: ${error.message}. Refresh to retry.`;} };
      await nextPage();
      if(view.collection) { if(![...collection.options].some(o=>o.value===view.collection)) collection.add(new Option("Selected collection",view.collection)); collection.value=view.collection; await choose(); }
    } catch(error) { if(current())collectionsStatus.textContent=`Collections unavailable: ${error.message}. The loaded video library remains usable.`; }
  })();
  draw();
}

function configureVideoPreview(asset, video, epoch) {
  const gameId=state.gameId, current=()=>epoch===previewEpoch && gameId===state.gameId && state.tokens;
  const host=document.createElement("section"); host.className="video-player-details"; video.after(host);
  const notice=document.createElement("p"); notice.textContent=`${(asset.metadata?.category || "unclassified").replaceAll("-"," ")} · Classification and provenance remain as recorded. A dramatization or playful derivative is not a canonical session transcript.`; host.append(notice);
  const preview=asset.metadata?.extra?.preview;
  if(preview?.schemaVersion===1 && sameGameKey(preview.imageKey)) void api("/image-links",{},{body:{gameId,keys:[preview.imageKey]}}).then(result=>{if(current() && result.images?.[preview.imageKey]?.url)video.poster=result.images[preview.imageKey].url;}).catch(()=>{});
  const episode=currentTVEpisode?.gameId===gameId && currentTVEpisode.record.cuts.some(c=>c.assetKey===asset.key)?currentTVEpisode:null;
  if(episode){const heading=document.createElement("h3"),label=document.createElement("p"),navigation=document.createElement("nav");heading.textContent=episode.record.title;label.textContent=`${episode.series.title} · Episode ${episode.record.number} · ${episode.record.status==="approved"?"Approved private selection":"Private draft"}. No automatic playback.`;navigation.setAttribute("aria-label","Episode playback");
    const index=episode.episodes.findIndex(e=>e.id===episode.record.id);for(const [name,position] of [["Previous episode",index-1],["Next episode",index+1]]){const button=document.createElement("button");button.type="button";button.className="quiet-button";button.textContent=name;button.disabled=position<0 || position>=episode.episodes.length;button.onclick=()=>{if(current()){closePreview();void episode.activate(episode.episodes[position].id,episode.episodes[position].revision,true);}};navigation.append(button);}host.append(heading,label,navigation);
    if(episode.record.posterAssetKey)void api("/image-links",{},{body:{gameId,keys:[episode.record.posterAssetKey]}}).then(result=>{if(current() && result.images?.[episode.record.posterAssetKey]?.url)video.poster=result.images[episode.record.posterAssetKey].url;}).catch(()=>{});
  }
  const playlist=videoPlaylist?.gameId===gameId ? videoPlaylist : null;
  const index=playlist?.assets.findIndex(a=>a.key===asset.key) ?? -1;
  if(index>=0) {
    const navigation=document.createElement("nav"); navigation.setAttribute("aria-label","Ordered collection playback");
    const label=document.createElement("p"); label.textContent=`${playlist.collection.name} · ${index+1} of ${playlist.assets.length} available videos. Order is explicit; no automatic playback.`;
    const button=(name,position)=>{const node=document.createElement("button");node.type="button";node.className="quiet-button";node.textContent=name;node.disabled=position<0 || position>=playlist.assets.length;node.onclick=()=>{if(current()){const entry=playlist.assets[position];void previewFile({...entry,name:entry.metadata?.title || entry.name});}};return node;};
    navigation.append(label,button("Previous collection video",index-1),button("Next collection video",index+1));host.append(navigation);
  }
  const captions=document.createElement("details"), heading=document.createElement("summary"), captionStatus=document.createElement("p");
  heading.textContent="Caption tracks"; captionStatus.setAttribute("role","status");captionStatus.textContent="Finding explicitly associated WebVTT exports…";
  captions.append(heading,captionStatus);host.append(captions);
  let blobUrl=null;
  video.pantherCleanup=()=>{video.pantherCaptionController?.abort();if(blobUrl)URL.revokeObjectURL(blobUrl);blobUrl=null;};
  void(async()=>{
    try {
      const assets=episode ? [...episode.assets.values()] : await allAssets(gameId);if(!current())return;
      const directory=asset.key.slice(0,asset.key.lastIndexOf("/")+1);
      const tracks=assets.filter(a=>a.kind==="video-captions" && a.key.endsWith(".vtt") && sameGameKey(a.key)
        && (a.key.slice(0,a.key.lastIndexOf("/")+1)===directory || asset.sourceKeys?.includes(a.key) || a.sourceKeys?.includes(asset.key)
          || (episode?.record.cuts.find(c=>c.id===episode.record.selectedCutId)?.assetKey===asset.key && episode.record.captionAssetKeys.includes(a.key))));
      if(!tracks.length){captionStatus.textContent=episode?"No caption export is registered for this episode cut. Other exports may be available on its asset page; burned-in subtitles remain in the original.":"No separate caption track is associated. Any burned-in subtitles remain part of the original video.";return;}
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
      captionStatus.textContent=`${tracks.length} explicitly associated caption exports. No language, author or review status is guessed.`;
    }catch(error){if(current())captionStatus.textContent=`Caption lookup unavailable: ${error.message}. Video playback remains usable.`;}
  })();
}

async function loadLibrary(section, epoch, previousAssets = [], cursor = null) {
  const gameId = state.gameId, current = () => epoch === routeEpoch && gameId === state.gameId && state.tokens;
  const status = document.getElementById("library-status"), list = document.getElementById("library-list");
  document.getElementById("session-library").hidden = false;
  document.getElementById("live-transcript").hidden = !["transcripts", "audio"].includes(section);
  if (["transcripts", "audio"].includes(section)) {
    drawLive();
    for (const record of liveRecords) if (!liveHistory.has(historyKey(record))) void loadLiveHistory(record);
  }
  document.getElementById("library-title").textContent = {audio:"Audio", transcripts:"Transcripts", videos:"Videos"}[section];
  status.hidden = false;
  const loading = showLoading(status, `Fetching ${section} from the catalog…`);
  try {
    // A bounded page of the selected section, never an automatic whole-game scan.
    const page = await api("/assets", {gameId, section, cursor});
    if (!Array.isArray(page.assets)) throw new Error("Asset catalog unavailable");
    const assets = [...new Map([...previousAssets, ...page.assets].map(a => [a.key, a])).values()];
    if (!current()) return;
    list.replaceChildren();
    loading.update("Organizing recordings, transcripts and videos…");
    if (section === "videos") await loadMovies(assets, epoch);
    if (!current()) return;
    status.hidden = section === "videos" && new URLSearchParams(location.search).has("project");
    list.hidden = status.hidden;
    if (status.hidden) return;
    const manifests = new Set(assets.filter(a => a.recording?.partCount > 0).map(a => a.key.split("/")[3]));
    const keys = new Set(assets.map(a => a.key));
    const selected = assets.filter(a => section === "audio"
      ? a.recording?.partCount > 0 || ((a.contentType.startsWith("audio/") || /\.(flac|wav|mp3|m4a|ogg)$/i.test(a.name)) && !manifests.has(a.key.split("/")[3]))
      : section === "videos" ? a.contentType.startsWith("video/") || /\.(mp4|webm|mov|m4v|ogv)$/i.test(a.name)
      : ["transcript", "raw-transcript", "corrected-transcript", "edited-transcript"].includes(a.kind)
        && !(a.key.endsWith(".md") && keys.has(a.key.slice(0,-3) + ".json")));
    selected.sort((a,b) => (b.metadata?.sessionId || "").localeCompare(a.metadata?.sessionId || "") || b.lastModified.localeCompare(a.lastModified) || a.name.localeCompare(b.name));
    if (section === "videos") {
      renderVideoLibrary(selected,list,status,current,page.cursor ? () => { void loadLibrary(section,epoch,assets,page.cursor); } : null);
      return;
    }
    status.textContent = selected.length
      ? section === "videos" ? "Episodes, experiments and other videos. Open a video to play it and explore its inputs and outputs."
        : section === "audio" ? "Continuous session playback. Lossless original parts are retained separately." : "All saved versions. Raw recognition is preserved; corrected transcripts are separate and may still contain uncertainty."
      : `No ${section === "audio" ? "recordings" : section} yet for this game.`;
    const sessionGroups = new Map();
    for (const asset of selected) {
      const card = document.createElement("article"); card.className = "novel-card session-card";
      const heading = document.createElement("h2");
      const label = section === "audio" && asset.kind === "recording-manifest" ? `Recording · ${asset.metadata?.sessionId || asset.name}` : asset.metadata?.title || asset.name;
      heading.append(assetLink(asset, label));
      const kind = document.createElement("p");
      kind.textContent = `${asset.metadata?.sessionId || "Session not recorded"} · ${asset.kind === "raw-transcript" ? "Raw transcript" : ["corrected-transcript", "edited-transcript"].includes(asset.kind) ? "Corrected / edited transcript" : asset.kind} · ${section === "videos" ? "Video" : asset.name.endsWith(".json") ? "Structured reader" : asset.name.endsWith(".md") ? "Markdown export" : "Original audio"}`;
      const date = document.createElement("p"); date.textContent = new Date(asset.lastModified).toLocaleString();
      card.append(heading, kind, date);
      if (section === "transcripts") {
        const sessionId = asset.metadata?.sessionId || "";
        if (!sessionGroups.has(sessionId)) {
          const group = document.createElement("section"), title = document.createElement("h2"), note = document.createElement("p");
          group.className = "transcript-session";
          title.textContent = sessionId ? `Session · ${sessionId}` : "Session not identified";
          note.textContent = "Loaded transcript versions. Canonical selection is separate from review or human verification; dates below are asset timestamps, not inferred session dates.";
          group.append(title, note); list.append(group); sessionGroups.set(sessionId, group);
        }
        const summary = document.createElement("p"), version = asset.metadata?.extra?.version;
        const observed = asset.transcript;
        summary.textContent = observed?.state === "available"
          ? `Observed speakers: ${observed.participants.map(p => p.name || p.id).join(", ") || "None assigned"} · ${observed.unassignedSegments} unassigned segments · Review: ${observed.reviewStatus}`
          : "Speaker summary unavailable; open the preserved transcript to inspect its evidence.";
        const revision = document.createElement("p"); revision.textContent = version ? `Asset version ${version.number} · ${version.seriesId}` : "Version metadata unavailable — inventory verification required.";
        card.append(summary, revision); sessionGroups.get(sessionId).append(card);
      } else list.append(card);
    }
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
    if (current()) status.textContent = `${error.message}. Use Refresh to retry.`;
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
    const heading = document.createElement("h3"); heading.textContent = title;
    const list = document.createElement("ul"); list.dataset.connections = title.toLowerCase();
    for (const record of records) {
      const li = document.createElement("li"), jobId = record.metadata?.extra?.jobId;
      li.append(record.kind === "novel-chapter" && /^[a-f0-9]{64}$/.test(jobId || "")
        ? novelLink(record.connectionLabel, jobId) : assetLink(record, record.connectionLabel));
      list.append(li);
    }
    if (!records.length) { const li = document.createElement("li"); li.textContent = `No finished ${title.toLowerCase()} recorded.`; list.append(li); }
    host.append(heading, list);
  }
}

async function renderAssetLinks(key, epoch) {
  const host = document.getElementById("asset-links"), gameId = state.gameId;
  const current = () => epoch === previewEpoch && gameId === state.gameId && state.tokens;
  if (!sameGameKey(key)) { host.textContent = "Connections are available for game assets."; return; }
  try {
    const assets = await allAssets(gameId);
    if (!current()) return;
    const item = assets.find(a => a.key === key);
    if (!item) { host.textContent = "This asset is not in the current catalog. Refresh to retry."; return; }
    host.replaceChildren();
    const connections = finishedAssetConnections(assets, key, gameId);
    appendFinishedConnections(host, connections);
    const companions = assets.filter(a => a.key !== key && a.key.split("/")[3] === key.split("/")[3]);
    if (companions.length) {
      const details = document.createElement("details"), summary = document.createElement("summary"), list = document.createElement("ul");
      summary.textContent = "Technical files and original exports";
      for (const asset of companions) { const li = document.createElement("li"); li.append(assetLink(asset)); list.append(li); }
      details.append(summary, list); host.append(details);
    }
    const warnings = assets.filter(a => a.lineageWarning).length;
    if (warnings || connections.incomplete) { const warning = document.createElement("p"); warning.textContent = "Some provenance is missing or unreadable; finished-asset connections may be incomplete."; host.append(warning); }
    const note = document.createElement("p"); note.className = "status";
    note.textContent = "Finished assets only. Processing steps are omitted; full provenance is retained. Connections do not establish factual accuracy."; host.append(note);
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
    if (!version || version.schemaVersion !== 1) { host.textContent = "Version record unavailable; the asset migration is not complete."; return; }
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

function detailBlock(title, value) {
  const details = document.createElement("details"), summary = document.createElement("summary"), pre = document.createElement("pre");
  summary.textContent = title; pre.textContent = JSON.stringify(value, null, 2); details.append(summary, pre); return details;
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
  if (!key) {
    // Do not push existing playable videos below the fold with an empty planning feature.
    if (!plans.length) { host.hidden = true; return; }
    const intro = movieNode("div", undefined, "movie-intro");
    const text = movieNode("div"); text.append(movieNode("p", "THE CUTTING ROOM", "eyebrow"),
      movieNode("h2", "A good film starts before the first frame."),
      movieNode("p", "Review the story, cast and shot-by-shot budget. Nothing generates until you approve.", "movie-muted"));
    intro.append(text, movieNode("span", "Planning costs ≠ generation spend", "movie-tag")); host.append(intro);
    const grid = movieNode("div", undefined, "movie-projects");
    for (const asset of plans.sort((a,b) => b.lastModified.localeCompare(a.lastModified))) {
      const card = movieNode("article", undefined, "movie-project-card");
      card.append(movieNode("p", "MOVIE PLAN · REVIEW BEFORE GENERATION", "eyebrow"),
        movieNode("h3", asset.metadata?.title || asset.name),
        movieNode("p", asset.metadata?.description || "Open the screenplay, planned shots and budget.", "movie-muted"));
      const link = movieNode("a", "Open review workspace →", "movie-open");
      link.href = `${gamePath("videos")}?project=${encodeURIComponent(asset.key)}`;
      link.onclick = event => { if (!event.metaKey && !event.ctrlKey) { event.preventDefault(); navigate(link.href); } };
      card.append(link); grid.append(card);
    }
    if (!plans.length) grid.append(movieNode("p", "No movie plans yet. A prepared plan will appear here before any paid generation.", "movie-empty"));
    host.append(grid, movieNode("h2", "Video library", "movie-library-heading")); return;
  }
  showLoading(host, "Reading the screenplay, shots and budget review…");
  try {
    if (!sameGameKey(key)) throw new Error("This movie plan does not belong to the selected game");
    const data = await api("/movie-review", {gameId, key});
    if (!current()) return;
    if (data.plan?.gameId !== gameId || data.plan?.entityType !== "MovieReviewPlan") throw new Error("Invalid movie plan");
    drawMovieWorkspace(host, data, key, assets, current);
  } catch (error) {
    if (!current()) return;
    host.replaceChildren(movieNode("p", `${error.message}. Use Refresh to retry.`, "error"),
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
    aside.replaceChildren(movieNode("p", "PRODUCTION CHECKPOINT", "eyebrow"), movieNode("h3", "Review before you spend"));
    const cost = movieNode("div", undefined, "movie-cost");
    cost.append(movieNode("strong", data.readiness.costComplete ? movieMoney(data.readiness.knownCostUsd) : "Unquoted"),
      movieNode("span", "estimated generation cost", "movie-muted")); aside.append(cost);
    aside.append(movieNode("p", `${movieMoney(plan.budget.capUsd)} total budget ceiling · USD`, "movie-cap"));
    const budgetBar = movieNode("div", undefined, "movie-budget-bar");
    const fill = movieNode("span"); fill.style.width = `${Math.min(100, Number(data.readiness.knownCostUsd) / Number(plan.budget.capUsd) * 100)}%`; budgetBar.append(fill); aside.append(budgetBar);
    aside.append(movieNode("p", plan.budget.notes || "Includes retries. Quotes must be refreshed before approval. Unknown costs are not zero.", "movie-small"));
    const count = movieNode("p", `${reviewed.size} of ${plan.shots.length} shots reviewed`, "movie-reviewed-count"); aside.append(count);
    if (data.readiness.blockers.length) {
      const details = movieNode("details", undefined, "movie-blockers"); details.open = true;
      details.append(movieNode("summary", `${data.readiness.blockers.length} items need attention`));
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
  const activity = document.createElement("p"); audio.after(activity);
  const waiting = () => { if (current()) { activity.hidden = false; showLoading(activity, "Buffering audio/video for playback…"); } };
  const ready = () => { activity.hidden = true; activity.replaceChildren(); };
  audio.addEventListener("loadstart", waiting); audio.addEventListener("waiting", waiting);
  for (const event of ["loadedmetadata", "canplay", "playing", "ended", "error"]) audio.addEventListener(event, ready);
  const warning = document.createElement("p"), retry = document.createElement("button");
  warning.hidden = true; warning.className = "error";
  retry.type = "button"; retry.className = "quiet-button"; retry.textContent = "Refresh playback link";
  warning.append("Playback failed or the link expired. Refresh the link, or download the original if this browser cannot decode it. ", retry);
  audio.after(warning);
  audio.addEventListener("error", () => { if (current()) warning.hidden = false; });
  retry.addEventListener("click", async () => {
    const time = audio.currentTime;
    try {
      const result = await api("/object-url", {key});
      if (!current()) return;
      audio.src = result.url;
      audio.addEventListener("loadedmetadata", () => { if (current()) audio.currentTime = time; }, {once:true});
      warning.hidden = true;
    } catch { if (current()) warning.hidden = false; }
  });
}

function renderStructuredAsset(asset, epoch) {
  const doc = asset.document;
  if (!doc) { elements.previewBody.textContent = "Structured preview unavailable. Use Open original; the source is unchanged."; return; }
  const host = document.createElement("div"); host.className = "structured-asset";
  const transcript = doc.entityType === "PlayerTranscript" ? doc : ["corrected-transcript", "edited-transcript"].includes(doc.stage) ? doc.payload?.transcript : null;
  if (transcript && Array.isArray(transcript.segments)) {
    const notice = document.createElement("p"); notice.className = "novel-notice";
    const edited = [asset.kind, doc.stage, doc.artifactType].some(kind => ["corrected-transcript", "edited-transcript"].includes(kind));
    notice.textContent = `${edited ? "Corrected / edited transcript" : "Raw transcript"} · ${doc.reviewStatus || "unreviewed"}. Speakers identify players, not characters.`;
    if (doc.publicationStatus === "accepted-with-notes") notice.textContent += " Working draft with unresolved review notes.";
    if (!transcript.captureIntegrity) notice.textContent += " Capture integrity was not recorded in this version.";
    host.append(notice);
    if (transcript.captureIntegrity) host.append(detailBlock("Capture integrity and warnings", transcript.captureIntegrity));
    const people = new Map((transcript.players || []).map(p => [p.id, p.name]));
    const navigation = transcriptNavigation(host, asset, transcript, epoch, people);
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
  } else if (doc.entityType === "Recording" && Array.isArray(doc.parts)) {
    const notice = document.createElement("p"); notice.textContent = `Recording status: ${doc.status || "unknown"} · ${doc.parts.length} lossless original parts retained. One continuous listening copy; assembly does not repair capture gaps.`;
    const audio = document.createElement("audio"); audio.controls = true; audio.preload = "metadata";
    const status = document.createElement("p"); status.setAttribute("role", "status"); showLoading(status, "Finding the continuous audio playback file…");
    const parts = document.createElement("div"); parts.className = "recording-parts";
    host.append(notice, audio, status, parts);
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
          status.textContent = "Continuous playback has not been prepared yet. It is produced after the uploaded chunk set is marked complete and the laptop workflow runs. Lossless originals remain under Technical files and original exports.";
          return;
        }
        const copy = copies[0].playback;
        const result = await api("/object-url", {key:copy.audioKey});
        if (!current()) return;
        audio.src = result.url;
        attachMediaRecovery(audio, copy.audioKey, current);
        status.textContent = `Continuous playback · ${timestamp(copy.durationSeconds)} · MP3 listening copy. No file switches at part boundaries.`;
        doc.parts.forEach((part,index) => {
          if (!Number.isFinite(part.start) || part.start < 0 || part.start >= copy.durationSeconds) return;
          const button = document.createElement("button"); button.type = "button"; button.className = "quiet-button";
          button.textContent = `Jump to part ${index+1} · ${timestamp(part.start)}`;
          button.disabled = audio.readyState < 1;
          audio.addEventListener("loadedmetadata", () => { if (current()) button.disabled = false; });
          button.addEventListener("click", () => { if (current()) audio.currentTime = part.start; });
          parts.append(button);
        });
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
  const label = document.createElement("label"), search = document.createElement("input"), results = document.createElement("p"), previous = document.createElement("button"), next = document.createElement("button");
  label.textContent = "Search speech or player names"; search.type = "search"; search.maxLength = 500; search.id = "transcript-search"; label.htmlFor = search.id;
  search.placeholder = "Find a name, place or phrase…"; results.setAttribute("role", "status");
  previous.type = next.type = "button"; previous.className = next.className = "quiet-button";
  previous.textContent = "Previous match"; next.textContent = "Next match";
  tools.append(label, search, previous, next, results); host.append(tools);
  const versionLabel = document.createElement("label"), versions = document.createElement("select");
  versions.id = "transcript-version"; versions.disabled = true; versionLabel.htmlFor = versions.id; versionLabel.textContent = "Session transcript version";
  versions.add(new Option("Finding saved versions…", asset.key)); tools.append(versionLabel, versions);
  const selection = document.createElement("div"), selectionStatus = document.createElement("p");
  selectionStatus.setAttribute("role", "status"); selectionStatus.textContent = sessionId ? "Checking the explicit canonical selection…" : "Canonical selection unavailable: this transcript has no session identity.";
  selection.append(selectionStatus); tools.append(selection);
  const source = document.createElement("details"), sourceHeading = document.createElement("summary"), sourceStatus = document.createElement("p"), audio = document.createElement("audio");
  sourceHeading.textContent = "Source recording · listen at a transcript timestamp";
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
    results.textContent = query ? `${matches.length} matching ${matches.length === 1 ? "line" : "lines"}. All source lines remain visible.` : `${lines.length} transcript lines. Search does not hide or edit evidence.`;
  };
  const move = direction => {
    if (!matches.length) return;
    lines.forEach(entry => entry.line.classList.remove("transcript-current-match"));
    position = position < 0 ? (direction > 0 ? 0 : matches.length - 1) : (position + direction + matches.length) % matches.length;
    const line = lines[matches[position]].line;
    line.classList.add("transcript-current-match"); line.tabIndex = -1;
    line.scrollIntoView({block:"center", behavior:"instant"}); line.focus({preventScroll:true});
    results.textContent = `Match ${position+1} of ${matches.length}. All source lines remain visible.`;
  };
  search.addEventListener("input", update);
  search.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); move(event.shiftKey ? -1 : 1); } });
  previous.onclick = () => move(-1); next.onclick = () => move(1);
  versions.onchange = () => { const chosen = versions.value; if (sameGameKey(chosen)) void previewFile({key:chosen,name:versions.selectedOptions[0].textContent}); };
  const seeks = [];
  let duration = null;
  const seek = async seconds => {
    if (!current() || duration === null || !Number.isFinite(seconds) || seconds < 0 || seconds >= duration) return;
    source.open = true;
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
      sourceStatus.textContent = "Continuous listening copy of the linked source. Timestamps follow the transcript; capture warnings and attribution uncertainty still apply.";
    } catch (error) { if (current()) { versions.replaceChildren(new Option("Version navigation unavailable",asset.key)); sourceStatus.textContent = `Source navigation unavailable: ${error.message}. Use Inputs or reopen to retry.`; } }
  };
  void configure();
  if (sessionId && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(sessionId)) void (async () => {
    try {
      let chosen = await api("/transcript-selection", {gameId,sessionId});
      if (!current()) return;
      const report = () => {
        selectionStatus.textContent = chosen.warning || (chosen.selection
          ? `${chosen.selection.key === asset.key ? "Viewing the canonical reading version" : "Viewing a non-canonical version"}. Canonical selection is not human verification; review/uncertainty remain as reported above.`
          : "No canonical reading version has been designated for this session. This is an archived transcript, not an approved record.");
        selection.querySelector('[data-canonical-link]')?.remove();
        if (chosen.selection?.key && chosen.selection.key !== asset.key && sameGameKey(chosen.selection.key)) {
          const link = assetLink({key:chosen.selection.key}, "Open canonical reading version"); link.dataset.canonicalLink = "true"; selection.append(link);
        }
      };
      report();
      const details = document.createElement("details"), heading = document.createElement("summary"), explanation = document.createElement("p"), reasonLabel = document.createElement("label"), reason = document.createElement("input"), confirmLabel = document.createElement("label"), confirm = document.createElement("input"), button = document.createElement("button"), status = document.createElement("p");
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
      details.append(heading, explanation, reasonLabel, reason, confirmLabel, button, status); selection.append(details);
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
document.getElementById("character-assets-refresh").addEventListener("click", () => { assetIndex = null; void renderRoute(); });
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
elements.characterBack.addEventListener("click", () => navigate(gamePath("characters")));
elements.gameSelector.addEventListener("change", () => {
  const section = elements.primaryNav.querySelector("[aria-current]")?.dataset.section || "media";
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
  if (!link) return;
  event.preventDefault();
  navigate(link.getAttribute("href"));
});
document.querySelector(".brand").addEventListener("click", (event) => {
  if (!state.tokens) return;
  event.preventDefault();
  navigate(gamePath("media"));
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
  const active = liveRecords.find(r => liveState(r) === "recording");
  const current = active || liveRecords[0];
  const mode = current ? liveState(current) : liveFailure ? "lost" : "none";
  const labels = {recording:"Recording in progress", stalled:"Recording progress stalled", stopped:"Recording stopped", lost:"Recording signal lost"};
  badge.hidden = mode === "none"; badge.dataset.state = mode; badge.href = gamePath("transcripts");
  document.getElementById("recording-label").textContent = labels[mode] || "";
  status.textContent = liveFailure ? "Live feed unavailable. Recording may still be running locally. Retrying automatically."
    : liveRecords.length ? "Updates automatically as completed audio chunks are transcribed."
    : "No live recording reported for this game. Start the live worker from the recording laptop.";
  const projected = liveRecords.map(r => ({recordingId:r.recordingId, previewId:r.previewId, sessionId:r.sessionId, mode:liveState(r), previewState:r.previewState, segments:r.segments, omittedChunks:r.omittedChunks, history:liveHistory.get(historyKey(r))}));
  const key = JSON.stringify(projected);
  if (key === liveRenderKey) return;
  liveRenderKey = key;
  const host = document.getElementById("live-recordings"), positions = new Map();
  const focusAction = host.contains(document.activeElement) ? document.activeElement.dataset.historyAction : null;
  for (const el of host.querySelectorAll(".live-lines")) positions.set(el.dataset.recording, {top:el.scrollTop, bottom:el.scrollHeight-el.scrollTop-el.clientHeight<30});
  host.replaceChildren();
  for (const record of projected) {
    const article = document.createElement("article"), heading = document.createElement("h3"), note = document.createElement("p"), lines = document.createElement("div");
    heading.textContent = record.sessionId;
    note.textContent = `${labels[record.mode] || "Recording status unknown"} · ${record.previewState.replaceAll("-", " ")}.${record.omittedChunks ? " Joined after recording began." : ""}`;
    const view = record.history, controls = document.createElement("div"), historyNote = document.createElement("p");
    controls.className = "live-history-controls"; controls.setAttribute("role","group"); controls.setAttribute("aria-label","Transcript history navigation");
    const chunks = view?.chunks || [], first = chunks[0]?.partIndex, last = chunks.at(-1)?.partIndex;
    for (const [label,position,cursor,disabled] of [
      ["Beginning","beginning",undefined,false], ["Earlier","before",first,first===undefined || first===0],
      ["Later","after",last,last===undefined], ["Live","live",undefined,false],
    ]) {
      const button = document.createElement("button"); button.type = "button"; button.textContent = label;
      button.dataset.historyAction = `${record.recordingId}:${label}`; button.disabled = disabled;
      button.addEventListener("click",()=>loadLiveHistory(record,position,cursor)); controls.append(button);
    }
    historyNote.className = "live-history-status";
    historyNote.textContent = view?.error || (view?.loading ? "Loading transcript history…"
      : view?.loaded && !chunks.length ? "History is being uploaded from the recording laptop."
      : view?.position === "beginning" && first>0 ? "The beginning is still being transcribed. Retry Beginning shortly."
      : view?.mode === "history" ? "Browsing earlier speech. Choose Live to follow new speech."
      : "Following new speech. Use Beginning or Earlier to browse the full session.");
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
document.getElementById("live-refresh").addEventListener("click", refreshLive);
document.getElementById("recording-badge").addEventListener("click", event => {
  if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault(); navigate(gamePath("transcripts"));
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
    await ensureSession();
    await renderRoute();
  } catch (error) {
    document.getElementById("page-loading").hidden = true;
    // Offline/5xx failures must not discard a valid remembered session or route.
    showWelcome(error.message);
  }
}

// Account operations use the first-party HttpOnly session. Credentials never go
// into storage, URLs, generic asset APIs, or browser logs.
let accountSettingsEpoch = 0;
function closeAccountSettings() {
  accountSettingsEpoch += 1;
  const dialog = document.getElementById("account-settings-dialog");
  if (dialog.open) dialog.close();
  document.getElementById("account-settings-body").replaceChildren();
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
  heading.textContent=title; copy.textContent=description; section.append(heading,copy); host.append(section); return section;
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
  const dialog=document.getElementById("account-settings-dialog"), host=document.getElementById("account-settings-body");
  document.getElementById("account-settings-title").textContent=recovery?"Password recovery":"Account settings";
  dialog.showModal();
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
      return "Password reset. Close this window and sign in with your new password.";
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
  const identity=accountSection(host,"Profile",`Signed in as ${profile.username}. Your login username stays unchanged.`);
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
    if(epoch===accountSettingsEpoch) emailSection.querySelector("p").textContent="Email verification completed. Reopen account settings to see the active address.";
    return "Email verified. Reopen account settings to see the active address.";
  });
  emailCode=accountField(verifyForm,"Email verification code"); emailCode.required=true; emailCode.autocomplete="one-time-code";
  accountForm(emailSection,"Resend email code",async()=>{await accountRequest("resend-email");return "Verification requested. Check the pending or current address.";});

  const passwordSection=accountSection(host,"Password","Use at least 16 characters, with upper/lowercase letters, a number and a symbol. Cognito stores and verifies your password.");
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
      const help=document.createElement("p"); help.textContent="Add this key manually to your authenticator as a time-based (TOTP) account. This secret is only displayed here and is removed when you close this window."; enrollment.append(help);
      let code;
      const confirmMfa=accountForm(enrollment,"Enable authenticator",async()=>{
        const result=await accountRequest("mfa-confirm",{code:code.value.trim()});
        if(result.verified===false)throw new Error("Authenticator code was not verified. Try a fresh code.");
        if(epoch!==accountSettingsEpoch)return;
        setupForm.hidden=true;
        mfaSection.querySelector("p").textContent="Authenticator MFA is enabled. Keep a secure authenticator backup. Email password recovery does not remove MFA; losing the authenticator requires administrator help.";
        const done=document.createElement("p"); done.textContent="Authenticator enabled. Reopen account settings to see the current status.";
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
      if(epoch===accountSettingsEpoch) mfaSection.querySelector("p").textContent="Authenticator MFA is disabled. Reopen settings to enroll again.";
      return "Authenticator disabled. Reopen account settings for the current status.";
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
}
document.getElementById("account-settings-button").addEventListener("click",()=>openAccountSettings());
document.getElementById("password-recovery-button").addEventListener("click",()=>openAccountSettings(true));
document.getElementById("account-settings-close").addEventListener("click",closeAccountSettings);
document.getElementById("account-settings-dialog").addEventListener("cancel",event=>{event.preventDefault();closeAccountSettings();});

start();
