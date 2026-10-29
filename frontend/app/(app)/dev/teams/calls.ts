import { api, type ApiClient } from "@/lib/api/client";

import {
  creditRefusal,
  decideRefusal,
  inviteRefusal,
  type CreditRefusal,
  type InviteRefusal,
  type PeersPage,
  type ProblemCard,
} from "./teams";

// Peers and team up from the browser (REQ-DEV-03; same-origin /api, the typed client adds the CSRF header to every
// POST, PATCH and DELETE). Each call settles into what the screen says, never a thrown error: a thrown fetch
// (offline, reset) is "failed".

export type Done = { ok: true } | { ok: false };

export async function done(run: () => Promise<{ response: Response }>): Promise<Done> {
  try {
    return { ok: (await run()).response.ok };
  } catch {
    return { ok: false };
  }
}

export interface TeamCalls {
  /** The next page of peers (the list's "More"): the page, the hourly limit, or a failure. */
  peers: (page: number) => Promise<PeersPage | "tooMany" | null>;
  /** Published problems and Briefs for the Team up sheet: newest first, or those whose words match. */
  problems: (q: string) => Promise<ProblemCard[] | null>;
  invite: (to: string, problem: string, note: string) => Promise<{ ok: true } | { ok: false; refusal: InviteRefusal }>;
  block: (userId: string) => Promise<Done>;
  accept: (invitationId: string) => Promise<{ ok: true; threadId: string } | { ok: false; refusal: "gone" | "failed" }>;
  decline: (invitationId: string) => Promise<{ ok: true } | { ok: false; refusal: "gone" | "failed" }>;
  withdraw: (invitationId: string) => Promise<{ ok: true } | { ok: false; refusal: "gone" | "failed" }>;
  leave: (threadId: string) => Promise<Done>;
  credit: (proposalId: string, userId: string) => Promise<{ ok: true } | { ok: false; refusal: CreditRefusal }>;
  leaveCredit: (proposalId: string) => Promise<Done>;
}

export function teamCalls(client: ApiClient = api): TeamCalls {
  async function decide(path: "accept" | "decline" | "withdraw", id: string) {
    try {
      const { response } = await client.POST(`/api/me/teams/invitations/{invitation_id}/${path}`, {
        params: { path: { invitation_id: id } },
      });
      return response.ok ? ({ ok: true } as const) : ({ ok: false, refusal: decideRefusal(response.status) } as const);
    } catch {
      return { ok: false, refusal: "failed" } as const;
    }
  }
  return {
    async peers(page) {
      try {
        const { data, response } = await client.GET("/api/me/peers", { params: { query: { page } } });
        return data ?? (response.status === 429 ? "tooMany" : null);
      } catch {
        return null;
      }
    },
    async problems(q) {
      const words = Array.from(q.trim()).slice(0, 100).join("");
      try {
        const { data } = await client.GET("/api/problems", { params: { query: { q: words || undefined, limit: 5 } } });
        return data?.items ?? null;
      } catch {
        return null;
      }
    },
    async invite(to, problem, note) {
      try {
        const { error, response } = await client.POST("/api/me/teams/invitations", {
          body: { to_user_id: to, problem_id: problem, note: note.trim() || null },
        });
        return response.ok ? { ok: true } : { ok: false, refusal: inviteRefusal(response.status, error) };
      } catch {
        return { ok: false, refusal: "failed" };
      }
    },
    block: (userId) => done(() => client.POST("/api/me/blocks", { body: { user_id: userId } })),
    async accept(id) {
      try {
        const { data, response } = await client.POST("/api/me/teams/invitations/{invitation_id}/accept", {
          params: { path: { invitation_id: id } },
        });
        return data ? { ok: true, threadId: data.thread_id } : { ok: false, refusal: decideRefusal(response.status) };
      } catch {
        return { ok: false, refusal: "failed" };
      }
    },
    decline: (id) => decide("decline", id),
    withdraw: (id) => decide("withdraw", id),
    leave: (threadId) => done(() => client.POST("/api/me/teams/{thread_id}/leave", { params: { path: { thread_id: threadId } } })),
    async credit(proposalId, userId) {
      try {
        const { error, response } = await client.POST("/api/me/ideas/{proposal_id}/contributors", {
          params: { path: { proposal_id: proposalId } },
          body: { user_id: userId },
        });
        return response.ok ? { ok: true } : { ok: false, refusal: creditRefusal(response.status, error) };
      } catch {
        return { ok: false, refusal: "failed" };
      }
    },
    leaveCredit: (proposalId) =>
      done(() => client.DELETE("/api/me/contributions/{proposal_id}", { params: { path: { proposal_id: proposalId } } })),
  };
}
