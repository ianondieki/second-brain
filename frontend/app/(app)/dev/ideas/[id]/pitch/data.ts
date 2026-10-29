import { redirect } from "next/navigation";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import {
  isOrgId,
  MAX_BATCH,
  orgKey,
  pickerApiQuery,
  type MyTags,
  type PickerQuery,
  type PitchOption,
  type PitchPicker,
  type ProposalViews,
} from "./picker";

// Server-side calls for pitching and "Who has seen this" (signed in, owner only). Each call is bounded, so a hung API
// ends in the route's error page (the picker) or in a sentence on the idea page, never a page that never renders.
const TIMEOUT_MS = 5000;

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

function failed(path: string, status: number): never {
  // The session ended between the page's /me check and this call: sign in again.
  if (status === 401) redirect("/login");
  throw new Error(`${path} answered ${status}`);
}

export type PickerPage = { kind: "page"; picker: PitchPicker } | { kind: "notFound" } | { kind: "staleCursor" };

/** One page of the picker: the directory by niche, what a tag would do for each organisation, and the plan cap. */
export async function pickerPage(proposalId: string, query: PickerQuery): Promise<PickerPage> {
  const { data, response } = await serverApi().GET("/api/me/proposals/{proposal_id}/pitch/orgs", {
    params: { path: { proposal_id: proposalId }, query: pickerApiQuery(query) },
    ...(await options()),
  });
  if (data) return { kind: "page", picker: data };
  if (response.status === 404) return { kind: "notFound" };
  if (response.status === 400 && query.cursor) return { kind: "staleCursor" };
  return failed("GET /api/me/proposals/{proposal_id}/pitch/orgs", response.status);
}

/**
 * Organisations chosen on another page or search (the URL's `sel`), each as the picker would list it, so the
 * developer sees every choice by name with its outcome before it is sent. The frozen API reads a directory entry by
 * id (its name) and says what a tag would do only through the picker, so each id is read by id, then looked up in the
 * picker searched by that name. An id either read cannot resolve (unlisted, unknown, not found by its name) is left
 * out: it is neither shown nor sent. At most one batch of ids.
 */
export async function chosenOptions(proposalId: string, ids: readonly string[]): Promise<PitchOption[]> {
  const init = await options();
  const api = serverApi();
  const found = await Promise.all(
    ids
      .filter(isOrgId)
      .slice(0, MAX_BATCH)
      .map(async (id): Promise<PitchOption | null> => {
        try {
          const card = await api.GET("/api/directory/orgs/{org_id}", { params: { path: { org_id: id } }, ...init });
          if (!card.data) return null;
          const q = Array.from(card.data.name.replace(/\u0000/g, "").trim()).slice(0, 100).join("");
          if (!q) return null;
          const { data } = await api.GET("/api/me/proposals/{proposal_id}/pitch/orgs", {
            params: { path: { proposal_id: proposalId }, query: { q, limit: 100 } },
            ...init,
          });
          const option = data?.groups.flatMap((group) => group.orgs).find((o) => orgKey(o.card.id) === orgKey(id));
          return option ?? null;
        } catch {
          return null; // timed out or unreachable: not shown, so not sent
        }
      }),
  );
  return found.filter((option): option is PitchOption => option !== null);
}

/** The niche tree for the picker's niche select. */
export async function nicheTree() {
  const { data, response } = await serverApi().GET("/api/directory/niches", await options());
  if (!data) failed("GET /api/directory/niches", response.status);
  return data;
}

/** A read the idea page can do without: null when it fails (the page then says so in one sentence). */
async function tolerant<T>(call: () => Promise<{ data?: T; response: Response }>): Promise<T | null> {
  let answer: { data?: T; response: Response };
  try {
    answer = await call();
  } catch {
    return null; // timed out or unreachable
  }
  if (answer.response.status === 401) redirect("/login");
  return answer.data ?? null;
}

/** The idea's tags and the plan cap, or null when they cannot be read now. */
export async function ideaTags(proposalId: string): Promise<MyTags | null> {
  const init = await options();
  return tolerant(() =>
    serverApi().GET("/api/me/proposals/{proposal_id}/tags", { params: { path: { proposal_id: proposalId } }, ...init }),
  );
}

/** Who opened the idea's full details (owner only, newest first), or null when the log cannot be read now. */
export async function ideaViews(proposalId: string): Promise<ProposalViews | null> {
  const init = await options();
  return tolerant(() =>
    serverApi().GET("/api/me/proposals/{proposal_id}/views", { params: { path: { proposal_id: proposalId } }, ...init }),
  );
}
