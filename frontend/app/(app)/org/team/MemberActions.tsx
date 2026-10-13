"use client";

import { lazy, Suspense, useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

import type { TeamCalls } from "./calls";
import type { OrgRole } from "./team";

// The open step (roles or removal) is a chunk of its own, fetched when a button is pressed (MemberEditor.tsx).
const MemberEditor = lazy(() => import("./MemberEditor").then((module) => ({ default: module.MemberEditor })));

type Mode = "idle" | "roles" | "remove";

/**
 * A member's actions for an owner or admin (REQ-TEN-02): "Change roles" (an owner's alone) and "Remove", each opening
 * its step in place (MemberEditor, loaded on the press); "Roles saved." when the roles were changed. The last owner and
 * the protected roles are refused by the API and said there in words.
 */
export function MemberActions({
  orgId,
  orgName,
  member,
  canChangeRoles,
  canRemove,
  enrolled,
  calls,
}: {
  orgId: string;
  orgName: string;
  member: { user_id: string; name: string; roles: readonly OrgRole[] };
  canChangeRoles: boolean;
  canRemove: boolean;
  enrolled: boolean;
  calls?: TeamCalls;
}) {
  const t = useStrings("teamAdmin");
  const [mode, setMode] = useState<Mode>("idle");
  const [saved, setSaved] = useState(false);
  // The button that opened the step, to give focus back to when it closes (the idle buttons are drawn anew).
  const returnTo = useRef<Mode>("idle");
  const actions = useRef<HTMLDivElement>(null);
  const done = useRef<HTMLDivElement>(null);

  // Focus back to the button that opened the step when it closes (WCAG 2.4.3).
  useEffect(() => {
    if (mode !== "idle") return;
    const back = returnTo.current;
    returnTo.current = "idle";
    if (back === "idle") return;
    const selector = back === "roles" ? "[data-change-roles]" : "[data-remove]";
    actions.current?.querySelector<HTMLElement>(selector)?.focus();
  }, [mode]);

  function open(next: Mode) {
    setSaved(false);
    setMode(next);
  }

  if (mode !== "idle") {
    return (
      <Suspense fallback={<p role="status" className="text-sm text-ink-soft sm:col-span-2">{t("loading")}</p>}>
        <MemberEditor
          mode={mode}
          orgId={orgId}
          orgName={orgName}
          member={member}
          enrolled={enrolled}
          calls={calls}
          onClose={() => {
            returnTo.current = mode;
            setMode("idle");
          }}
          onSaved={() => {
            setMode("idle");
            setSaved(true);
            requestAnimationFrame(() => done.current?.focus());
          }}
        />
      </Suspense>
    );
  }

  if (!canChangeRoles && !canRemove) return null;
  return (
    <div
      ref={actions}
      // Under 640 px the actions sit under the person's words, past the initials (36 px + 14 px gap).
      className="flex flex-col gap-2 pl-[3.125rem] sm:col-start-2 sm:row-start-1 sm:items-end sm:pl-0"
      data-member-actions={member.user_id}
    >
      <div className="flex gap-2">
        {canChangeRoles ? (
          <Button
            variant="link"
            onClick={() => open("roles")}
            aria-label={t("changeRolesLabel", { name: member.name })}
            data-change-roles=""
          >
            {t("changeRoles")}
          </Button>
        ) : null}
        {canRemove ? (
          <Button
            variant="link"
            onClick={() => open("remove")}
            aria-label={t("removeLabel", { name: member.name })}
            data-remove=""
          >
            {t("remove")}
          </Button>
        ) : null}
      </div>
      {saved ? (
        <Alert ref={done} tone="ok" className="w-full">
          <p>{t("rolesSaved")}</p>
        </Alert>
      ) : null}
    </div>
  );
}
