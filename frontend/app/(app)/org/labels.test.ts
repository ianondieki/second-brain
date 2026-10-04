import { describe, expect, it } from "vitest";

import en from "@/locales/en.json";

import { stageKey } from "./labels";

// The Inbox's stage chip (/org Home and /org/inbox) names a side state as the tracker labels it (REQ-ENG-10 part),
// never "In progress" for a hold nor another wording for an open question.
describe("the Inbox's stage labels", () => {
  const label = (state: Parameters<typeof stageKey>[0]) => {
    const [, key] = stageKey(state).split(".");
    return en.inbox.stage[key as keyof typeof en.inbox.stage];
  };

  it("say an open question and a hold as the tracker does", () => {
    expect(label("INFO_REQUESTED")).toBe("Information requested");
    expect(label("ON_HOLD")).toBe("On hold");
  });

  it("keep In progress for the other open stages", () => {
    expect(label("NEGOTIATION")).toBe("In progress");
  });
});
