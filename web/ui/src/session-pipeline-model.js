/** Visual states for the session graph. Queued and waiting stay not-started gray. */

export function presentation(status) {
  if (status === "done" || status === "failed" || status === "running") return status;
  return "pending";
}

export function statusText(status) {
  return {done: "Done", failed: "Failed", running: "Running", queued: "Queued", paused: "Waiting", unknown: "Unknown", pending: "Not started"}[status] || "Not started";
}
