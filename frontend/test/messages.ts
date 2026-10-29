import type { Limits, Message, Thread } from "@/components/tracker/messages/thread";

import { ENGAGEMENT_ID } from "./engagement";

// Engagement thread fixtures for the Messages tab's tests (REQ-ENG-11), shaped like GET …/messages answers.

export const LIMITS: Limits = {
  max_chars: 4000,
  max_attachments: 5,
  max_attachment_bytes: 20_971_520,
  accepted_types: ["application/pdf", "image/png", "image/jpeg", "text/markdown", "text/plain"],
};

export function message(overrides: Partial<Message> = {}): Message {
  return {
    id: "0199b000-0000-7000-8000-0000000a0001",
    sender_party: "org",
    sender_name: "Rita Wanjiru",
    mine: false,
    body: "Habari Achieng,\nCan you share the pilot plan?",
    redacted: false,
    created_at: "2026-10-05T07:05:00Z",
    attachments: [],
    ...overrides,
  };
}

export function thread(overrides: Partial<Thread> = {}): Thread {
  return {
    engagement_id: ENGAGEMENT_ID,
    status: "open",
    opens_at_stage: "INTEREST_CONFIRMED",
    can_post: true,
    unread: 0,
    last_read_at: null,
    limits: LIMITS,
    items: [],
    next_cursor: null,
    ...overrides,
  };
}
