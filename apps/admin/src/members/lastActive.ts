export type LastActive =
  { key: "never" } | { key: "today" } | { key: "yesterday" } | { key: "daysAgo"; days: number };

const MS_PER_DAY = 86_400_000;

function calendarDay(date: Date): number {
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
}

/**
 * How long ago a moment was, in calendar days of the browser's time zone (not 24-hour spans):
 * a sign-in at 23:50 yesterday is "Yesterday" at 00:10 today. `null` means never.
 */
export function lastActive(iso: string | null, now: Date): LastActive {
  if (iso === null) return { key: "never" };
  const days = Math.round((calendarDay(now) - calendarDay(new Date(iso))) / MS_PER_DAY);
  if (days <= 0) return { key: "today" };
  if (days === 1) return { key: "yesterday" };
  return { key: "daysAgo", days };
}
