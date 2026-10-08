import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHero } from "@/components/ui/PageHero";
import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { quizToday } from "./data";
import { BOARD_PATH, topicLabel } from "./quiz";
import { QuizPlay } from "./QuizPlay";
import { QuizResults } from "./QuizResults";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("quiz");
  return { title: t("pageTitle") };
}

/**
 * Developer › Today's five (REQ-DEV-01; D-59): today's approved set to play, or once played its results with why,
 * sources and flags. Reached from Home's card (no nav item of its own: the developer nav stays at five, principle 6).
 * Developers only; organisations go to their own home, as from every developer route.
 */
export default async function QuizPage() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("quiz");
  const te = await getTranslations("eyebrow");
  const state = await quizToday();

  let content;
  if (state.kind === "none") {
    content = <EmptyState sentence={t("none")} action={t("noneAction")} href={BOARD_PATH} />;
  } else if (state.today.attempt) {
    content = <QuizResults today={state.today} attempt={state.today.attempt} />;
  } else {
    const questions = [...state.today.questions]
      .sort((a, b) => a.position - b.position)
      .map(({ id, position, prompt, options, topic }) => ({ id, position, prompt, options, topic: topicLabel(t, topic) }));
    content = (
      <ClientStrings strings={await clientStrings(["quizPlay"])}>
        <QuizPlay setId={state.today.set_id} questions={questions} />
      </ClientStrings>
    );
  }

  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <div className="flex max-w-3xl flex-col gap-8">
        <PageHero eyebrow={te("quiz")} back={{ href: "/dev", label: t("back") }} title={t("title")} lead={t("lead")} />
        {content}
      </div>
    </SignedInShell>
  );
}
