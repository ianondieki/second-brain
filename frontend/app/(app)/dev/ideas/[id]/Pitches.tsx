import { getLocale, getTranslations } from "next-intl/server";
import type { ComponentType, SVGProps } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ClockIcon, ClosedIcon, SendIcon } from "@/components/ui/icons";
import { Row, RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";
import { clientStrings } from "@/lib/i18n/client-strings";

import { formatDay } from "../dates";
import type { IdeaStatus } from "../status";
import { canWithdraw, heldKey, pitchesLeft, pitchHref, tagState, type MyTags, type TagOut, type TagState } from "./pitch/picker";
import { WithdrawTag } from "./WithdrawTag";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

export const PITCHES_HEADING = "pitches-heading";

// Sent in the success tone; saved, withdrawn and closed neutral (the accent is for "act here").
const LOOK: Record<TagState, { Icon: ComponentType<SVGProps<SVGSVGElement>>; tone: BadgeTone }> = {
  sent: { Icon: SendIcon, tone: "ok" },
  saved: { Icon: ClockIcon, tone: "neutral" },
  withdrawn: { Icon: ClosedIcon, tone: "neutral" },
  closed: { Icon: ClosedIcon, tone: "neutral" },
};

export interface PitchesProps {
  ideaId: string;
  status: IdeaStatus;
  /** Null when the tags could not be read now. */
  tags: MyTags | null;
}

/**
 * The idea's pitches (REQ-PROP-03, REQ-DIR-04), a Section: the plan's cap as "N of M left", then each organisation it
 * was pitched to as a Row with the pitch's state as a Badge (sent, saved until they verify, withdrawn, closed), the
 * held sentence of docs/spec/06 6.2 while it waits, and Withdraw for a saved one. The state is the row's one badge.
 * The heading takes focus after a withdrawal (WithdrawTag).
 */
export async function Pitches({ ideaId, status, tags }: PitchesProps) {
  const t = await getTranslations("ideaPitches");
  const locale = await getLocale();
  const left = tags ? pitchesLeft(tags.cap) : null;
  const pitchable = status === "published" && left !== 0;
  const withdrawable = tags?.items.some(canWithdraw) ?? false;
  const list = tags ? (
    <RowList aria-label={t("listLabel")}>
      {tags.items.map((tag) => (
        <PitchRow key={tag.id} tag={tag} ideaId={ideaId} locale={locale} t={t} />
      ))}
    </RowList>
  ) : null;
  return (
    <Section
      title={t("title")}
      headingId={PITCHES_HEADING}
      focusable
      className="mt-12"
      description={
        !tags ? undefined : (
          <span data-cap="">
            {left === null
              ? t("capUnlimited")
              : left === 0
                ? t("capUsed", { limit: tags.cap.limit ?? 0 })
                : t("capLeft", { count: left, limit: tags.cap.limit ?? 0 })}
          </span>
        )
      }
    >
      {!tags ? (
        <p className="text-ink">{t("loadFailed")}</p>
      ) : (
        <>
          {status !== "published" ? <p className="mb-4 text-ink">{t(`blocked.${status}`)}</p> : null}
          {tags.items.length === 0 ? (
            pitchable ? <EmptyState sentence={t("empty")} action={t("pitch")} href={pitchHref(ideaId)} /> : null
          ) : withdrawable ? (
            <ClientStrings strings={await clientStrings(["tagWithdraw"])}>{list}</ClientStrings>
          ) : (
            list
          )}
        </>
      )}
    </Section>
  );
}

type Translate = Awaited<ReturnType<typeof getTranslations<"ideaPitches">>>;

function PitchRow({ tag, ideaId, locale, t }: { tag: TagOut; ideaId: string; locale: string; t: Translate }) {
  const state = tagState(tag);
  const { Icon, tone } = LOOK[state];
  const name = tag.org?.name ?? t("orgUnlisted");
  const held = state === "saved" ? heldKey(tag.status) : null;
  return (
    <Row
      data-tag={tag.id}
      // The company's page when it is listed; the row holds its own links and Withdraw, so it is not stretched.
      title={name}
      href={tag.org ? `/dev/companies/${encodeURIComponent(tag.org.id)}` : undefined}
      stretch={false}
      meta={t("pitchedOn", { date: formatDay(locale, tag.created_at) })}
      badges={[
        <Badge key="state" data-status={state} tone={tone} icon={<Icon />}>
          {t(`state.${state}`)}
        </Badge>,
      ]}
    >
      {held ? <p className="max-w-[62ch] text-sm text-ink">{t(held, { name })}</p> : null}
      {tag.engagement_id ? (
        <p>
          <StandaloneLink href={`/dev/engagements/${encodeURIComponent(tag.engagement_id)}`}>
            {t("tracker")}
          </StandaloneLink>
        </p>
      ) : null}
      {canWithdraw(tag) ? (
        <div className="mt-2">
          <WithdrawTag proposalId={ideaId} tagId={tag.id} orgName={name} returnFocusTo={PITCHES_HEADING} />
        </div>
      ) : null}
    </Row>
  );
}
