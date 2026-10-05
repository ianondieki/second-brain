import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { safeHttpsUrl } from "@/components/problem/problem";
import { Badge } from "@/components/ui/Badge";
import { standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { StandaloneLink } from "@/components/ui/StandaloneLink";
import { AlertIcon, CheckIcon, ClosedIcon } from "@/components/ui/icons";
import { clientStrings } from "@/lib/i18n/client-strings";

import { FlagQuestion } from "./FlagQuestion";
import { Marks } from "./Marks";
import {
  BOARD_PATH,
  optionMark,
  outcomes,
  QUESTIONS,
  questionOutcome,
  topicLabel,
  type QuizAttempt,
  type QuizToday,
} from "./quiz";

/**
 * The results of today's five (REQ-DEV-01), drawn on the server once the developer has played: the score as a figure
 * with the five marks and the streak (the raised summary), then each question with the chosen and the right option
 * marked (an icon and words, never colour alone), "Why?" with its reason, the official page it comes from (a new
 * tab) and "Flag". A withdrawn question says it counts for nobody and cannot be flagged. The heading takes focus once
 * the answers are checked (QuizPlay) and is where Home's "See why" lands.
 */
export async function QuizResults({ today, attempt }: { today: QuizToday; attempt: QuizAttempt }) {
  const t = await getTranslations("quiz");
  const questions = [...today.questions].sort((a, b) => a.position - b.position);
  const strings = await clientStrings(["quizPlay"]);

  return (
    <section aria-labelledby="quiz-results" className="flex flex-col gap-10">
      <div className="rounded-panel border border-line bg-field p-5 shadow-card sm:p-6" data-quiz-summary="">
        <h2 id="quiz-results" tabIndex={-1} className="scroll-mt-24 text-xl text-ink focus:outline-none">
          {t("results.heading")}
        </h2>
        <p className="mt-4 text-lg text-ink" data-quiz-score="">
          {t.rich("results.score", {
            score: attempt.score,
            total: attempt.out_of,
            fig: (chunks) => (
              <span className="mr-1 font-display text-3xl font-[680] tracking-[-0.02em] tabular-nums">{chunks}</span>
            ),
          })}
        </p>
        <Marks marks={outcomes(today, attempt)} className="mt-3" />
        <p className="mt-4 text-ink" data-quiz-streak="">
          {t("results.streak", { current: today.streak.current, best: today.streak.best })}
        </p>
        <p className="text-ink-soft">{t("results.tomorrow")}</p>
        <StandaloneLink href={BOARD_PATH} className="mt-2">
          {t("results.board")}
        </StandaloneLink>
      </div>

      <ClientStrings strings={strings}>
        <ol aria-label={t("results.listLabel")} className="flex flex-col divide-y divide-line rounded-panel border border-line bg-field">
          {questions.map((question, index) => {
            const chosen = attempt.answers[index] ?? null;
            const outcome = questionOutcome(question, attempt, index);
            const href = safeHttpsUrl(question.source.url);
            const promptId = `result-${question.position}`;
            return (
              <li key={question.id} data-result={question.position} data-outcome={outcome} className="px-4 py-6 sm:px-6">
                <article aria-labelledby={promptId} className="flex flex-col gap-3">
                  <p className="flex flex-wrap gap-x-3 text-sm text-ink-soft">
                    <span>{t("results.position", { number: question.position, total: QUESTIONS })}</span>
                    <span className="[overflow-wrap:anywhere]">{topicLabel(t, question.topic)}</span>
                  </p>
                  <h3 id={promptId} className="text-lg font-semibold [overflow-wrap:anywhere] text-ink">
                    {question.prompt}
                  </h3>
                  <ul className="flex flex-col gap-2">
                    {question.options.map((text, option) => {
                      const mark = outcome === "pulled" ? null : optionMark(option, question.answer, chosen);
                      return (
                        <li
                          key={option}
                          data-mark={mark ?? undefined}
                          className={cn(
                            "flex flex-col gap-2 rounded-control border px-4 py-3 sm:flex-row sm:items-center sm:justify-between",
                            mark === "rightChosen" || mark === "right" ? "border-ok-line bg-ok-wash" : "border-line",
                            mark === "wrongChosen" && "border-error-line bg-error-wash",
                          )}
                        >
                          <span className="[overflow-wrap:anywhere] text-ink">{text}</span>
                          {mark ? (
                            <Badge
                              tone={mark === "wrongChosen" ? "error" : "ok"}
                              icon={mark === "wrongChosen" ? <AlertIcon /> : <CheckIcon />}
                              className="shrink-0 self-start sm:self-auto"
                            >
                              {t(`results.mark.${mark}`)}
                            </Badge>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                  {outcome === "skipped" ? <p className="text-sm text-ink-soft">{t("results.skipped")}</p> : null}
                  {outcome === "pulled" ? (
                    <p className="inline-flex items-start gap-2 text-sm text-ink-soft">
                      <ClosedIcon className="mt-0.5 size-4 shrink-0" />
                      {t("results.pulled")}
                    </p>
                  ) : null}
                  {question.why ? (
                    <div className="mt-1 max-w-[68ch]">
                      <p className="font-semibold text-ink">{t("results.why")}</p>
                      <p className="mt-1 text-ink" data-why="">
                        {question.why}
                      </p>
                    </div>
                  ) : null}
                  {href ? (
                    <p className="text-sm">
                      <a href={href} target="_blank" rel="noopener noreferrer" className={cn(standaloneLinkClass, "[overflow-wrap:anywhere]")} data-source="">
                        {t("results.source", { title: question.source.title })}
                        <span className="sr-only"> {t("results.newTab")}</span>
                      </a>
                    </p>
                  ) : null}
                  {outcome === "pulled" ? null : <FlagQuestion questionId={question.id} number={question.position} />}
                </article>
              </li>
            );
          })}
        </ol>
      </ClientStrings>
    </section>
  );
}
