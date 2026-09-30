import type { StringTree } from "@/components/ClientStrings";
import { clientStrings } from "@/lib/i18n/client-strings";

/**
 * The strings the console's step-up form reads (research/StepUp.tsx, P11-F: adminResearch.stepUp.* and
 * adminResearch.refusal.generic), without the rest of the research namespace.
 */
export async function stepUpStrings(): Promise<Record<string, StringTree>> {
  const { adminResearch } = await clientStrings(["adminResearch"]);
  const refusal = adminResearch.refusal as StringTree;
  return { adminResearch: { stepUp: adminResearch.stepUp, refusal: { generic: refusal.generic } } };
}

/** The case page's client strings: its own namespace and the step-up form's. */
export async function caseStrings(): Promise<Record<string, StringTree>> {
  return { ...(await clientStrings(["adminModeration"])), ...(await stepUpStrings()) };
}
