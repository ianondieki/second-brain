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

/** Developer Home: the reads (together, not one after the other), then HomeContent draws them. */
export default async function DeveloperHome() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const [engagements, ideas, recommended, quiz, week, peers, activity, mine] = await Promise.all([
    myEngagements(),
    myIdeas(),
    recommendations(),
    quizCard(),
    weekStrip(),
    homePeers(),
    publicActivity(),
    getActivity(),
  ]);
  return (
    <HomeContent
      me={me}
      engagements={engagements}
      ideas={ideas}
      recommended={recommendationsState(recommended)}
      quiz={quiz}
      week={week}
      peers={peers}
      now={appNow()}
      activity={activity}
      mine={mine}
    />
  );
}
