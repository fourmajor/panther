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
