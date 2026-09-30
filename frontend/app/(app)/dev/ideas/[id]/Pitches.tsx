import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";
import type { ComponentType, SVGProps } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { ClockIcon, ClosedIcon, SendIcon } from "@/components/ui/icons";
import { EmptyState } from "@/components/ui/EmptyState";
import { clientStrings } from "@/lib/i18n/client-strings";

import { formatDay } from "../dates";
import type { IdeaStatus } from "../status";
import { canWithdraw, heldKey, pitchesLeft, pitchHref, tagState, type MyTags, type TagOut, type TagState } from "./pitch/picker";
import { WithdrawTag } from "./WithdrawTag";

export const PITCHES_HEADING = "pitches-heading";

const LOOK: Record<TagState, { Icon: ComponentType<SVGProps<SVGSVGElement>>; tone: string }> = {
  sent: { Icon: SendIcon, tone: "text-ok" },
  saved: { Icon: ClockIcon, tone: "text-jacaranda" },
  withdrawn: { Icon: ClosedIcon, tone: "text-ink-soft" },
  closed: { Icon: ClosedIcon, tone: "text-ink-soft" },
};

export interface PitchesProps {
  ideaId: string;
  status: IdeaStatus;
  /** Null when the tags could not be read now. */
  tags: MyTags | null;
}

/**
 * The idea's pitches (REQ-PROP-03, REQ-DIR-04): the plan's cap as "N of M left", then each organisation it was pitched
 * to with the pitch's state as icon + words + colour (sent, saved until they verify, withdrawn, closed), the held
 * sentence of docs/spec/06 6.2 while it waits, and Withdraw for a saved one. The state is the card's one chip.
 */
export async function Pitches({ ideaId, status, tags }: PitchesProps) {
  const t = await getTranslations("ideaPitches");
  const locale = await getLocale();
  const heading = (
    <h2 id={PITCHES_HEADING} tabIndex={-1} className="text-lg text-ink focus:outline-none">
      {t("title")}
    </h2>
  );
  if (!tags) {
    return (
      <section aria-labelledby={PITCHES_HEADING} className="mt-10">
        {heading}
        <p className="mt-2 text-ink">{t("loadFailed")}</p>
      </section>
    );
  }
  const left = pitchesLeft(tags.cap);
  const pitchable = status === "published" && left !== 0;
  const withdrawable = tags.items.some(canWithdraw);
  const list = (
    <ul aria-label={t("listLabel")} className="mt-4 border-b border-line">
      {tags.items.map((tag) => (
        <PitchRow key={tag.id} tag={tag} ideaId={ideaId} locale={locale} t={t} />
      ))}
    </ul>
  );
  return (
    <section aria-labelledby={PITCHES_HEADING} className="mt-10">
      {heading}
      <p className="mt-1 text-sm text-ink-soft" data-cap="">
        {left === null
          ? t("capUnlimited")
          : left === 0
            ? t("capUsed", { limit: tags.cap.limit ?? 0 })
            : t("capLeft", { count: left, limit: tags.cap.limit ?? 0 })}
      </p>
      {status !== "published" ? <p className="mt-3 text-ink">{t(`blocked.${status}`)}</p> : null}
      {tags.items.length === 0 ? (
        pitchable ? (
          <EmptyState className="mt-4" sentence={t("empty")} action={t("pitch")} href={pitchHref(ideaId)} />
        ) : null
      ) : withdrawable ? (
        <ClientStrings strings={await clientStrings(["tagWithdraw"])}>{list}</ClientStrings>
      ) : (
        list
      )}
    </section>
  );
}

type Translate = Awaited<ReturnType<typeof getTranslations<"ideaPitches">>>;

function PitchRow({ tag, ideaId, locale, t }: { tag: TagOut; ideaId: string; locale: string; t: Translate }) {
  const state = tagState(tag);
  const { Icon, tone } = LOOK[state];
  const name = tag.org?.name ?? t("orgUnlisted");
  const held = state === "saved" ? heldKey(tag.status) : null;
  return (
    <li className="flex flex-col gap-1 border-t border-line py-4" data-tag={tag.id}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h3 className="min-w-0 text-base font-semibold [overflow-wrap:anywhere] text-ink">
          {tag.org ? (
            <Link
              href={`/dev/companies/${encodeURIComponent(tag.org.id)}`}
              className="-my-2 inline-flex min-h-11 items-center py-2 underline decoration-line decoration-1 underline-offset-4 hover:decoration-jacaranda"
            >
              {name}
            </Link>
          ) : (
            name
          )}
        </h3>
        <span data-status={state} className={cn("inline-flex items-center gap-1.5 text-sm font-medium", tone)}>
          <Icon className="size-5 shrink-0" />
          {t(`state.${state}`)}
        </span>
      </div>
      <p className="text-sm text-ink-soft">{t("pitchedOn", { date: formatDay(locale, tag.created_at) })}</p>
      {held ? <p className="max-w-[62ch] text-sm text-ink">{t(held, { name })}</p> : null}
      {tag.engagement_id ? (
        <Link href={`/dev/engagements/${encodeURIComponent(tag.engagement_id)}`} className={standaloneLinkClass}>
          {t("tracker")}
        </Link>
      ) : null}
      {canWithdraw(tag) ? (
        <div className="mt-2">
          <WithdrawTag proposalId={ideaId} tagId={tag.id} orgName={name} returnFocusTo={PITCHES_HEADING} />
        </div>
      ) : null}
    </li>
  );
}
