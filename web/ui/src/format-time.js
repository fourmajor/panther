/** One user-visible timestamp format: medium date, 24-hour clock, no AM/PM. */
export const TIMESTAMP_OPTIONS = {
  dateStyle: "medium",
  timeStyle: "short",
  hourCycle: "h23",
};

export function formatTimestamp(value, locale) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, TIMESTAMP_OPTIONS).format(date);
}
