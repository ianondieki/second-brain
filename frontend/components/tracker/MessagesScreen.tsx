import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { buttonClass } from "@/components/ui/Button";
import { LinkPending } from "@/components/ui/LinkPending";

import { engagementHistory, engagementThread } from "./data";
import { MessagesTab } from "./MessagesTab";
import { turnOf, type Detail } from "./model";
import { engagementHref, needsHistory, tabHref, TrackerHeader, TrackerSpine, TrackerTabs, TurnCard } from "./TrackerFrame";

/**
 * One engagement's Messages tab as its own route (/dev/engagements/[id]/messages, /org/engagements/[id]/messages;
 * REQ-ENG-11): the tracker's title, turn card, spine and tab bar, then the thread. The turn card's buttons stay on the
 * Tracker tab, which a link in the card opens: this route carries the thread's client code, never the tracker's
 * (docs/spec/07 item 5, 150 KB per route), and Send is its one primary action.
 */
export async function MessagesScreen({ detail, basePath, query = "" }: { detail: Detail; basePath: string; query?: string }) {
  const t = await getTranslations("tracker");
  const [history, read] = await Promise.all([
    needsHistory(detail) ? engagementHistory(detail.id) : null,
    engagementThread(detail.id),
  ]);
  const href = engagementHref(basePath, detail.id);
  const trackerHref = tabHref(href, query, "tracker");
  // The way to the turn card's buttons, only when the next step is the viewer's and the tab does not already show it
  // (a thread not open yet, or a refused read, ends in the same "Open the Tracker tab").
  const turn = turnOf(detail, detail.my_party);
  const yours = (turn.kind === "you" || turn.kind === "both") && read.kind === "open";
  return (
    <>
      <TrackerHeader detail={detail} basePath={basePath} query={query} />
      <TurnCard detail={detail}>
        {yours ? (
          <div>
            <Link href={trackerHref} data-to-tracker="" className={buttonClass("secondary", "no-underline")}>
              {t("messages.toTracker")}
              <LinkPending className="ml-2" />
            </Link>
          </div>
        ) : null}
      </TurnCard>
      <TrackerSpine detail={detail} history={history} />
      <TrackerTabs detail={detail} current="messages" basePath={basePath} query={query} />
      <div className="mt-6 flex max-w-3xl flex-col gap-10">
        <MessagesTab detail={detail} read={read} trackerHref={trackerHref} />
      </div>
    </>
  );
}
