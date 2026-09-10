const config = window.PANTHER_CONFIG;

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
    scope: "openid profile",
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

async function api(path, parameters = {}) {
  await ensureSession();
  const url = new URL(path, config.apiUrl);
  for (const [key, value] of Object.entries(parameters)) {
    if (value) url.searchParams.set(key, value);
  }
  let response = await fetch(url, {
    headers: { authorization: `Bearer ${state.tokens.id_token}` },
  });
  if (response.status === 401) {
    await ensureSession({ force: true });
    response = await fetch(url, { headers: { authorization: `Bearer ${state.tokens.id_token}` } });
  }
  if (response.status === 401) {
    clearSession();
    showWelcome("Your session has expired. Please sign in again.");
    throw new Error("Session expired");
  }
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "The media service could not be reached.");
  return body;
}

function showWelcome(message = "") {
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
    elements.characterModel.removeAttribute("src");
    closePreview();
  }
  elements.gameSelector.value = selected;
  elements.gamePurpose.textContent = state.games.find(g => g.id === selected).purpose === "test" ? "Test game · separate from campaign material" : "";
  if (!state.gameDetail) {
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
  return true;
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

  const copy = document.createElement("span");
  const name = document.createElement("strong");
  name.textContent = character.name;
  const title = document.createElement("small");
  title.textContent = character.title;
  copy.append(name, title);

  const arrow = document.createElement("span");
  arrow.className = "entry-arrow";
  arrow.textContent = "View 3D model";
  button.append(marker, copy, arrow);
  button.addEventListener("click", () => navigate(characterPath(character)));
  elements.characterList.append(button);
}

async function loadCharacters() {
  const epoch = routeEpoch;
  elements.characterProfile.hidden = true;
  elements.characterList.hidden = false;
  elements.charactersStatus.hidden = false;
  elements.charactersStatus.textContent = "Loading characters…";
  if (state.charactersLoaded) {
    elements.charactersStatus.hidden = true;
    return;
  }
  try {
    const result = await api("/characters", { gameId: state.gameId });
    if (epoch !== routeEpoch) return;
    const merged = new Map(state.gameDetail.characters.map(c => [c.id, { ...c, title: "Character" }]));
    for (const c of result.characters) if (c.gameId === state.gameId) merged.set(c.id, c);
    elements.characterList.replaceChildren();
    for (const character of merged.values()) renderCharacterCard(character);
    state.charactersLoaded = true;
    elements.charactersStatus.hidden = true;
    if (!merged.size) {
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

function showModelFallback(message) {
  elements.characterModel.hidden = true;
  elements.modelFallback.hidden = false;
  elements.modelFallbackMessage.textContent = message;
  elements.modelStatus.textContent = message;
  elements.modelReset.disabled = true;
}

function configureCharacter(profile) {
  const { character, model, poster } = profile;
  state.currentCharacter = { gameId: character.gameId, characterId: character.id };
  elements.characterName.textContent = character.name;
  elements.characterTitle.textContent = character.title;
  elements.characterSummary.textContent = character.summary;
  document.querySelector("#character-model-area").hidden = !model;
  document.querySelector("#character-no-model").hidden = Boolean(model);
  if (!model) { state.currentCharacter = null; return; }
  elements.characterPoster.src = poster.url;
  elements.characterPoster.alt = `Portrait of ${character.name}`;
  elements.fallbackPoster.src = poster.url;
  elements.fallbackPoster.alt = `Portrait of ${character.name}`;
  elements.characterModel.alt = `Interactive 3D model of ${character.name}`;
  elements.characterModel.cameraOrbit = model.cameraOrbit;
  elements.characterModel.fieldOfView = model.fieldOfView;
  elements.characterModel.dataset.defaultCameraOrbit = model.cameraOrbit;
  elements.characterModel.dataset.defaultFieldOfView = model.fieldOfView;
  elements.characterModel.removeAttribute("src");
  if (typeof elements.characterModel.showPoster === "function") {
    elements.characterModel.showPoster();
  }
  elements.characterModel.hidden = false;
  elements.modelFallback.hidden = true;
  elements.modelLoad.disabled = false;
  elements.modelLoad.textContent = "Explore 3D model";
  elements.modelReset.disabled = true;
  elements.modelProgressBar.style.transform = "scaleX(0)";
  elements.modelSize.textContent = `${formatBytes(model.size)} · limit ${formatBytes(5 * 1024 * 1024)}`;
  elements.modelSource.textContent =
    model.sourceRetained && model.provenanceRetained
      ? "Original and provenance retained"
      : "Web representation";
  elements.modelStatus.textContent = "Portrait ready. Load the model when you want it.";
}

async function loadCharacter(gameId, characterId) {
  const epoch = routeEpoch;
  document.getElementById("character-assets-list").replaceChildren();
  document.getElementById("character-assets-status").textContent = "Loading associated assets…";
  elements.characterList.hidden = true;
  elements.characterProfile.hidden = true;
  elements.charactersStatus.hidden = false;
  elements.charactersStatus.textContent = "Loading character…";
  try {
    const profile = await api("/character", { gameId, characterId });
    if (epoch !== routeEpoch) return;
    configureCharacter(profile);
    elements.characterProfile.hidden = false;
    elements.charactersStatus.hidden = true;
    void loadCharacterAssets(gameId, characterId, epoch);
  } catch (error) {
    if (epoch !== routeEpoch) return;
    const character = state.gameDetail?.characters.find(c => c.id === characterId);
    if (character && error.message === "Character not found") {
      configureCharacter({ character: { ...character, title: "Character", summary: "" } });
      elements.characterProfile.hidden = false;
      elements.charactersStatus.hidden = true;
      void loadCharacterAssets(gameId, characterId, epoch);
      return;
    }
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
    for (const asset of matching) {
      const li = document.createElement("li");
      li.append(assetLink(asset), document.createTextNode(` · ${asset.kind}`));
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
  elements.modelStatus.textContent = "Preparing a fresh private model link…";
  try {
    const profile = await api("/character", state.currentCharacter);
    await Promise.race([
      customElements.whenDefined("model-viewer"),
      new Promise((_, reject) =>
        window.setTimeout(() => reject(new Error("3D viewer unavailable")), 10_000),
      ),
    ]);
    if (epoch !== routeEpoch) return;
    elements.characterModel.src = profile.model.url;
    elements.characterModel.dismissPoster();
    elements.modelStatus.textContent = "Loading the 3D model…";
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
  elements.characterModel.jumpCameraToGoal();
  elements.modelStatus.textContent = "Default view restored.";
}

async function renderRoute() {
  const epoch = ++routeEpoch;
  clearLibrary();
  closePreview();
  elements.novel.hidden = true;
  clearNovel();
  try { await ensureSession(); } catch (error) { showWelcome(error.message); return; }
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
  if (epoch === routeEpoch && sameGameKey(key)) await previewFile({key, name: key.split("/").at(-1)});
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
  elements.status.textContent = cursor ? "Loading more…" : "Loading…";
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
    const image = document.createElement("img");
    image.src = url;
    image.alt = title;
    return image;
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
  for (const media of elements.previewBody.querySelectorAll("audio, video")) media.pause();
  const epoch = ++previewEpoch;
  elements.previewTitle.textContent = file.name;
  elements.previewBody.textContent = "Preparing preview…";
  document.getElementById("asset-links").textContent = "Loading connections…";
  elements.previewDetails.textContent = formatBytes(file.size);
  elements.openOriginal.removeAttribute("href");
  if (!elements.previewDialog.open) elements.previewDialog.showModal();

  try {
    const result = await api("/object-url", { key: file.key });
    if (epoch !== previewEpoch) return;
    const structured = file.key.endsWith(".json") && sameGameKey(file.key);
    if (structured) elements.previewBody.textContent = "Loading structured document…";
    else elements.previewBody.replaceChildren(previewElement(result.contentType, result.url, file.name));
    elements.previewDetails.textContent = `${formatBytes(result.size)} · link valid for ${Math.round(result.expiresIn / 60)} minutes`;
    elements.openOriginal.href = result.url;
    if (/^(audio|video)\//.test(result.contentType)) attachMediaRecovery(elements.previewBody.firstChild, file.key, () => epoch === previewEpoch);
    void renderAssetLinks(file.key, epoch);
    if (structured) {
      const detail = await api("/asset-document", {gameId: state.gameId, key: file.key});
      if (epoch !== previewEpoch) return;
      renderStructuredAsset(detail, epoch);
    }
  } catch (error) {
    if (epoch !== previewEpoch) return;
    elements.previewBody.textContent = error.message;
  }
}

function closePreview() {
  previewEpoch += 1;
  for (const media of elements.previewBody.querySelectorAll("audio, video")) { media.pause(); media.removeAttribute("src"); media.load(); }
  elements.previewDialog.close();
  elements.previewBody.replaceChildren();
  elements.openOriginal.removeAttribute("href");
  document.getElementById("asset-links").replaceChildren();
}

const novel = Object.fromEntries(["status", "list", "reader", "prose", "title", "manuscript",
  "details", "notice", "pagination", "read", "show-details", "download", "back", "refresh"]
  .map(name => [name, document.getElementById(`novel-${name}`)]));
let currentChapter = null;

function clearNovel() {
  currentChapter = null;
  novel.reader.hidden = true;
  for (const part of ["list", "prose", "details", "pagination", "title", "notice"]) novel[part].replaceChildren();
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
function narrativeReferences(chapter, assets, chapters) {
  const characters = state.gameDetail.characters || [];
  const resolvers = {
    character: target => {
      const c = characters.find(c => c.id === target.id);
      if (!c || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(c.id)) return null;
      return {identity: `character:${c.id}`, make: text => {
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
      return asset ? {identity: `asset:${asset.key}`, make: text => assetLink(asset, text)} : null;
    },
    chapter: target => chapters.some(c => c.id === target.id && /^[a-f0-9]{64}$/.test(c.id))
      ? {identity: `chapter:${target.id}`, make: text => novelLink(text, target.id)} : null,
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
      }
      end = match.index + match[0].length;
    }
    parent.append(document.createTextNode(part.slice(end)));
  }
}

function novelLink(title, id) {
  const link = document.createElement("a");
  link.href = gamePath(`novel/${id}`);
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
  const sourceTitle = document.createElement("h3"); sourceTitle.textContent = "Source artifacts";
  const sources = document.createElement("div"); sources.className = "novel-sources";
  const keys = new Set([chapter.details.rawReference?.key, ...(chapter.details.sourceKeys || []), chapter.details.artifact?.key]);
  for (const key of keys) {
    if (typeof key !== "string" || !key.startsWith(`games/${state.gameId}/assets/`)) continue;
    const button = document.createElement("button"); button.className = "quiet-button";
    button.textContent = key.split("/").at(-1); button.title = key;
    button.addEventListener("click", () => previewFile({key, name: button.textContent}));
    sources.append(button);
  }
  const provenance = document.createElement("details");
  const label = document.createElement("summary"); label.textContent = "Full provenance and revision history";
  const data = document.createElement("pre"); data.textContent = JSON.stringify(chapter.details, null, 2);
  provenance.append(label, data);
  novel.details.replaceChildren(heading, summary, versionsTitle, versionList, reviewTitle, review, notes, sourceTitle, sources, provenance);
}

async function loadNovel(chapterId, epoch) {
  const gameId = state.gameId;
  const current = () => epoch === routeEpoch && state.gameId === gameId && state.tokens;
  novel.status.textContent = "Loading chapters…";
  novel.status.hidden = false;
  try {
    const chapters = [];
    let cursor;
    do {
      const page = await api("/novel", {gameId, cursor});
      if (!current()) return;
      chapters.push(...page.chapters);
      cursor = page.cursor;
    } while (cursor);
    // A session can have multiple immutable editions; only the latest appears in the TOC.
    chapters.sort((a, b) => b.createdAt - a.createdAt || b.id.localeCompare(a.id));
    const sessions = new Map();
    for (const chapter of chapters) {
      if (!sessions.has(chapter.sessionId)) sessions.set(chapter.sessionId, []);
      sessions.get(chapter.sessionId).push(chapter);
    }
    const ordered = [...sessions.values()].sort((a, b) => a.at(-1).createdAt - b.at(-1).createdAt || a[0].sessionId.localeCompare(b[0].sessionId)).map(v => v[0]);
    if (!chapterId) {
      novel.status.hidden = Boolean(ordered.length);
      novel.status.textContent = "No chapters yet. Completed novel chapters will appear here automatically.";
      for (const [index, chapter] of ordered.entries()) {
        const card = document.createElement("div"); card.className = "novel-card";
        const number = document.createElement("p"); number.className = "eyebrow"; number.textContent = `Chapter ${index + 1}`;
        const title = document.createElement("h2"); title.append(novelLink(chapter.title, chapter.id));
        const meta = document.createElement("p"); meta.textContent = `${chapter.sessionId} · ${chapterDate(chapter)}${chapter.publicationStatus === "accepted-with-notes" ? " · Working draft" : ""}`;
        card.append(number, title, meta); novel.list.append(card);
      }
      return;
    }
    const chapter = await api("/novel-chapter", {gameId, chapterId});
    if (!current()) return;
    currentChapter = chapter;
    novel.title.textContent = chapter.title;
    proseMarkdown(novel.prose, chapter.markdown);
    chapterDetails(chapter, sessions.get(chapter.sessionId) || [chapter]);
    novel.notice.textContent = [chapter.notice,
      state.gameDetail.game.purpose === "test" ? "Test-game adaptation · not campaign canon." : "",
      chapter.publicationStatus === "accepted-with-notes" ? "Working draft · AI review left unresolved notes. See Details." : "",
      sessions.get(chapter.sessionId)?.[0].id !== chapter.id ? "You are reading an earlier version. See Details for the latest." : "",
    ].filter(Boolean).join(" ");
    novel.notice.hidden = !novel.notice.textContent;
    novelView(false);
    novel.reader.hidden = false;
    novel.status.hidden = true;
    // Link enrichment is optional: a catalog outage must not prevent reading the manuscript.
    proseMarkdown(novel.prose, chapter.markdown, narrativeReferences(chapter, [], chapters));
    void allAssets(gameId).then(assets => {
      if (current()) proseMarkdown(novel.prose, chapter.markdown, narrativeReferences(chapter, assets, chapters));
    }).catch(() => {
      if (current()) { novel.status.hidden = false; novel.status.textContent = "Some asset links could not be loaded. The story is available; Refresh chapters to retry."; }
    });
    const index = ordered.findIndex(c => c.sessionId === chapter.sessionId);
    if (index > 0) novel.pagination.append(novelLink(`← ${ordered[index - 1].title}`, ordered[index - 1].id));
    if (index >= 0 && index < ordered.length - 1) novel.pagination.append(novelLink(`${ordered[index + 1].title} →`, ordered[index + 1].id));
  } catch (error) {
    if (!current()) return;
    novel.status.hidden = false;
    novel.status.textContent = `${error.message}. Use Refresh chapters to retry.`;
  }
}

let assetIndex = null;
function sameGameKey(key) {
  return typeof key === "string" && key.startsWith(`games/${state.gameId}/assets/`)
    && !key.split("/").includes("..") && !/[\x00-\x1f]/.test(key);
}

function clearLibrary() {
  document.getElementById("session-library").hidden = true;
  document.getElementById("library-list").replaceChildren();
  if (!state.tokens) assetIndex = null;
}

async function allAssets(gameId) {
  if (assetIndex?.gameId === gameId) return assetIndex.promise;
  const entry = {gameId};
  entry.promise = (async () => {
    const assets = []; let cursor = null; const seen = new Set();
    do {
      const page = await api("/assets", {gameId, cursor});
      if (!Array.isArray(page.assets)) throw new Error("Asset catalog unavailable");
      assets.push(...page.assets);
      if (assets.length > 5000) throw new Error("Catalog exceeds this reader's limit; incomplete results are not displayed.");
      cursor = page.cursor;
      if (cursor && (seen.has(cursor) || seen.size >= 200)) throw new Error("Catalog exceeds this reader's limit; incomplete results are not displayed.");
      if (cursor) seen.add(cursor);
    } while (cursor);
    return assets;
  })().catch(error => { if (assetIndex === entry) assetIndex = null; throw error; });
  assetIndex = entry;
  return entry.promise;
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

async function loadLibrary(section, epoch) {
  const gameId = state.gameId, current = () => epoch === routeEpoch && gameId === state.gameId && state.tokens;
  const status = document.getElementById("library-status"), list = document.getElementById("library-list");
  document.getElementById("session-library").hidden = false;
  document.getElementById("library-title").textContent = {audio:"Audio", transcripts:"Transcripts", videos:"Videos"}[section];
  status.textContent = "Loading session assets…";
  try {
    const assets = await allAssets(gameId);
    if (!current()) return;
    const manifests = new Set(assets.filter(a => a.recording?.partCount > 0).map(a => a.key.split("/")[3]));
    const keys = new Set(assets.map(a => a.key));
    const selected = assets.filter(a => section === "audio"
      ? a.recording?.partCount > 0 || ((a.contentType.startsWith("audio/") || /\.(flac|wav|mp3|m4a|ogg)$/i.test(a.name)) && !manifests.has(a.key.split("/")[3]))
      : section === "videos" ? a.contentType.startsWith("video/") || /\.(mp4|webm|mov|m4v|ogv)$/i.test(a.name)
      : ["transcript", "raw-transcript", "corrected-transcript", "edited-transcript"].includes(a.kind)
        && !(a.key.endsWith(".md") && keys.has(a.key.slice(0,-3) + ".json")));
    selected.sort((a,b) => (b.metadata?.sessionId || "").localeCompare(a.metadata?.sessionId || "") || b.lastModified.localeCompare(a.lastModified) || a.name.localeCompare(b.name));
    status.textContent = selected.length
      ? section === "videos" ? "Episodes, experiments and other videos. Open a video to play it and explore its inputs and outputs."
        : section === "audio" ? "Continuous session playback. Lossless original parts are retained separately." : "All saved versions. Raw recognition is preserved; corrected transcripts are separate and may still contain uncertainty."
      : `No ${section === "audio" ? "recordings" : section} yet for this game.`;
    for (const asset of selected) {
      const card = document.createElement("article"); card.className = "novel-card session-card";
      const heading = document.createElement("h2");
      const label = section === "audio" && asset.kind === "recording-manifest" ? `Recording · ${asset.metadata?.sessionId || asset.name}` : asset.metadata?.title || asset.name;
      heading.append(assetLink(asset, label));
      const kind = document.createElement("p");
      kind.textContent = `${asset.metadata?.sessionId || "Session not recorded"} · ${asset.kind === "raw-transcript" ? "Raw transcript" : ["corrected-transcript", "edited-transcript"].includes(asset.kind) ? "Corrected / edited transcript" : asset.kind} · ${section === "videos" ? "Video" : asset.name.endsWith(".json") ? "Structured reader" : asset.name.endsWith(".md") ? "Markdown export" : "Original audio"}`;
      const date = document.createElement("p"); date.textContent = new Date(asset.lastModified).toLocaleString();
      card.append(heading, kind, date); list.append(card);
    }
  } catch (error) {
    if (current()) status.textContent = `${error.message}. Use Refresh to retry.`;
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
    const inputs = (item.sourceKeys || []).filter(sameGameKey);
    const outputs = assets.filter(a => a.sourceKeys?.includes(key));
    for (const [title, records] of [["Inputs", inputs.map(k => assets.find(a => a.key === k) || {key:k, name:`Unavailable or unindexed · ${k.split("/").at(-1)}`} )], ["Outputs", outputs]]) {
      const heading = document.createElement("h3"); heading.textContent = title;
      const list = document.createElement("ul");
      for (const record of records) { const li = document.createElement("li"); li.append(assetLink(record)); list.append(li); }
      if (!records.length) { const li = document.createElement("li"); li.textContent = `No ${title.toLowerCase()} recorded.`; list.append(li); }
      host.append(heading, list);
    }
    const companions = assets.filter(a => a.key !== key && a.key.split("/")[3] === key.split("/")[3]);
    if (companions.length) {
      const details = document.createElement("details"), summary = document.createElement("summary"), list = document.createElement("ul");
      summary.textContent = "Related files in this asset";
      for (const asset of companions) { const li = document.createElement("li"); li.append(assetLink(asset)); list.append(li); }
      details.append(summary, list); host.append(details);
    }
    const warnings = assets.filter(a => a.lineageWarning).length;
    if (warnings) { const warning = document.createElement("p"); warning.textContent = `${warnings} asset(s) have incomplete structured provenance; output links may be incomplete.`; host.append(warning); }
    const note = document.createElement("p"); note.className = "status";
    note.textContent = "Recorded relationships, not proof of factual accuracy. Historical missing links are not inferred."; host.append(note);
  } catch (error) { if (current()) host.textContent = `Connections unavailable: ${error.message}. Close and reopen to retry.`; }
}

function detailBlock(title, value) {
  const details = document.createElement("details"), summary = document.createElement("summary"), pre = document.createElement("pre");
  summary.textContent = title; pre.textContent = JSON.stringify(value, null, 2); details.append(summary, pre); return details;
}

function timestamp(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "Unknown time";
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2,"0")}`;
}

function attachMediaRecovery(audio, key, current) {
  audio.preload = "metadata";
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
  const transcript = doc.entityType === "PlayerTranscript" ? doc : doc.stage === "corrected-transcript" ? doc.payload?.transcript : null;
  if (transcript && Array.isArray(transcript.segments)) {
    const notice = document.createElement("p"); notice.className = "novel-notice";
    const edited = [asset.kind, doc.stage, doc.artifactType].some(kind => ["corrected-transcript", "edited-transcript"].includes(kind));
    notice.textContent = `${edited ? "Corrected / edited transcript" : "Raw transcript"} · ${doc.reviewStatus || "unreviewed"}. Speakers identify players, not characters.`;
    if (doc.publicationStatus === "accepted-with-notes") notice.textContent += " Working draft with unresolved review notes.";
    if (!transcript.captureIntegrity) notice.textContent += " Capture integrity was not recorded in this version.";
    host.append(notice);
    if (transcript.captureIntegrity) host.append(detailBlock("Capture integrity and warnings", transcript.captureIntegrity));
    const people = new Map((transcript.players || []).map(p => [p.id, p.name]));
    for (const segment of transcript.segments) {
      const line = document.createElement("section"); line.className = "transcript-segment";
      const heading = document.createElement("h3"), text = document.createElement("p");
      heading.textContent = `${timestamp(segment.start)}–${timestamp(segment.end)} · ${people.get(segment.playerId) || segment.playerId || "Unassigned speaker"}`;
      text.textContent = typeof segment.text === "string" ? segment.text : "[Missing text]";
      line.append(heading, text);
      const annotations = Object.fromEntries(Object.entries(segment).filter(([k]) => !["start","end","text","playerId"].includes(k)));
      if (Object.keys(annotations).length) line.append(detailBlock("Evidence and annotations", annotations));
      host.append(line);
    }
    if (doc.payload?.review) host.append(detailBlock("Correction review", doc.payload.review));
    host.append(detailBlock("Transcript corrections, uncertainty and provenance", Object.fromEntries(
      Object.entries(transcript).filter(([key]) => key !== "segments")
    )));
    if (doc.revisionHistory) host.append(detailBlock("Editorial revision history", doc.revisionHistory));
  } else if (doc.entityType === "Recording" && Array.isArray(doc.parts)) {
    const notice = document.createElement("p"); notice.textContent = `Recording status: ${doc.status || "unknown"} · ${doc.parts.length} lossless original parts retained. One continuous listening copy; assembly does not repair capture gaps.`;
    const audio = document.createElement("audio"); audio.controls = true; audio.preload = "metadata";
    const status = document.createElement("p"); status.setAttribute("role", "status"); status.textContent = "Loading continuous recording…";
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
          status.textContent = "Continuous playback has not been prepared yet. It is produced after the uploaded chunk set is marked complete and the laptop workflow runs. Lossless originals remain under Inputs.";
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

document.getElementById("library-refresh").addEventListener("click", () => { assetIndex = null; void renderRoute(); });
novel.refresh.addEventListener("click", () => { assetIndex = null; void renderRoute(); });
document.getElementById("character-assets-refresh").addEventListener("click", () => { assetIndex = null; void renderRoute(); });
novel.back.addEventListener("click", () => navigate(gamePath("novel")));
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
elements.characterModel.addEventListener("progress", (event) => {
  const progress = Math.max(0, Math.min(1, event.detail.totalProgress || 0));
  elements.modelProgressBar.style.transform = `scaleX(${progress})`;
  elements.modelStatus.textContent = `Loading the 3D model… ${Math.round(progress * 100)}%`;
});
elements.characterModel.addEventListener("load", () => {
  elements.modelProgressBar.style.transform = "scaleX(1)";
  elements.modelStatus.textContent = "Model ready. Drag, zoom, or use the keyboard to explore.";
  elements.modelReset.disabled = false;
});
elements.characterModel.addEventListener("error", () => {
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

async function start() {
  if (!config?.apiUrl || !config?.clientId || !config?.cognitoDomain || !config?.redirectUri) {
    showWelcome("The media explorer is not configured yet.");
    return;
  }
  try {
    await completeLogin();
    await ensureSession();
    await renderRoute();
  } catch (error) {
    // Offline/5xx failures must not discard a valid remembered session or route.
    showWelcome(error.message);
  }
}

start();
