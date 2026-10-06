"use client";

import Link from "next/link";
import { lazy, Suspense, useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";
import { RowBase, RowList } from "@/components/ui/RowBase";
import { CheckIcon } from "@/components/ui/status-icons";

import { teamCalls, type TeamCalls } from "../teams/calls";
import { Overflow, overflowItemClass } from "../teams/Overflow";
import { closeOverflows } from "../teams/overflow-close";
import type { PeerRelation } from "../teams/data";
import { nameList, nicheNames, threadHref, type Peer, type PeersPage } from "../teams/teams";

// The Team up sheet loads with the first press of a Team up (its search and form are not needed to read the list).
const TeamUpSheet = lazy(() => import("./TeamUpSheet").then((m) => ({ default: m.TeamUpSheet })));

export interface PeerListProps {
  initial: PeersPage;
  /** Niche names by slug (a peer's shared niches come as slugs). */
  niches: Readonly<Record<string, string>>;
  /** What already stands with a peer (an open thread, an invitation either way), by their id. */
  relations?: Readonly<Record<string, PeerRelation>>;
  locale: string;
  calls?: Partial<TeamCalls>;
}

/**
 * The peers of /dev/peers (REQ-DEV-03; D-58): one row each (handle, headline, the niches the two share by name, the
 * county when it is theirs too), "Team up" as each row's one action (a sheet: the problem or Brief, a note, "Send
 * invitation"), then "Invited" with the line saying it was sent, which takes focus. "Block" sits in each row's overflow
 * menu behind a confirmation; a peer the caller already teams up with shows "Teaming up" (their thread), and one with
 * an invitation either way "Invited you" or "Invited", instead of Team up; a blocked peer leaves the list and a status line says so (it takes focus). "More" adds
 * the next page of twenty.
 */
export function PeerList({ initial, niches, relations = {}, locale, calls: given }: PeerListProps) {
  const t = useStrings("teamUp");
  const [calls] = useState<TeamCalls>(() => ({ ...teamCalls(), ...given }));
  const [peers, setPeers] = useState(initial.peers);
  const [next, setNext] = useState(initial.next);
  const [more, setMore] = useState<"idle" | "busy" | "failed" | "tooMany">("idle");
  const [invited, setInvited] = useState<Record<string, true>>({});
  const [justSent, setJustSent] = useState<string | null>(null);
  const [inviting, setInviting] = useState<Peer | null>(null);
  const [blocking, setBlocking] = useState<Peer | null>(null);
  const [blockState, setBlockState] = useState<"idle" | "busy" | "failed">("idle");
  const [said, setSaid] = useState<{ text: string; n: number } | null>(null);
  const blockDialog = useRef<HTMLDialogElement>(null);
  const status = useRef<HTMLDivElement>(null);
  const blocked = useRef<string | null>(null);

  useEffect(() => {
    if (said) status.current?.focus();
  }, [said]);

  useEffect(() => {
    if (blocking) openConfirm(blockDialog.current);
  }, [blocking]);

  useEffect(() => {
    document.addEventListener("click", closeOverflows);
    document.addEventListener("keydown", closeOverflows);
    return () => {
      document.removeEventListener("click", closeOverflows);
      document.removeEventListener("keydown", closeOverflows);
    };
  }, []);

  async function loadMore() {
    if (!next || more === "busy") return;
    setMore("busy");
    const page = await calls.peers(next);
    if (page === null || page === "tooMany") {
      setMore(page === null ? "failed" : "tooMany");
      return;
    }
    const first = page.peers[0];
    setPeers((shown) => [...shown, ...page.peers.filter((peer) => !shown.some((s) => s.user_id === peer.user_id))]);
    setNext(page.next);
    setMore("idle");
    // Reading goes on from the first peer just added.
    if (first) requestAnimationFrame(() => document.getElementById(`peer-${first.user_id}`)?.focus());
  }

  async function block() {
    if (!blocking || blockState === "busy") return;
    setBlockState("busy");
    const outcome = await calls.block(blocking.user_id);
    if (!outcome.ok) {
      setBlockState("failed");
      return;
    }
    blocked.current = blocking.handle;
    blockDialog.current?.close();
  }

  return (
    <div className="flex flex-col gap-6">
      {said ? (
        <Alert key={said.n} tone="ok" ref={status}>
          {said.text}
        </Alert>
      ) : null}

      <div className="rounded-panel border border-line bg-field px-4 sm:px-6">
        <RowList rule={false} data-peer-list="">
          {peers.map((peer) => {
            const titleId = `peer-${peer.user_id}-title`;
            const shared = nicheNames(peer.shared_niches, niches);
            return (
              <RowBase
                key={peer.user_id}
                id={`peer-${peer.user_id}`}
                tabIndex={-1}
                className="focus:outline-none"
                data-peer={peer.handle}
                data-invited={invited[peer.user_id] ? "" : undefined}
                titleId={titleId}
                // The page has no section heading over the list: each peer's handle is the next level under the h1.
                headingLevel={2}
                title={peer.handle}
                meta={peer.headline ?? t("row.noHeadline")}
              >
                {peer.same_county || shared.length > 0 ? (
                  <p className="flex flex-wrap gap-x-4 text-sm text-ink">
                    {peer.same_county ? <span data-same-county="">{t("row.sameCounty")}</span> : null}
                    {shared.length > 0 ? <span>{t("row.sharedNiches", { value: nameList(shared, locale) })}</span> : null}
                  </p>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  {invited[peer.user_id] ? (
                    <InvitedLine name={peer.handle} focus={justSent === peer.user_id} />
                  ) : relations[peer.user_id]?.kind === "thread" ? (
                    <Link href={threadHref((relations[peer.user_id] as { id: string }).id)} className={standaloneLinkClass} aria-describedby={titleId} data-relation="thread">
                      {t("row.teaming")}
                    </Link>
                  ) : relations[peer.user_id] ? (
                    <p className="flex min-h-11 items-center font-semibold text-ink" data-relation={relations[peer.user_id]?.kind}>
                      {relations[peer.user_id]?.kind === "invitedYou" ? t("row.invitedYou") : t("row.invited")}
                    </p>
                  ) : (
                    <Button aria-describedby={titleId} aria-haspopup="dialog" onClick={() => setInviting(peer)} data-team-up="">
                      {t("row.teamUp")}
                    </Button>
                  )}
                  <Overflow label={t("row.more")} describedBy={titleId} data-peer-menu="">
                    <button
                      type="button"
                      className={`${overflowItemClass} text-error`}
                      aria-haspopup="dialog"
                      onClick={(event) => {
                        // The menu closes and its button takes focus before the dialog opens, so Cancel or Escape give
                        // focus back to the row's menu button (this item is hidden once the menu closes).
                        const menu = event.currentTarget.closest("details");
                        if (menu) menu.open = false;
                        menu?.querySelector("summary")?.focus();
                        setBlockState("idle");
                        setBlocking(peer);
                      }}
                      data-block=""
                    >
                      {t("row.block")}
                    </button>
                  </Overflow>
                </div>
              </RowBase>
            );
          })}
        </RowList>
      </div>

      {next ? (
        <div className="flex flex-col items-start gap-2">
          <Button busy={more === "busy"} onClick={() => void loadMore()} data-more-peers="">
            {more === "busy" ? t("list.loading") : t("list.more")}
          </Button>
          {more === "failed" || more === "tooMany" ? (
            <Alert className="w-full">{more === "failed" ? t("list.moreFailed") : t("list.moreTooMany")}</Alert>
          ) : null}
        </div>
      ) : null}

      {inviting ? (
        <Suspense fallback={null}>
          <TeamUpSheet
            key={inviting.user_id}
            peer={inviting}
            locale={locale}
            calls={calls}
            onDone={(sent) => {
              const peer = inviting;
              setInviting(null);
              if (!sent) return;
              setInvited((now) => ({ ...now, [peer.user_id]: true }));
              setJustSent(peer.user_id);
            }}
          />
        </Suspense>
      ) : null}

      <ConfirmDialog
        ref={blockDialog}
        tone="danger"
        title={t("block.title", { name: blocking?.handle ?? "" })}
        confirmLabel={t("block.confirm")}
        busyLabel={t("block.busy")}
        cancelLabel={t("block.cancel")}
        busy={blockState === "busy"}
        onConfirm={() => void block()}
        problem={blockState === "failed" ? <Alert>{t("block.failed")}</Alert> : null}
        onClose={() => {
          const gone = blocking;
          setBlocking(null);
          setBlockState("idle");
          if (gone && blocked.current === gone.handle) {
            blocked.current = null;
            setPeers((shown) => shown.filter((peer) => peer.user_id !== gone.user_id));
            setSaid((now) => ({ text: t("list.blocked", { name: gone.handle }), n: (now?.n ?? 0) + 1 }));
          }
        }}
      >
        <p>{t("block.body")}</p>
      </ConfirmDialog>
    </div>
  );
}

/** "Invited", and the line saying the invitation went, which takes focus once, right after sending. */
function InvitedLine({ name, focus }: { name: string; focus: boolean }) {
  const t = useStrings("teamUp");
  const line = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (focus) line.current?.focus();
  }, [focus]);
  return (
    <p ref={line} tabIndex={-1} role="status" className="flex min-h-11 items-center gap-2 text-ink focus:outline-none" data-invited-line="">
      <CheckIcon className="size-5 shrink-0 text-ok" />
      <span className="font-semibold">{t("row.invited")}</span>
      <span className="text-sm text-ink-soft">{t("row.sent", { name })}</span>
    </p>
  );
}
