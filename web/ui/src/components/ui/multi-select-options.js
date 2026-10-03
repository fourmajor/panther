// Match names, not internal identifiers. Selected entries stay out of the
// suggestion list; the original option order makes Enter deterministic.
export function matchingOptions(options, value, query) {
  const selected = new Set(value);
  const needle = query.trim().toLocaleLowerCase();
  const seen = new Set();
  return options.filter(option => {
    if (seen.has(option.id)) return false;
    seen.add(option.id);
    return !selected.has(option.id) && String(option.name ?? option.label ?? option.id).toLocaleLowerCase().includes(needle);
  });
}
export function addSelection(value, id) {
  return value.includes(id) ? value : [...value, id];
}
