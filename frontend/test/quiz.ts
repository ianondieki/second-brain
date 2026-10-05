import type { QuizAttempt, QuizBoard, QuizToday } from "@/app/(app)/dev/quiz/quiz";

// Test fixtures for Today's five (REQ-DEV-01): the demo's set as the API sends it, before and after playing.

const PROMPTS = [
  "How many spaces per indentation level does PEP 8 recommend for Python code?",
  "In Kubernetes, what are the smallest deployable units of computing that you can create and manage?",
  "Which HTTP method does a browser use for a CORS preflight request?",
  "Which defence does the OWASP SQL Injection Prevention Cheat Sheet list first among its primary defences?",
  "Under Rust's ownership rules, how many owners can a value have at one time?",
];
const ANSWERS = [2, 1, 2, 1, 0];

export function quizToday({ played = false, answers = [2, 0, 2, null, 0] as (number | null)[], pulled = -1 } = {}): QuizToday {
  const correct = answers.map((a, i) => (i === pulled ? null : a === ANSWERS[i]));
  const score = correct.filter(Boolean).length;
  const attempt: QuizAttempt | null = played
    ? { answers, correct, score, out_of: pulled >= 0 ? 4 : 5, finished_at: "2026-10-05T07:00:00Z", time_ms: 81_000 }
    : null;
  return {
    set_id: "01a0f100-0000-7000-8000-000000000001",
    quiz_date: "2026-10-05",
    questions: PROMPTS.map((prompt, i) => ({
      id: `01a0f100-0000-7000-8000-00000000001${i}`,
      position: i + 1,
      prompt,
      options: ["A one", "B two", "C three", "D four"].map((o) => `${o} ${i + 1}`),
      topic: `Topic ${i + 1}`,
      pulled: i === pulled,
      answer: played ? ANSWERS[i] : null,
      why: played ? `Because of reason ${i + 1}.` : null,
      source: { id: `src-${i}`, title: `Official page ${i + 1}`, url: i === 4 ? "javascript:alert(1)" : `https://docs.example.org/${i}` },
    })),
    attempt,
    streak: { current: 2, best: 5 },
    leaderboard_opt_in: false,
  };
}

export function board(me: Partial<QuizBoard["me"]> = {}, rows: QuizBoard["rows"] = []): QuizBoard {
  return {
    week_start: "2026-10-05",
    week_end: "2026-10-11",
    rows,
    me: { points: 12, rank: 4, opted_in: true, played: true, ...me },
  };
}
