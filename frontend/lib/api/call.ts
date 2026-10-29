import { errorKey, type ErrorKey } from "./errors";

export type ApiOutcome<T> = { ok: true; data: T; status: number } | { ok: false; key: ErrorKey; status: number };

/**
 * Settles an openapi-fetch call into success or an `errors.*` key. A thrown fetch (offline, DNS, reset) becomes
 * "network", so screens never show a raw exception.
 */
export async function settle<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<ApiOutcome<T>> {
  try {
    const { data, error, response } = await call;
    if (response.ok) return { ok: true, data: data as T, status: response.status };
    return { ok: false, key: errorKey(error), status: response.status };
  } catch {
    return { ok: false, key: "network", status: 0 };
  }
}
