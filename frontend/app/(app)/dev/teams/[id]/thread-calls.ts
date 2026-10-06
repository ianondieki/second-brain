import type { ThreadCalls } from "@/components/tracker/messages/calls";
import { retryMinutes } from "@/components/tracker/messages/refusals";
import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-code";

import { teamPostRefusal, toMessage, toThreadPage } from "./team-thread";

// The team thread's calls in the shape the engagement thread's parts make them (components/tracker/messages: Thread,
// Composer, ReportSheet take a `calls` prop): the same steps against /api/me/teams/{thread_id} (REQ-DEV-03), each
// settling into the value or the refusal those parts already word. A team message carries no files, so the file
// calls refuse (the composer offers no Attach when max_attachments is 0).

const THREAD = "/api/me/teams/{thread_id}" as const;

/** The calls of the thread with `counterpart` (the other developer's handle, the sender name of their messages). */
export function teamThreadCalls(counterpart: string, client: ApiClient = api): ThreadCalls {
  return {
    async postMessage(threadId, body) {
      try {
        const { data, error, response } = await client.POST(`${THREAD}/messages`, {
          params: { path: { thread_id: threadId } },
          body: { body },
        });
        if (data) return { ok: true, message: toMessage(data, counterpart) };
        const refusal = teamPostRefusal(response.status, error);
        return refusal === "tooMany" ? { ok: false, refusal, minutes: retryMinutes(response.headers, error) } : { ok: false, refusal };
      } catch {
        return { ok: false, refusal: "network" };
      }
    },
    async olderPage(threadId, cursor) {
      try {
        const { data } = await client.GET(THREAD, { params: { path: { thread_id: threadId }, query: { cursor } } });
        return data ? { ok: true, thread: toThreadPage(data, counterpart) } : { ok: false };
      } catch {
        return { ok: false };
      }
    },
    async markRead(threadId, upTo) {
      try {
        const { response } = await client.POST(`${THREAD}/read`, {
          params: { path: { thread_id: threadId } },
          body: { up_to: upTo },
        });
        return response.ok;
      } catch {
        return false;
      }
    },
    async reportMessage(threadId, messageId, reasons) {
      try {
        const { error, response } = await client.POST(`${THREAD}/messages/{message_id}/report`, {
          params: { path: { thread_id: threadId, message_id: messageId } },
          body: { reasons },
        });
        if (response.ok) return { ok: true, created: true };
        const code = apiErrorCode(error);
        // Reported before (by the caller): the line says it is already with the moderators.
        if (code === "already_reported") return { ok: true, created: false };
        if (code === "own_message") return { ok: false, refusal: "reportOwn" };
        return { ok: false, refusal: response.status === 429 ? "reportLimit" : "reportFailed" };
      } catch {
        return { ok: false, refusal: "reportFailed" };
      }
    },
    fileLink: async () => ({ ok: false, changed: false }),
    removeStaged: async () => true,
    uploadFile: async () => ({ ok: false, problem: "failed" }),
  };
}
