import type { StringTree } from "@/components/ClientStrings";
import { clientStrings } from "@/lib/i18n/client-strings";

/**
 * The strings the console's step-up form reads (research/StepUp.tsx, P11-F: adminResearch.stepUp.* and
 * adminResearch.refusal.generic), without the rest of the research namespace: every console section asks for a fresh
 * code the same way.
 */
export async function stepUpStrings(): Promise<Record<string, StringTree>> {
  const { adminResearch } = await clientStrings(["adminResearch"]);
  const refusal = adminResearch.refusal as StringTree;
  return { adminResearch: { stepUp: adminResearch.stepUp, refusal: { generic: refusal.generic } } };
}
