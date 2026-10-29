import { getTranslations } from "next-intl/server";

import { ButtonLink } from "@/components/ui/ButtonLink";
import { Section } from "@/components/ui/Section";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

import { Marks } from "./Marks";
import { outcomes, QUIZ_PATH, type QuizCardState } from "./quiz";

/**
 * Home's "Today's five" (REQ-DEV-01; D-59): one flat card, drawn on the server with no script of its own. Not played:
 * one sentence and "Play" (the card's action, a secondary link: Home keeps its one primary action). Played: the score
 * as a figure, the streak and "See why". A day without a set: one sentence and nothing to do. When the read failed
 * the card is left out (the state is null), never the error page.
 */
export async function QuizCard({ state }: { state: QuizCardState }) {
  if (!state) return null;
  const t = await getTranslations("quiz");
  const attempt = state.kind === "set" ? state.today.attempt : null;

  let body;
  if (state.kind === "none") {
    body = <p className="text-ink" data-quiz-card="none">{t("card.none")}</p>;
  } else if (!attempt) {
    body = (
      <>
        <p className="max-w-[52ch] text-ink" data-quiz-card="play">
          {t("card.lead")}
        </p>
        <ButtonLink href={QUIZ_PATH} className="shrink-0">
          {t("card.play")}
        </ButtonLink>
      </>
    );
  } else {
    body = (
      <>
        <div className="flex flex-col gap-2" data-quiz-card="played">
          <p className="text-ink">
            {t.rich("card.played", {
              score: attempt.score,
              total: attempt.out_of,
              streak: state.today.streak.current,
              fig: (chunks) => <span className="mr-1 font-figure text-2xl font-[680] tracking-[-0.02em] tabular-nums">{chunks}</span>,
            })}
          </p>
          <Marks marks={outcomes(state.today, attempt)} />
        </div>
        <StandaloneLink href={`${QUIZ_PATH}#quiz-results`} className="shrink-0">
          {t("card.seeWhy")}
        </StandaloneLink>
      </>
    );
  }

  return (
    <Section title={t("title")} headingId="home-quiz" data-home="quiz">
      <div className="flex flex-col items-start gap-4 rounded-panel border border-line bg-field p-5 sm:flex-row sm:items-center sm:justify-between sm:gap-8 sm:p-6">
        {body}
      </div>
    </Section>
  );
}
