import { getTranslations } from "next-intl/server";

import { EmptyState } from "./EmptyState";
import { ACTION_HREF, type Refusal } from "./refusals";

/**
 * An organisation read refused before anything could be shown, as the Inbox words it: turn on two-step sign-in, or
 * enter the code (each the screen's one primary action), or not available with a way back. One sentence, one action.
 */
export async function OrgRefusal({
  refusal,
  orgName,
  back,
}: {
  refusal: Refusal;
  orgName: string;
  /** Where "not available" leads, with its words. */
  back: { href: string; action: string };
}) {
  const t = await getTranslations("inbox");
  const tp = await getTranslations("orgProposal");
  if (refusal === "mfa_enrolment_required") {
    return (
      <EmptyState
        sentence={t("refusedMfaSetup", { org: orgName })}
        action={tp("action.turnOnMfa")}
        href={ACTION_HREF.turnOnMfa!}
        primary
      />
    );
  }
  if (refusal === "mfa_required") {
    return <EmptyState sentence={t("refusedMfaCode")} action={tp("action.enterCode")} href={ACTION_HREF.enterCode!} primary />;
  }
  return <EmptyState sentence={t("refusedNotFound")} action={back.action} href={back.href} />;
}
