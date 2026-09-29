import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";

import { CONTACT_REVEALED_STATES, DUAL_ENDORSEMENT_STATES, MAIN_PATH_GROUP, MILESTONE_STEPS } from "./model";

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
});
