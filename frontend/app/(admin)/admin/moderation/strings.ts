import type { StringTree } from "@/components/ClientStrings";
import { clientStrings } from "@/lib/i18n/client-strings";

import { stepUpStrings } from "../strings";

/** The case page's client strings: its own namespace and the step-up form's. */
export async function caseStrings(): Promise<Record<string, StringTree>> {
  return { ...(await clientStrings(["adminModeration"])), ...(await stepUpStrings()) };
}
