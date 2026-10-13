// When to try again after a 429 (REQ-TEN-02, REQ-ENG-17; the P28 review's MAJOR 6): the API's Retry-After header,
// said roughly in the page's words (`retryAfter.*`), never a promise the server did not make. Pure: the pages, the
// client islands and their tests share it.

/** Seconds from a Retry-After value (delay-seconds or an HTTP date), or null when there is none or it is unreadable. */
export function retryAfterSeconds(value: string | null | undefined, now: number = Date.now()): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed);
  const at = Date.parse(trimmed);
  return Number.isNaN(at) ? null : Math.max(0, Math.round((at - now) / 1000));
}

/** Which `retryAfter.*` sentence says the wait, with its figure: rounded up to minutes, then to hours past one. */
export type RetryWhen = { key: "minute" | "minutes" | "hour" | "hours" | "later"; count?: number };

export function retryWhen(seconds: number | null | undefined): RetryWhen {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return { key: "later" };
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  if (minutes <= 1) return { key: "minute" };
  if (minutes < 60) return { key: "minutes", count: minutes };
  const hours = Math.round(minutes / 60);
  return hours <= 1 ? { key: "hour" } : { key: "hours", count: hours };
}
