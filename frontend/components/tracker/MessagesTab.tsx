import { getLocale, getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { Section } from "@/components/ui/Section";
import { InfoIcon } from "@/components/ui/status-icons";
import { clientStrings } from "@/lib/i18n/client-strings";

import type { ThreadRead } from "./data";
import { Thread } from "./messages/Thread";
import { nairobiToday } from "./input";
import type { Detail } from "./model";

/**
 * The tracker's Messages tab (REQ-ENG-11, AC-TRACK-9; docs/spec/06 6.9, docs/spec/07 item 1: Tracker · Documents ·
 * Messages · History). Before INTEREST_CONFIRMED one sentence says when the thread opens, and nothing else (the
 * organisation cannot read it then). Open, the thread and its composer. After the end, or for
 * a member whose role cannot write, the thread stays readable and a sentence stands where the composer would be.
 */
export async function MessagesTab({ detail, read }: { detail: Detail; read: ThreadRead }) {
  const t = await getTranslations("tracker");
  const developer = detail.my_party === "developer";
  if (!read.open) {
    return (
      <Section title={t("messages.title")} headingId="messages-heading" data-thread-state="not_open">
        <p className="max-w-[60ch] text-ink" data-thread-closed="not_open">
          {developer ? t("messages.notOpenDev", { org: detail.org_name }) : t("messages.notOpenOrg")}
        </p>
      </Section>
    );
  }
  const { thread } = read;
  const locale = await getLocale();
  const closed = thread.status === "read_only";
  const note = closed ? t("messages.readOnly") : thread.can_post ? null : t("messages.viewer");
  return (
    <Section
      title={t("messages.title")}
      headingId="messages-heading"
      description={
        thread.can_post
          ? developer
            ? t("messages.leadDev", { org: detail.org_name })
            : t("messages.leadOrg", { name: detail.developer_name })
          : undefined
      }
      data-thread-state={thread.status}
    >
      <ClientStrings strings={await clientStrings(["trackerMessages"])}>
        <Thread
          engagementId={detail.id}
          initial={thread}
          today={detail.today ?? nairobiToday()}
          locale={locale}
          orgName={detail.org_name}
          empty={closed || !thread.can_post ? t("messages.emptyClosed") : t("messages.empty")}
        />
      </ClientStrings>
      {note ? (
        <p className="mt-6 flex max-w-[65ch] items-start gap-2 text-ink" data-thread-closed={closed ? "read_only" : "viewer"}>
          <InfoIcon className="mt-0.5 size-5 shrink-0 text-accent" />
          <span>{note}</span>
        </p>
      ) : null}
    </Section>
  );
}
