import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ClientStrings, type StringTree } from "./ClientStrings";
import { ErrorScreen } from "./ErrorScreen";
import en from "@/locales/en.json";

afterEach(cleanup);

// REQ-FND-04: the public demo's banner moves focus to #main when dismissed; on a failed page that is this <main>, so it
// takes focus programmatically (tabIndex -1, no ring: it is not a control), as every shell's main does.
describe("ErrorScreen", () => {
  it("has a main region that can take focus", () => {
    render(
      <ClientStrings strings={{ errorPage: en.errorPage as unknown as StringTree }}>
        <ErrorScreen retry={() => {}} />
      </ClientStrings>,
    );
    const main = document.getElementById("main")!;
    expect(main.tagName).toBe("MAIN");
    expect(main.getAttribute("tabindex")).toBe("-1");
    main.focus();
    expect(document.activeElement).toBe(main);
  });
});
