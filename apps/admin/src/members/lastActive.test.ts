import { describe, expect, it } from "vitest";
import { lastActive } from "./lastActive";

// Local-time dates (no "Z"): the helper compares calendar days of the browser zone.
const NOW = new Date("2026-10-21T00:10:00");

describe("lastActive", () => {
  it("is_never_for_null", () => {
    expect(lastActive(null, NOW)).toEqual({ key: "never" });
  });

  it("is_today_for_the_same_calendar_day", () => {
    expect(lastActive("2026-10-21T00:05:00", NOW)).toEqual({ key: "today" });
    expect(lastActive("2026-10-21T23:59:00", new Date("2026-10-21T23:59:30"))).toEqual({
      key: "today",
    });
  });

  it("is_today_for_a_moment_slightly_in_the_future_clock_skew", () => {
    expect(lastActive("2026-10-21T00:30:00", NOW)).toEqual({ key: "today" });
  });

  it("is_yesterday_across_midnight_even_within_24_hours", () => {
    expect(lastActive("2026-10-20T23:50:00", NOW)).toEqual({ key: "yesterday" });
  });

  it("counts_calendar_days_for_older_moments", () => {
    expect(lastActive("2026-10-19T12:00:00", NOW)).toEqual({ key: "daysAgo", days: 2 });
    expect(lastActive("2026-10-18T01:00:00", NOW)).toEqual({ key: "daysAgo", days: 3 });
    expect(lastActive("2026-09-21T12:00:00", NOW)).toEqual({ key: "daysAgo", days: 30 });
  });
});
