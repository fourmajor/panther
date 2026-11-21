/** Latest run that still counts, matching the session badge. Stale runs do not. */
export function latestCurrentRun(runs) {
  return [...(runs || [])]
    .sort((a, b) => (Number(b.startedAt) || 0) - (Number(a.startedAt) || 0) || String(a.id || "").localeCompare(String(b.id || "")))
    .find(run => !run.stale) || null;
}

/** The list card and the detail recap use the cards projection, then the record itself. */
export function recapInputs(record, card) {
  if (card && (card.excerptKey || card.excerptLabel)) {
    return {excerptKey: card.excerptKey || null, excerptLabel: card.excerptLabel || null};
  }
  return {excerptKey: record?.excerptKey || null, excerptLabel: record?.excerptLabel || null};
}
