"use client";

import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";

import { revealContact, type Contact, type Refusal } from "./calls";

/**
 * The developer's contact details for the organisation's named contact person (GET …/contact; docs/spec/06 6.9 stage
 * 3, AC-TRACK-9). Fetched only when asked for: each reveal is recorded on the organisation's audit trail.
 */
export function ContactReveal({
  engagementId,
  revealImpl = revealContact,
}: {
  engagementId: string;
  revealImpl?: typeof revealContact;
}) {
  const t = useStrings("trackerActions");
  const [contact, setContact] = useState<Contact | null>(null);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [busy, setBusy] = useState(false);
  const revealed = useRef<HTMLDivElement>(null);

  // The button the person pressed is replaced by the details: focus moves to them, so they are announced where the
  // control was (WCAG 2.4.3; ECC review, P16-F), as ShareTier2 does.
  useEffect(() => {
    if (contact) revealed.current?.focus();
  }, [contact]);

  async function reveal() {
    if (busy) return;
    setBusy(true);
    setRefusal(null);
    const outcome = await revealImpl(engagementId);
    setBusy(false);
    if (outcome.ok) setContact(outcome.contact);
    else setRefusal(outcome.refusal);
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
    <div className="flex flex-col items-start gap-3">
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
