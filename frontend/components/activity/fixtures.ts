import type { Activity } from "./calendar";

/** 26 weeks ending Thursday 8 Oct 2026 (Nairobi), as GET /api/me/activity?weeks=26 answers it (the P25-B shape). */
export function activityFixture(counts: Record<string, number> = {}, to = "2026-10-08"): Activity {
  const end = Date.parse(`${to}T00:00:00Z`);
  const days = Array.from({ length: 182 }, (_, i) => {
    const date = new Date(end - (181 - i) * 86_400_000).toISOString().slice(0, 10);
    return { date, count: counts[date] ?? 0 };
  });
  const total = days.reduce((sum, d) => sum + d.count, 0);
  return {
    from: days[0].date,
    to,
    timezone: "Africa/Nairobi",
    days,
    kinds: total ? [{ kind: "version_registered", count: Math.ceil(total / 2) }, { kind: "message_sent", count: Math.floor(total / 2) }] : [],
    total,
  };
}
