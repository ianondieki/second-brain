"use client";

import { useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

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
      <dl data-contact-revealed="" className="grid gap-x-8 gap-y-2 sm:grid-cols-[minmax(10rem,auto)_1fr]">
        <dt className="text-sm font-medium text-ink-soft">{t("contact.name")}</dt>
        <dd className="text-ink [overflow-wrap:anywhere]">{contact.developer_name}</dd>
        <dt className="text-sm font-medium text-ink-soft">{t("contact.email")}</dt>
        <dd className="text-ink [overflow-wrap:anywhere]">
          {contact.email ? <a href={`mailto:${contact.email}`}>{contact.email}</a> : t("contact.noEmail")}
        </dd>
      </dl>
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
