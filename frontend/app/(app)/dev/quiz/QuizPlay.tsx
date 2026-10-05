"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { RadioGroup } from "@/components/ui/RadioGroup";

import { quizCalls, type QuizCalls } from "./calls";
import { Marks } from "./Marks";
import { answeredCount, QUESTIONS, type FinishProblem, type QuizQuestion } from "./quiz";

export type PlayQuestion = Pick<QuizQuestion, "id" | "position" | "prompt" | "options" | "topic">;

export interface QuizPlayProps {
  setId: string;
  questions: readonly PlayQuestion[];
  /** The results heading the server draws once the answers are in; focus moves there. */
  resultsId?: string;
  calls?: QuizCalls;
}

const OPTION_VALUES = ["0", "1", "2", "3"] as const;

/**
 * The five questions on one page (REQ-DEV-01): each a radio group (its prompt the legend, its position and topic as a
 * plain line above), then "Check answers", the screen's one primary action, which ignores presses until all five are
 * answered (pressing it then takes focus to the first unanswered question); once something is answered, "Check 2, skip
 * 3" sends what is answered, the rest as skipped. The time from the page opening to the check is sent and shown nowhere. Once the API has the
 * answers the page is fetched again (the server draws the results) and focus moves to the results heading. A day that
 * ended meanwhile, or a day without a set, is one sentence and the way Home in place of the form.
 */
export function QuizPlay({ setId, questions, resultsId = "quiz-results", calls: given }: QuizPlayProps) {
  const t = useStrings("quizPlay");
  const router = useRouter();
  const calls = useRef(given ?? quizCalls()).current;
  const [chosen, setChosen] = useState<(number | null)[]>(() => Array.from({ length: QUESTIONS }, () => null));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Exclude<FinishProblem, "played" | "closed" | "noQuiz"> | null>(null);
  const [ended, setEnded] = useState<"closed" | "noQuiz" | null>(null);
  const [refreshing, startRefresh] = useTransition();
  const started = useRef(0);
  const finished = useRef(false);
  const notice = useRef<HTMLDivElement>(null);

  useEffect(() => {
    started.current = performance.now();
    return () => {
      // Runs once the refreshed page has drawn the results in this form's place.
      if (finished.current) document.getElementById(resultsId)?.focus();
    };
  }, [resultsId]);

  useEffect(() => {
    if (problem || ended) notice.current?.focus();
  }, [problem, ended]);

  const answered = answeredCount(chosen);
  const complete = answered === QUESTIONS;
  const working = busy || refreshing;

  async function send() {
    if (working) return;
    setBusy(true);
    setProblem(null);
    const outcome = await calls.finish(setId, chosen, performance.now() - started.current);
    setBusy(false);
    if (outcome.ok || outcome.problem === "played") {
      finished.current = true;
      startRefresh(() => router.refresh());
      return;
    }
    if (outcome.problem === "closed" || outcome.problem === "noQuiz") setEnded(outcome.problem);
    else setProblem(outcome.problem);
  }

  function check(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!complete) {
      const first = chosen.findIndex((value) => value === null);
      document.querySelector<HTMLInputElement>(`input[name="q${questions[first]?.position}"]`)?.focus();
      return;
    }
    void send();
  }

  if (ended) {
    return (
      <Alert tone="info" ref={notice}>
        <p data-quiz-ended={ended}>{t(`problem.${ended}`)}</p>
        <Link href="/dev" className={standaloneLinkClass}>
          {t("home")}
        </Link>
      </Alert>
    );
  }

  return (
    <form noValidate onSubmit={check} aria-busy={working || undefined} data-quiz-play="">
      <ol className="flex flex-col divide-y divide-line rounded-panel border border-line bg-field shadow-card">
        {questions.map((question, index) => (
          <li key={question.id} data-question={question.position} className="flex flex-col gap-1 px-4 py-6 sm:px-6">
            <p className="flex flex-wrap gap-x-3 text-sm text-ink-soft">
              <span>{t("position", { number: question.position, total: QUESTIONS })}</span>
              <span className="[overflow-wrap:anywhere]">{question.topic}</span>
            </p>
            <RadioGroup
              id={`q-${question.position}`}
              name={`q${question.position}`}
              legend={<span className="block text-lg font-semibold [overflow-wrap:anywhere]">{question.prompt}</span>}
              options={question.options.map((text, option) => ({ value: OPTION_VALUES[option], label: text }))}
              value={chosen[index] === null ? null : OPTION_VALUES[chosen[index]]}
              onChange={(value) => setChosen((list) => list.map((old, i) => (i === index ? Number(value) : old)))}
            />
          </li>
        ))}
      </ol>

      {problem ? (
        <Alert ref={notice} className="mt-6">
          <p data-quiz-problem={problem}>{t(`problem.${problem}`)}</p>
        </Alert>
      ) : null}

      <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-col gap-2">
          <p className="text-sm text-ink-soft tabular-nums" data-quiz-progress="">
            {t("progress", { count: answered, total: QUESTIONS })}
          </p>
          <Marks marks={chosen.map((value) => (value === null ? "open" : "done"))} />
        </div>
        <div className="flex flex-col gap-3 sm:flex-row-reverse sm:items-center">
          <Button
            type="submit"
            variant="primary"
            busy={working}
            aria-disabled={working || !complete || undefined}
            aria-describedby={complete ? undefined : "quiz-check-hint"}
          >
            {working ? t("checking") : t("check")}
          </Button>
          {answered > 0 && !complete ? (
            <Button variant="link" busy={working} onClick={() => void send()} data-quiz-skip="">
              {t("skip", { count: answered, number: QUESTIONS - answered })}
            </Button>
          ) : null}
        </div>
      </div>
      {complete ? null : (
        <p id="quiz-check-hint" className="mt-3 text-sm text-ink-soft sm:text-right">
          {answered > 0 ? t("checkHint") : t("checkHintNone")}
        </p>
      )}
    </form>
  );
}
