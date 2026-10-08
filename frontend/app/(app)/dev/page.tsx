import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { getActivity } from "@/components/activity/fetch";
import { myEngagements } from "@/components/tracker/data";
import { appNow, requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { publicActivity } from "@/lib/public/public-data";

import { recommendations } from "./discover/data";
import { recommendationsState } from "./discover/recommendations";
import { HomeContent } from "./HomeContent";
import { myIdeas } from "./ideas/data";
import { quizCard } from "./quiz/data";
import { homePeers } from "./teams/data";
import { weekStrip } from "./week/data";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("home");
  return { title: t("devPageTitle") };
}

/**
 * A read for below the first screen, started now and awaited by HomeContent's boundary. Each one answers null on a
 * failure; the one thing it throws (a redirect, the session ended) is handled there, so it is marked handled here and
 * never reaches the process as an unhandled rejection while the shell renders.
 */
function started<T>(read: Promise<T>): Promise<T> {
  read.catch(() => undefined);
  return read;
}

/**
 * Developer Home. The first screen's reads (the stat tiles: the engagements and the ideas) come first, together; the
 * rest start once those have answered, so they do not queue ahead of them at the API, and HomeContent streams them in
 * below the tiles (P25: the greeting, the LCP element, no longer waits for data shown further down).
 */
export default async function DeveloperHome() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const [engagements, ideas] = await Promise.all([myEngagements(), myIdeas()]);
  return (
    <HomeContent
      me={me}
      engagements={engagements}
      ideas={ideas}
      recommended={started(recommendations().then(recommendationsState))}
      quiz={started(quizCard())}
      week={started(weekStrip())}
      peers={started(homePeers())}
      now={appNow()}
      activity={started(publicActivity())}
      mine={started(getActivity())}
    />
  );
}
