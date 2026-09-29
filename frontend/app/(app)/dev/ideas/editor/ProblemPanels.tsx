"use client";

import { useTranslations } from "next-intl";
import { useId, useState, type FormEvent, type ReactNode } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { SelectField } from "@/components/ui/SelectField";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { TextField } from "@/components/ui/TextField";

import type { searchProblems } from "../calls";
import { LIMITS, MAX_PROBLEMS, type NicheNode, type ProblemCard, type ProblemMode, type ProblemRef } from "../ideas";

export interface ProblemPanelsProps {
  mode: ProblemMode;
  linked: ProblemRef[];
  newTitle: string;
  newStatement: string;
  niches: NicheNode[];
  /** The newest published problems, rendered with the page. */
  initialResults: ProblemCard[];
  errors: { newTitle?: ReactNode; newStatement?: ReactNode };
  onMode: (mode: ProblemMode) => void;
  onLinked: (problems: ProblemRef[]) => void;
  onNewTitle: (value: string) => void;
  onNewStatement: (value: string) => void;
  searchImpl?: typeof searchProblems;
}

type Search = { kind: "idle" } | { kind: "busy" } | { kind: "failed" };

// Loaded with the first search, not with the page (docs/spec/07 item 5).
const loadSearch: typeof searchProblems = (filters) => import("../calls").then((m) => m.searchProblems(filters));

/**
 * The chosen way of naming the problem, loaded once a choice is made: link up to five published problems (GET
 * /api/problems, by words and niche) or describe a new one, which becomes a developer-reported problem when the idea
 * is published (AC-PROP-5).
 */
export function ProblemPanels(props: ProblemPanelsProps) {
  const { mode, linked, niches, errors, onMode, onLinked, searchImpl = loadSearch } = props;
  const t = useTranslations("ideaEditor");
  const f = useTranslations("ideaFields");
  const id = useId();
  const [q, setQ] = useState("");
  const [niche, setNiche] = useState("");
  const [results, setResults] = useState<ProblemCard[]>(props.initialResults);
  const [search, setSearch] = useState<Search>({ kind: "idle" });
  const [searched, setSearched] = useState(false);
  const linkedIds = new Set(linked.map((problem) => problem.id));
  const full = linked.length >= MAX_PROBLEMS;

  async function runSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (search.kind === "busy") return;
    setSearch({ kind: "busy" });
    const outcome = await searchImpl({ q, niche }).catch(() => ({ ok: false as const }));
    if (outcome.ok) {
      setResults(outcome.value.items);
      setSearched(true);
      setSearch({ kind: "idle" });
    } else {
      setSearch({ kind: "failed" });
    }
  }

  function link(problem: ProblemCard) {
    if (full || linkedIds.has(problem.id)) return;
    const { id: problemId, title, source, label, niche: problemNiche } = problem;
    onLinked([...linked, { id: problemId, title, source, label, niche: problemNiche }]);
  }

  return (
    <div className="flex flex-col gap-5">
      {mode === "pick" ? (
        <div className="flex flex-col gap-5">
          {linked.length > 0 ? (
            <section aria-labelledby={`${id}-linked`}>
              <h3 id={`${id}-linked`} className="flex flex-wrap items-baseline gap-x-3 font-semibold text-ink">
                {t("linkedLabel")}
                <span className="text-sm font-normal text-ink-soft tabular-nums">
                  {t("linkedCount", { count: linked.length, max: MAX_PROBLEMS })}
                </span>
              </h3>
              <ul className="mt-2 flex flex-col">
                {linked.map((problem) => (
                  <li
                    key={problem.id}
                    className="flex items-start justify-between gap-3 border-t border-line py-2 last:border-b"
                  >
                    <span className="min-w-0 pt-2.5 [overflow-wrap:anywhere]">
                      {problem.title}
                      {problem.source === "developer" ? (
                        <span className="ml-2 text-sm text-ink-soft">{f("developerReported")}</span>
                      ) : null}
                    </span>
                    <Button
                      variant="link"
                      className="shrink-0"
                      aria-label={t("unlinkName", { title: problem.title })}
                      onClick={() => onLinked(linked.filter((item) => item.id !== problem.id))}
                    >
                      {t("unlink")}
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <form role="search" onSubmit={runSearch} aria-label={t("searchLabel")} className="flex flex-col gap-3">
            <div className="grid gap-3 sm:grid-cols-[1fr_minmax(10rem,14rem)]">
              <TextField
                id={`${id}-q`}
                type="search"
                label={t("searchLabel")}
                value={q}
                maxLength={100}
                autoComplete="off"
                enterKeyHint="search"
                onChange={(event) => setQ(event.target.value)}
              />
              <SelectField
                id={`${id}-niche`}
                label={t("searchNiche")}
                value={niche}
                onChange={(event) => setNiche(event.target.value)}
              >
                <option value="">{t("searchNicheAll")}</option>
                {niches.map((parent) => (
                  <option key={parent.id} value={parent.slug}>
                    {parent.name}
                  </option>
                ))}
              </SelectField>
            </div>
            <div>
              <Button type="submit" variant="secondary" busy={search.kind === "busy"}>
                {search.kind === "busy" ? t("searching") : t("search")}
              </Button>
            </div>
          </form>

          {search.kind === "failed" ? <Alert>{t("searchFailed")}</Alert> : null}
          {full ? <p className="text-sm text-ink-soft">{t("maxProblems", { max: MAX_PROBLEMS })}</p> : null}

          {results.length > 0 ? (
            <ul aria-label={t("resultsLabel")} className="flex flex-col">
              {results.map((problem) => {
                const isLinked = linkedIds.has(problem.id);
                return (
                  <li key={problem.id} className="flex items-start justify-between gap-3 border-t border-line py-3">
                    <div className="min-w-0">
                      <p className="font-medium [overflow-wrap:anywhere] text-ink">{problem.title}</p>
                      <p className="flex flex-wrap gap-x-3 text-sm text-ink-soft">
                        {problem.niche ? <span>{problem.niche.label}</span> : null}
                        {problem.source === "developer" ? <span>{f("developerReported")}</span> : null}
                      </p>
                      <p className="mt-1 line-clamp-2 text-sm text-ink [overflow-wrap:anywhere]">{problem.statement}</p>
                    </div>
                    {isLinked || full ? null : (
                      <Button
                        variant="link"
                        className="shrink-0"
                        aria-label={t("linkName", { title: problem.title })}
                        onClick={() => link(problem)}
                      >
                        {t("link")}
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <div data-empty-state="" className="border-t border-line pt-4">
              <p className="text-ink">{searched ? t("noProblems") : t("noProblemsYet")}</p>
              <Button variant="link" onClick={() => onMode("new")}>
                {t("describeInstead")}
              </Button>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          <TextField
            id={`${id}-new-title`}
            label={f("newProblemTitle")}
            value={props.newTitle}
            maxLength={LIMITS["new_problem.title"]}
            error={errors.newTitle}
            onChange={(event) => props.onNewTitle(event.target.value)}
          />
          <TextAreaField
            id={`${id}-new-statement`}
            label={f("newProblemStatement")}
            value={props.newStatement}
            maxLength={LIMITS["new_problem.statement"]}
            error={errors.newStatement}
            onChange={(event) => props.onNewStatement(event.target.value)}
          />
        </div>
      )}
    </div>
  );
}
