import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";

import {
  COMMAND_SEGMENT,
  CONTACT_REVEALED_STATES,
  DUAL_ENDORSEMENT_STATES,
  HOLD_MAX_DAYS,
  MAIN_PATH_GROUP,
  MILESTONE_SEGMENT,
  MILESTONE_STEPS,
  PAUSED_STATES,
  QUESTION_MAX_CHARS,
  REASON_MAX_CHARS,
} from "./model";

// docs/spec/06 6.9: the state machine (backend/src/bridge/engagements/state_machine.py) is the only definition of the
// stages. The frozen API sends the current stage's group, not the table, so the tracker keeps three small copies; this
// test reads the Python source and fails as soon as a copy differs from it. The same goes for the contact-by limit in
// backend/config/policy.yaml that two messages state in words.

// The repository root, three levels above this file (frontend/components/tracker).
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const repo = (path: string) => join(ROOT, path);
const source = readFileSync(repo("backend/src/bridge/engagements/state_machine.py"), "utf-8");

/** The text of a top-level Python assignment `NAME: ... = <open> … <close>` (a dict or tuple literal). */
function block(name: string, open: "{" | "("): string {
  const start = source.search(new RegExp(`^${name}: Final[^=]*= [{(]`, "m"));
  expect(start, name).toBeGreaterThanOrEqual(0);
  const close = open === "{" ? "\n}\n" : "\n)\n";
  const end = source.indexOf(close, start);
  expect(end, name).toBeGreaterThan(start);
  return source.slice(start, end);
}

function backendStageGroups(): Record<string, string> {
  const groups: Record<string, string> = {};
  for (const m of block("STAGE_GROUPS", "{").matchAll(/S\.(\w+): "(\w+)"/g)) groups[m[1]] = m[2];
  return groups;
}

function backendMilestoneSteps(): Record<string, string[]> {
  const steps: Record<string, string[]> = {};
  const text = block("MILESTONE_STEPS", "{");
  for (const m of text.matchAll(/Command\.(\w+): \(\s*frozenset\(\{([^}]*)\}\)/g)) {
    steps[m[1].toLowerCase()] = [...m[2].matchAll(/MilestoneState\.(\w+)/g)].map((s) => s[1]).sort();
  }
  return steps;
}

function backendMainPath(): string[] {
  return [...block("MAIN_PATH", "(").matchAll(/S\.(\w+)/g)].map((m) => m[1]);
}

describe("the tracker's copies of the state machine", () => {
  it("group every main-path stage as STAGE_GROUPS does", () => {
    const backend = backendStageGroups();
    expect(Object.keys(backend).length).toBeGreaterThanOrEqual(14);
    expect(MAIN_PATH_GROUP).toEqual(backend);
  });

  it("start each milestone command from the states MILESTONE_STEPS allows", () => {
    const backend = backendMilestoneSteps();
    expect(Object.keys(backend).sort()).toEqual(
      ["accept_milestone", "request_changes", "start_milestone", "submit_milestone"],
    );
    const ours = Object.fromEntries(Object.entries(MILESTONE_STEPS).map(([k, v]) => [k, [...v].sort()]));
    expect(ours).toEqual(backend);
  });

  it("reveal contact details in CONTACT_REVEALED's stages: the main path from INTEREST_CONFIRMED on", () => {
    expect(source).toMatch(/^CONTACT_REVEALED: Final = frozenset\(MAIN_PATH\[MAIN_PATH\.index\(S\.INTEREST_CONFIRMED\) :\]\)$/m);
    const path = backendMainPath();
    expect([...CONTACT_REVEALED_STATES]).toEqual(path.slice(path.indexOf("INTEREST_CONFIRMED")));
  });

  it("show both parties' endorsement rows on docs/spec/06 6.9's dual-endorsement stages", () => {
    // Stages 0, 4, 5, 8, 11, 12 and TERMINATED; milestone acceptances and payment confirmations are per milestone.
    expect([...DUAL_ENDORSEMENT_STATES].sort()).toEqual(
      ["AGREEMENT_SIGNING", "CONTACT_MADE", "NDA_PENDING", "ORG_INTEREST", "PAYMENT_FINAL", "SIGN_OFF", "TERMINATED"],
    );
    // Each of them (TERMINATED comes after the prototype) is a state the backend endorses in.
    for (const state of DUAL_ENDORSEMENT_STATES) if (state !== "TERMINATED") expect(backendMainPath()).toContain(state);
  });
});

describe("the side states (REQ-ENG-10 part)", () => {
  it("keep the stage marked in RETURNING's states: those an engagement leaves only for the stage it came from", () => {
    const line = /^RETURNING: Final = frozenset\(\{([^}]*)\}\)$/m.exec(source);
    expect(line, "RETURNING").not.toBeNull();
    const returning = [...line![1].matchAll(/S\.(\w+)/g)].map((m) => m[1]).sort();
    expect([...PAUSED_STATES].sort()).toEqual(returning);
  });

  it("build a request for every command of the table", () => {
    const start = source.indexOf("class Command(StrEnum):");
    const body = source.slice(start, source.indexOf("\n\n\n", start));
    const commands = [...body.matchAll(/^ {4}\w+ = "(\w+)"$/gm)].map((m) => m[1]).sort();
    expect(commands.length).toBeGreaterThanOrEqual(28);
    expect([...Object.keys(COMMAND_SEGMENT), ...Object.keys(MILESTONE_SEGMENT)].sort()).toEqual(commands);
  });

  it("limit questions, answers and reasons as QUESTION_MAX_CHARS and REASON_MAX_CHARS do", () => {
    expect(Number(/^QUESTION_MAX_CHARS: Final = (\d+)$/m.exec(source)?.[1])).toBe(QUESTION_MAX_CHARS);
    expect(Number(/^REASON_MAX_CHARS: Final = (\d+)$/m.exec(source)?.[1])).toBe(REASON_MAX_CHARS);
  });
});

describe("policy the copy states in words", () => {
  const policy = readFileSync(repo("backend/config/policy.yaml"), "utf-8");
  const days = Number(/^\s*contact_by_max_bd:\s*(\d+)\s*$/m.exec(policy)?.[1]);
  const EN = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
  const SW = ["", "moja", "mbili", "tatu", "nne", "tano", "sita", "saba", "nane", "tisa", "kumi"];

  it("name contact_by_max_bd business days in both languages", () => {
    expect(days).toBeGreaterThan(0);
    expect(en.trackerActions.approve.byHint).toContain(`${EN[days]} business days`);
    expect(en.trackerActions.refusal.invalidContactBy).toContain(`${EN[days]} business days`);
    expect(sw.trackerActions.approve.byHint).toContain(`siku ${SW[days]} za kazi`);
    expect(sw.trackerActions.refusal.invalidContactBy).toContain(`siku ${SW[days]} za kazi`);
  });

  /** A number under a policy.yaml section ("on_hold" → "max_days"). */
  function setting(section: string, key: string): number {
    const at = policy.search(new RegExp(`^${section}:\\s*$`, "m"));
    expect(at, section).toBeGreaterThanOrEqual(0);
    const rest = policy.slice(at);
    const end = rest.slice(1).search(/^\S/m);
    const value = new RegExp(`^\\s+${key}:\\s*(\\d+)\\s*$`, "m").exec(end > 0 ? rest.slice(0, end + 1) : rest)?.[1];
    expect(value, `${section}.${key}`).toBeDefined();
    return Number(value);
  }

  it("name a hold's longest date and the engagement's days on hold (on_hold) in both languages", () => {
    const most = setting("on_hold", "max_days");
    const total = setting("on_hold", "hold_days_total");
    expect(HOLD_MAX_DAYS).toBe(most);
    expect(en.trackerActions.sheet.pause.dateHint).toContain(`at most ${most} days ahead`);
    expect(en.trackerActions.sheet.pause.dateHint).toContain(`together may last ${total} days`);
    expect(en.trackerActions.refusal.invalidResumeAt).toContain(`${most} days ahead`);
    expect(en.trackerActions.refusal.holdLimit).toContain(`${total} days`);
    expect(sw.trackerActions.sheet.pause.dateHint).toContain(`isizidi siku ${most} mbele`);
    expect(sw.trackerActions.sheet.pause.dateHint).toContain(`visizidi siku ${total}`);
    expect(sw.trackerActions.refusal.invalidResumeAt).toContain(`siku ${most} mbele`);
    expect(sw.trackerActions.refusal.holdLimit).toContain(`siku ${total}`);
  });

  it("name the questions a stage allows and the days to answer one (info_requested) in both languages", () => {
    const questions = setting("info_requested", "info_requests_per_stage");
    const answerBd = setting("info_requested", "expire_bd");
    expect(en.trackerActions.sheet.requestInfo.limit).toContain(`${EN[questions]} questions`);
    expect(en.trackerActions.sheet.cancelRequest.body).toContain(`the ${EN[questions]} this stage allows`);
    expect(en.trackerActions.sheet.requestInfo.lead).toContain(`${EN[answerBd]} business days`);
    const SW_PLURAL = ["", "moja", "mawili", "matatu", "manne", "matano"];
    expect(sw.trackerActions.sheet.requestInfo.limit).toContain(`maswali ${SW_PLURAL[questions]}`);
    expect(sw.trackerActions.sheet.cancelRequest.body).toContain(`katika ${SW_PLURAL[questions]} yanayoruhusiwa`);
    expect(sw.trackerActions.sheet.requestInfo.lead).toContain(`siku ${SW[answerBd]} za kazi`);
  });
});
