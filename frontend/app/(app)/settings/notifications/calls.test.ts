import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";

import { saveChoices } from "./calls";

// REQ-CON-01: the save call sends the decisions as given and settles every answer into the page's outcomes.

function client(answer: () => Promise<{ data?: unknown; error?: unknown; response: Response }>) {
  const PUT = vi.fn(answer);
  return { client: { PUT } as unknown as ApiClient, PUT };
}

const body = { reminders: { granted: false, version: "2026-09-29.2" } };

describe("saveChoices", () => {
  it("PUTs the decisions to /api/me/consents and answers the recorded consents", async () => {
    const items = [{ purpose: "reminders", granted: false, text: "t", version: "2026-09-29.2" }];
    const { client: api, PUT } = client(async () => ({ data: items, response: new Response(null, { status: 200 }) }));
    expect(await saveChoices(body, api)).toEqual({ ok: true, items });
    expect(PUT).toHaveBeenCalledWith("/api/me/consents", { body });
  });

  it("settles a 409 on changed wording as 'changed'", async () => {
    const { client: api } = client(async () => ({
      error: { detail: { code: "consent_text_changed", message: "The consent wording has changed." } },
      response: new Response(null, { status: 409 }),
    }));
    expect(await saveChoices(body, api)).toEqual({ ok: false, refusal: "changed" });
  });

  it("settles a thrown fetch as 'network'", async () => {
    const { client: api } = client(() => Promise.reject(new TypeError("Failed to fetch")));
    expect(await saveChoices(body, api)).toEqual({ ok: false, refusal: "network" });
  });
});
