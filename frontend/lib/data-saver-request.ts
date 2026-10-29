import { headers } from "next/headers";
import { use } from "react";

import { asksToSaveData } from "./data-saver";

// The request's wish to save data, for server components (lib/data-saver.ts): `Save-Data: on` or the data-saver
// switch's cookie. Read from the request's headers (its Cookie header included), so every reader agrees.

type HeaderReader = { get(name: string): string | null };

/** The request asked to save data: no photograph is sent. Outside a request (a test, a static render): nothing asked. */
export async function savesData(): Promise<boolean> {
  try {
    const sent = await headers();
    return asksToSaveData((name) => sent.get(name));
  } catch {
    return false;
  }
}

/**
 * The same, read synchronously (React's `use`), so a band or a picture can sit inside the synchronous server
 * components of cards. Outside a request (a unit test, a static render) `headers()` throws at once: nothing was asked.
 */
export function useSavesData(): boolean {
  let pending: Promise<HeaderReader>;
  try {
    pending = headers();
  } catch {
    return false;
  }
  const sent = use(pending);
  return asksToSaveData((name) => sent.get(name));
}
