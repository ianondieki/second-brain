"use client";

import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";

import { revealContact, type Contact, type Refusal } from "./calls";

type Outcome = Awaited<ReturnType<typeof revealContact>>;

/**
 * The developer's contact details for the organisation's named contact person (GET …/contact; docs/spec/06 6.9 stage
 * 3, AC-TRACK-9). Fetched only when asked for: each reveal is recorded on the organisation's audit trail. On the
 * tracker it loads only once its button is pressed (components/tracker/lazy.tsx, LazyContactReveal) and then `start`s
 * at once, its own button taking the focus while it works: the press was the asking.
 */
export function ContactReveal({
  engagementId,
  revealImpl = revealContact,
  start = false,
}: {
  engagementId: string;
  revealImpl?: typeof revealContact;
  /** Reveal on mount (the button that loaded this part was the press); once only. */
  start?: boolean;
}) {
  const t = useStrings("trackerActions");
  const [contact, setContact] = useState<Contact | null>(null);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [busy, setBusy] = useState(start);
  const revealed = useRef<HTMLDivElement>(null);
  const asking = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  function settle(outcome: Outcome) {
    setBusy(false);
    if (outcome.ok) setContact(outcome.contact);
    else setRefusal(outcome.refusal);
  }

  // Pressed already (the lazy button): the place the press left is this button, busy, until the details replace it.
  useEffect(() => {
    if (!start || started.current) return;
    started.current = true;
    asking.current?.querySelector("button")?.focus();
    void revealImpl(engagementId).then(settle);
  }, [start, revealImpl, engagementId]);

  // The button the person pressed is replaced by the details: focus moves to them, so they are announced where the
  // control was (WCAG 2.4.3; ECC review, P16-F), as ShareTier2 does.
  useEffect(() => {
    if (contact) revealed.current?.focus();
  }, [contact]);

  async function reveal() {
    if (busy) return;
    setBusy(true);
    setRefusal(null);
    settle(await revealImpl(engagementId));
  }

  if (contact) {
    return (
      <div ref={revealed} tabIndex={-1} className="focus:outline-none">
        <DescriptionList data-contact-revealed="">
          <Description label={t("contact.name")}>{contact.developer_name}</Description>
          <Description label={t("contact.email")}>
            {contact.email ? <a href={mailto(contact.email)}>{contact.email}</a> : t("contact.noEmail")}
          </Description>
        </DescriptionList>
      </div>
    );
  }

  return (
    <div ref={asking} className="flex flex-col items-start gap-3">
      {refusal ? <Alert className="w-full">{t(`refusal.${refusal}`)}</Alert> : null}
      <Button variant="secondary" busy={busy} onClick={reveal}>
        {busy ? t("busy") : t("contact.reveal")}
      </Button>
    </div>
  );
}

/**
 * A mailto: link to one address and nothing else: the local part and the domain are encoded, so an address the API
 * accepted with `?`, `&` or `=` in it cannot add recipients, a subject or a body to the draft (ECC review, P16-F).
 */
export function mailto(email: string): string {
  const at = email.lastIndexOf("@");
  if (at < 0) return `mailto:${encodeURIComponent(email)}`;
  return `mailto:${encodeURIComponent(email.slice(0, at))}@${encodeURIComponent(email.slice(at + 1))}`;
}
