import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { HashFocus } from "./HashFocus";

// REQ-ENG-11 (P21 re-review): the Messages route lands where its address points, after a first load or an in-app
// navigation: the thread's heading, a message, or (a message older than the first page) the heading again.

afterEach(() => {
  cleanup();
  history.replaceState(null, "", "/");
});

function page(hash: string) {
  history.replaceState(null, "", `/dev/engagements/e/messages${hash}`);
  return render(
    <>
      <h2 id="messages-heading" tabIndex={-1}>
        Messages
      </h2>
      <article id="message-m1" tabIndex={-1}>
        A message
      </article>
      <HashFocus fallback="messages-heading" />
    </>,
  );
}

describe("landing on the thread", () => {
  it("focuses the thread's heading", () => {
    page("#messages-heading");
    expect(document.activeElement?.id).toBe("messages-heading");
  });

  it("focuses the message a History entry points at", () => {
    page("#message-m1");
    expect(document.activeElement?.id).toBe("message-m1");
  });

  it("falls back to the heading for a message not on the first page", () => {
    page("#message-older");
    expect(document.activeElement?.id).toBe("messages-heading");
  });

  it("leaves focus alone without a fragment", () => {
    page("");
    expect(document.activeElement).toBe(document.body);
  });
});
