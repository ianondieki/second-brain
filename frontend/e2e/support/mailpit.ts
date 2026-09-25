import type { APIRequestContext } from "@playwright/test";

// Reads the verification / sign-in link from Mailpit, the compose stack's test mailbox (never a real recipient).
const MAILPIT = (process.env.E2E_MAILPIT_URL ?? "http://localhost:8025").replace(/\/$/, "");
const LINK = /https?:\/\/[^\s"<>]+\/auth\/link#token=[A-Za-z0-9_-]+/;

interface Summary {
  ID: string;
  To: Array<{ Address: string }>;
}

/** Waits for the newest message to `to` that carries a sign-in link, and returns that link. */
export async function waitForSignInLink(request: APIRequestContext, to: string, timeoutMs = 30_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  const wanted = to.toLowerCase();
  while (Date.now() < deadline) {
    const list = await request.get(`${MAILPIT}/api/v1/messages?limit=100`);
    if (list.ok()) {
      const { messages = [] } = (await list.json()) as { messages?: Summary[] };
      for (const summary of messages) {
        if (!summary.To?.some((r) => r.Address.toLowerCase() === wanted)) continue;
        const message = await request.get(`${MAILPIT}/api/v1/message/${summary.ID}`);
        const { Text = "", HTML = "" } = (await message.json()) as { Text?: string; HTML?: string };
        const found = LINK.exec(Text) ?? LINK.exec(HTML);
        if (found) return found[0];
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`No sign-in link reached ${to} within ${timeoutMs} ms (Mailpit at ${MAILPIT})`);
}

/** The path and fragment of a link, so the test opens it on the stack under test whatever host the email names. */
export function pathOf(link: string): string {
  const url = new URL(link);
  return `${url.pathname}${url.search}${url.hash}`;
}
