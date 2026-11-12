/** Visual states for the session graph.
 * Gray is not started. Blue is running. Green is success. Red is failed.
 * The storyboard gate stays a distinct waiting state so paid video never looks authorized.
 */

export function presentation(status, id) {
  if (id === "storyboard-approval" && (status === "paused" || status === "queued")) return "gate";
  if (status === "done" || status === "failed" || status === "running") return status;
  return "pending";
}

export function statusText(status, id) {
  if (presentation(status, id) === "gate") return "Needs approval";
  return {done: "Done", failed: "Failed", running: "Running", queued: "Queued", paused: "Waiting", unknown: "Unknown", pending: "Not started"}[status] || "Not started";
}

export function workerLabel(id) {
  return {editorial: "Editorial", playback: "Playback", model: "Model"}[id] || id;
}

export function sessionHeadline(title, id) {
  const source = String(title || id || "").trim();
  const dated = source.match(/^(?:session-)?(20\d{2}-\d{2}-\d{2})$/);
  if (dated) return dated[1];
  return source || "Session";
}

export function cardTone(status) {
  if (status === "failed") return "failed";
  if (status === "done") return "done";
  if (status === "running" || status === "queued") return "running";
  if (status === "paused") return "paused";
  return "pending";
}

export function cardText(pipeline) {
  const status = pipeline?.status || "pending";
  const stage = pipeline?.stage;
  if (status === "pending") return "Not started";
  if (status === "done") return stage?.title ? `Done · ${stage.title}` : "Done";
  if (!stage) return statusText(status);
  if (status === "failed") return `Failed · ${stage.title}`;
  if (status === "running" || status === "queued") return `Running · ${stage.title}`;
  if (status === "started") return stage.title;
  return `${statusText(stage.status, stage.id)} · ${stage.title}`;
}

export function formatWhen(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  const date = new Date(n > 1e12 ? n : n * 1000);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {dateStyle: "medium", timeStyle: "short"}).format(date);
}

export function runIdentity(run) {
  if (!run?.id) return null;
  const id = String(run.id).trim();
  const bare = id.includes("~") ? id.slice(id.indexOf("~") + 1) : id;
  return bare || null;
}
