import { notFound, redirect } from "next/navigation";
import { cache } from "react";

import { isUuid } from "@/app/(app)/org/membership";
import { forwardHeaders, serverApi } from "@/lib/api/server";

import { HOME_PEERS, type Blocked, type Contribution, type Invitations, type PeersPage, type Profile, type TeamThread, type ThreadSummary } from "./teams";

// Server-side reads of peers and team up (REQ-DEV-03; bridge/teams/router.py, bridge/teams/peers.py), signed in,
// developers only (the API answers 404 to anyone else). Each is bounded, so a hung API ends in the route's error page
// (or, on Home, in a Home without the section) instead of a page that never renders.
const TIMEOUT_MS = 5000;
const HOME = "/dev";

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

function failed(path: string, status: number): never {
  if (status === 401) redirect("/login");
  if (status === 404) redirect(HOME);
  throw new Error(`GET ${path} answered ${status}`);
}

/**
 * Home's Peers section: the first three peers (a first page of three or fewer is not counted toward the hourly
 * limit) and whether the caller is visible to peers; null when the section is left out (a refusal, no answer in time,
 * the network). Only a lost session (401) leaves Home.
 */
export async function homePeers(): Promise<PeersPage | null> {
  let answer;
  try {
    answer = await serverApi().GET("/api/me/peers", { params: { query: { limit: HOME_PEERS } }, ...(await options()) });
  } catch {
    return null;
  }
  if (answer.data) return answer.data;
  if (answer.response.status === 401) redirect("/login");
  return null;
}

/** /dev/peers: one page of peers, or "tooMany" when the hourly limit of pages is reached (429). */
export async function peersPage(page = 1): Promise<PeersPage | "tooMany"> {
  const { data, response } = await serverApi().GET("/api/me/peers", { params: { query: { page } }, ...(await options()) });
  if (data) return data;
  if (response.status === 429) return "tooMany";
  return failed("/api/me/peers", response.status);
}

/**
 * Every niche's name by its slug (a peer's shared niches come as slugs). Empty when the list cannot be read: a row
 * then says how many niches it shares instead of their names.
 */
export const nicheNamesBySlug = cache(async function nicheNamesBySlug(): Promise<Record<string, string>> {
  try {
    const { data } = await serverApi().GET("/api/directory/niches", await options());
    const names: Record<string, string> = {};
    for (const parent of data ?? []) {
      names[parent.slug] = parent.name;
      for (const child of parent.children ?? []) names[child.slug] = child.name;
    }
    return names;
  } catch {
    return {};
  }
});

export async function myInvitations(): Promise<Invitations> {
  const { data, response } = await serverApi().GET("/api/me/teams/invitations", await options());
  return data ?? failed("/api/me/teams/invitations", response.status);
}

export async function myThreads(): Promise<ThreadSummary[]> {
  const { data, response } = await serverApi().GET("/api/me/teams", await options());
  return data?.threads ?? failed("/api/me/teams", response.status);
}

/** The ideas that credit the caller as a contributor; empty when they cannot be read (the list is secondary). */
export async function myContributions(): Promise<Contribution[]> {
  try {
    const { data } = await serverApi().GET("/api/me/contributions", await options());
    return data?.items ?? [];
  } catch {
    return [];
  }
}

/** One team thread's latest page, or the not-found page (not a party, unknown, not a uuid). Read once per request. */
export const teamThread = cache(async function teamThread(id: string): Promise<TeamThread> {
  if (!isUuid(id)) notFound();
  const { data, response } = await serverApi().GET("/api/me/teams/{thread_id}", {
    params: { path: { thread_id: id } },
    ...(await options()),
  });
  if (data) return data;
  if (response.status === 401) redirect("/login");
  if (response.status === 404) notFound();
  throw new Error(`GET /api/me/teams/{thread_id} answered ${response.status}`);
});

/** Settings › Profile: the caller's developer profile. */
export async function myProfile(): Promise<Profile> {
  const { data, response } = await serverApi().GET("/api/me/profile", await options());
  return data ?? failed("/api/me/profile", response.status);
}

/** The developers the caller blocked; empty when they cannot be read (the list is secondary on the page). */
export async function myBlocks(): Promise<Blocked[]> {
  try {
    const { data } = await serverApi().GET("/api/me/blocks", await options());
    return data?.blocked ?? [];
  } catch {
    return [];
  }
}

/**
 * The owner's view of an idea's contributors (each id with the handle the idea shows), for "Remove"; null when it
 * cannot be read (the idea page then shows the handles without Remove).
 */
export async function ideaContributors(proposalId: string): Promise<{ user_id: string; handle: string }[] | null> {
  try {
    const { data } = await serverApi().GET("/api/me/ideas/{proposal_id}/contributors", {
      params: { path: { proposal_id: proposalId } },
      ...(await options()),
    });
    return data ? data.items.map(({ user_id, handle }) => ({ user_id, handle })) : null;
  } catch {
    return null;
  }
}

/**
 * The caller's published ideas (id and title), which a team-thread counterpart can be credited on; empty when they
 * cannot be read: the thread page then offers no credit step rather than failing.
 */
export async function myPublishedIdeas(): Promise<{ id: string; title: string }[]> {
  try {
    const { data } = await serverApi().GET("/api/me/proposals", await options());
    return (data?.items ?? []).flatMap((idea) =>
      idea.status === "published" && idea.moderation_state === "clear" && idea.title ? [{ id: idea.id, title: idea.title }] : [],
    );
  } catch {
    return [];
  }
}

/** What already stands between the caller and a peer: an open thread, an invitation from them, or one to them. */
export type PeerRelation = { kind: "thread"; id: string } | { kind: "invitedYou" } | { kind: "invited" };

/**
 * The caller's open threads and pending invitations by the other developer's id, for /dev/peers (a peer they already
 * team up with, or have an invitation with, shows that instead of Team up). Empty when it cannot be read.
 */
export async function peerRelations(): Promise<Record<string, PeerRelation>> {
  try {
    const opts = await options();
    const [threads, invitations] = await Promise.all([
      serverApi().GET("/api/me/teams", opts),
      serverApi().GET("/api/me/teams/invitations", opts),
    ]);
    const out: Record<string, PeerRelation> = {};
    for (const item of invitations.data?.sent ?? []) if (item.counterpart) out[item.counterpart.user_id] = { kind: "invited" };
    for (const item of invitations.data?.received ?? []) if (item.counterpart) out[item.counterpart.user_id] = { kind: "invitedYou" };
    for (const thread of threads.data?.threads ?? []) {
      if (thread.open && thread.counterpart) out[thread.counterpart.user_id] = { kind: "thread", id: thread.id };
    }
    return out;
  } catch {
    return {};
  }
}
