import type { components } from "@/lib/api/schema";

// Label keys for the API's enums on the organisation screens (plain keys, not ICU select: every locale message keeps
// the same arguments in both languages, locales/locales.test.ts).

type EngagementState = components["schemas"]["EngagementState"];
type Maturity = components["schemas"]["ProposalMaturity"];

const LABELLED_STAGES = [
  "SUBMITTED",
  "UNDER_REVIEW",
  "INFO_REQUESTED",
  "ON_HOLD",
  "DECLINED",
  "WITHDRAWN",
  "TERMINATED",
  "EXPIRED",
  "CLOSED",
] as const satisfies readonly EngagementState[];
type LabelledStage = (typeof LABELLED_STAGES)[number];
const LABELLED: ReadonlySet<string> = new Set(LABELLED_STAGES);

/**
 * `inbox.stage.*`: the stages the Inbox names (an open question and a hold as the tracker labels them); every other
 * open stage reads "In progress".
 */
export function stageKey(state: EngagementState): `stage.${LabelledStage | "other"}` {
  return LABELLED.has(state) ? `stage.${state as LabelledStage}` : "stage.other";
}

/** `ideaFields.maturityValue.*` (shared with the developer's editor; "prototype" is not a usable message key). */
export const MATURITY_KEY = {
  idea: "maturityValue.idea",
  prototype: "maturityValue.prototypeStage",
  mvp: "maturityValue.mvp",
  live: "maturityValue.live",
} as const satisfies Record<Maturity, string>;
