const config = window.PANTHER_CONFIG;

const elements = {
  gameToolbar: document.querySelector("#game-toolbar"),
  gameSelector: document.querySelector("#game-selector"),
  gamePurpose: document.querySelector("#game-purpose"),
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
  elements.characterModel.src = null;
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
  elements.gameToolbar.hidden = true;
  elements.welcome.hidden = false;
  elements.explorer.hidden = true;
  elements.characters.hidden = true;
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
  } catch (error) {
    if (epoch !== routeEpoch) return;
    const character = state.gameDetail?.characters.find(c => c.id === characterId);
    if (character && error.message === "Character not found") {
      configureCharacter({ character: { ...character, title: "Character", summary: "" } });
      elements.characterProfile.hidden = false;
      elements.charactersStatus.hidden = true;
      return;
    }
    if (error.message !== "Session expired") {
      elements.charactersStatus.textContent = error.message;
    }
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
  try { await ensureSession(); } catch (error) { showWelcome(error.message); return; }
  if (epoch !== routeEpoch) return;
  showApplicationChrome();
  const gameRoute = window.location.pathname.match(/^\/games\/([a-z0-9]+(?:-[a-z0-9]+)*)\/(media|characters)(?:\/([a-z0-9]+(?:-[a-z0-9]+)*))?\/?$/);
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
  frame.src = url;
  frame.title = title;
  return frame;
}

async function previewFile(file) {
  const epoch = ++previewEpoch;
  elements.previewTitle.textContent = file.name;
  elements.previewBody.textContent = "Preparing preview…";
  elements.previewDetails.textContent = formatBytes(file.size);
  elements.openOriginal.removeAttribute("href");
  elements.previewDialog.showModal();

  try {
    const result = await api("/object-url", { key: file.key });
    if (epoch !== previewEpoch) return;
    elements.previewBody.replaceChildren(previewElement(result.contentType, result.url, file.name));
    elements.previewDetails.textContent = `${formatBytes(result.size)} · link valid for ${Math.round(result.expiresIn / 60)} minutes`;
    elements.openOriginal.href = result.url;
  } catch (error) {
    if (epoch !== previewEpoch) return;
    elements.previewBody.textContent = error.message;
  }
}

function closePreview() {
  previewEpoch += 1;
  elements.previewDialog.close();
  elements.previewBody.replaceChildren();
  elements.openOriginal.removeAttribute("href");
}

elements.login.addEventListener("click", login);
elements.logout.addEventListener("click", logout);
elements.refresh.addEventListener("click", () => loadPrefix(state.currentPrefix));
elements.loadMore.addEventListener("click", () => loadPrefix(state.currentPrefix, state.nextCursor));
elements.previewClose.addEventListener("click", closePreview);
elements.previewDialog.addEventListener("click", (event) => {
  if (event.target === elements.previewDialog) closePreview();
});
elements.characterBack.addEventListener("click", () => navigate(gamePath("characters")));
elements.gameSelector.addEventListener("change", () => navigate(`/games/${encodeURIComponent(elements.gameSelector.value)}/${window.location.pathname.includes("characters") ? "characters" : "media"}`));
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
