import { readFileSync } from "node:fs";
import { Blob as NodeBlob } from "node:buffer";
import { createHash } from "node:crypto";
import { join } from "node:path";

import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { detail, ORG_ID } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { DeclarationLine } from "@/components/team/TeamPanel";
import { HistoryList } from "@/components/tracker/HistoryList";
import { history } from "@/test/engagement";

import { declarationRefusal, type Declaration, type DeclarationOutcome } from "./calls";
import { DeclarationSheet } from "./DeclarationSheet";
import { focusLineWhenRefreshed, LINE_ID } from "./focus-line";
import { asSha256, HASH_MAX_BYTES, nairobiDay, sha256Hex } from "./hash";
import { ReceivedDeclaration } from "./ReceivedDeclaration";

// REQ-PROV-06 (P27 track D; docs/spec/06 6.4 pt 5): the organisation's declaration line and sheet (the file hashed
// in the browser, only the hex sent, every refusal by its code), the developer's panel, and History's label.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

afterEach(cleanup);

const FIXTURE = join(__dirname, "../../e2e/fixtures/prior-knowledge-evidence.txt");
const HASH = "44c2f203ce95cec1dfd7e6ede4d4963c602cc7cf2c82ebbf471931d52423ab83";

describe("the fingerprint", () => {
  it("is the SHA-256 that sha256sum prints, computed with Web Crypto", async () => {
    const bytes = readFileSync(FIXTURE);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(HASH);
    expect(await sha256Hex(new NodeBlob([bytes]) as unknown as Blob)).toBe(HASH);
    expect(await sha256Hex(new NodeBlob(["abc"]) as unknown as Blob)).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("accepts a pasted SHA-256 (64 hex digits, any case, spaces around) and nothing else", () => {
    expect(asSha256(` ${HASH.toUpperCase()} `)).toBe(HASH);
    expect(asSha256(HASH.slice(1))).toBeNull();
    expect(asSha256(`${HASH}0`)).toBeNull();
    expect(asSha256(HASH.replace("4", "g"))).toBeNull();
    expect(asSha256("")).toBeNull();
  });

  it("reads the first view's Nairobi day (22:30 UTC is already the next day)", () => {
    expect(nairobiDay("2026-10-02T22:30:00Z")).toBe("2026-10-03");
  });
});

const RECORDED: Declaration = {
  id: "d1",
  engagement_id: "e",
  declared_at: "2026-10-05T08:00:00Z",
  evidence_sha256_hex: HASH,
  evidence_title: "Board minutes on the 2025 cold-chain pilot",
  evidence_dated_on: "2025-06-10",
  first_tier2_view_at: "2026-10-02T07:00:00Z",
  window_closes_on: "2026-10-16",
};

function open({
  declareImpl = vi.fn(async (): Promise<DeclarationOutcome> => ({ ok: true, declaration: RECORDED })),
  hashImpl = vi.fn(async () => HASH),
  onClose = vi.fn(),
} = {}) {
  renderWithIntl(
    <DeclarationSheet
      orgId={ORG_ID}
      engagementId="e"
      closesOn="2026-10-16"
      firstViewOn="2026-10-02"
      onClose={onClose}
      declareImpl={declareImpl}
      hashImpl={hashImpl}
    />,
  );
  return { declareImpl, hashImpl, onClose };
}

function fileOf(size: number, name = "minutes.pdf"): File {
  const file = new File(["x"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

async function chooseFile(file: File) {
  await act(async () => fireEvent.change(screen.getByLabelText("File"), { target: { files: [file] } }));
}

async function fillRest(title = "Board minutes on the 2025 cold-chain pilot", date = "2025-06-10") {
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: title } });
  fireEvent.change(screen.getByLabelText("Date of the evidence"), { target: { value: date } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Record declaration" })));
}

describe("the declaration sheet", () => {
  it("says what it is in three sentences: what, that only a hash leaves the device, and the window's end", () => {
    open();
    const dialog = screen.getByRole("dialog", { name: "Declare prior knowledge" });
    const text = dialog.textContent!;
    expect(text).toContain(
      "If your organisation already had similar work before it first viewed this proposal, record that here.",
    );
    expect(text).toContain(
      "Only a fingerprint (SHA-256) of your file leaves this device; the file itself is never uploaded.",
    );
    expect(text).toContain("Declarations are not recorded on the platform after 16 Oct 2026.");
    // The title is permanent: its help says so, and asks for no names.
    const title = screen.getByLabelText("Title") as HTMLInputElement;
    expect(document.getElementById(title.getAttribute("aria-describedby")!)!.textContent).toBe(
      "A short title, no names. It is kept permanently.",
    );
    expect(title.maxLength).toBe(200);
    // The evidence's date: on or before the first full-proposal view, named.
    const date = screen.getByLabelText("Date of the evidence") as HTMLInputElement;
    expect(date.max).toBe("2026-10-02");
    expect(text).toContain("On or before 2 Oct 2026, the day your organisation first viewed the full proposal.");
    expect(dialog.querySelector("[data-primary]")).toBeNull();
  });

  it("fingerprints the chosen file on the device and sends only the hex, the title and the date", async () => {
    const { declareImpl, hashImpl } = open();
    const file = fileOf(1200);
    await chooseFile(file);
    expect(hashImpl).toHaveBeenCalledWith(file);
    expect(screen.getByText("Fingerprint of minutes.pdf:")).toBeTruthy();
    expect(document.querySelector("[data-file-hash]")!.textContent).toBe(HASH);
    await fillRest();
    expect(declareImpl).toHaveBeenCalledTimes(1);
    const [org, engagement, body] = (declareImpl as ReturnType<typeof vi.fn>).mock.calls[0];
    expect([org, engagement]).toEqual([ORG_ID, "e"]);
    expect(body).toEqual({
      evidence_sha256_hex: HASH,
      evidence_title: "Board minutes on the 2025 cold-chain pilot",
      evidence_dated_on: "2025-06-10",
    });
    expect(Object.keys(body).sort()).toEqual(["evidence_dated_on", "evidence_sha256_hex", "evidence_title"]);
  });

  it("shows the receipt once recorded, with focus on it, and closes saying it changed", async () => {
    const { onClose } = open();
    await chooseFile(fileOf(10));
    await fillRest();
    const receipt = document.querySelector("[data-declaration-receipt]")!;
    expect(receipt.textContent).toContain("A declaration was recorded on 5 Oct 2026:");
    expect(receipt.querySelector("[data-hash]")!.textContent).toBe(HASH);
    expect(receipt.textContent).toContain("Board minutes on the 2025 cold-chain pilot");
    expect(receipt.textContent).toContain("10 Jun 2025");
    await waitFor(() => expect(document.activeElement).toBe(receipt.querySelector("h3")));
    fireEvent.click(within(receipt as HTMLElement).getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalledWith(true);
  });

  it("does not fingerprint a file over 50 MB: it asks for the pasted hash", async () => {
    const { hashImpl } = open();
    await chooseFile(fileOf(HASH_MAX_BYTES + 1));
    expect(hashImpl).not.toHaveBeenCalled();
    expect(screen.getByLabelText("File").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText(/Files over 50 MB are not fingerprinted in the browser/)).toBeTruthy();
  });

  it("takes a pasted hash instead, and refuses one that is not 64 hex digits", async () => {
    const { declareImpl } = open();
    fireEvent.click(screen.getByRole("radio", { name: "Paste a SHA-256" }));
    const field = screen.getByLabelText("SHA-256");
    fireEvent.change(field, { target: { value: "abc123" } });
    await fillRest();
    expect(declareImpl).not.toHaveBeenCalled();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field);
    fireEvent.change(field, { target: { value: HASH.toUpperCase() } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Record declaration" })));
    expect((declareImpl as ReturnType<typeof vi.fn>).mock.calls[0][2].evidence_sha256_hex).toBe(HASH);
  });

  it("asks for the file, the title and the date before sending; a date after the first view is refused here", async () => {
    const { declareImpl } = open();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Record declaration" })));
    expect(declareImpl).not.toHaveBeenCalled();
    expect(screen.getByText("Choose the file to fingerprint.")).toBeTruthy();
    expect(screen.getByText("Give the evidence a title.")).toBeTruthy();
    expect(screen.getByText("Give the date of the evidence.")).toBeTruthy();
    await chooseFile(fileOf(10));
    await fillRest("Minutes", "2026-10-03");
    expect(declareImpl).not.toHaveBeenCalled();
    expect(screen.getByText("Choose a date on or before 2 Oct 2026.")).toBeTruthy();
  });

  it.each([
    [
      "no_tier2_access_yet",
      403,
      {},
      "The declaration window opens when your organisation first views the full proposal.",
    ],
    [
      "declaration_window_closed",
      403,
      { window_closed_on: "2026-10-16" },
      "The declaration window closed on 16 Oct 2026. Declarations are not recorded on the platform after this window.",
    ],
    ["already_declared", 409, {}, "Your organisation has already declared prior knowledge on this engagement."],
    ["engagement_ended", 409, {}, "This engagement has ended, so no declaration can be recorded on it."],
    ["role_not_allowed", 403, {}, "Only an owner, admin or signatory can declare prior knowledge."],
  ] as const)("says %s (%i) in the sheet, in its own words", async (code, status, extra, words) => {
    const error = { detail: { code, message: "server words", ...extra } };
    const declareImpl = vi.fn(
      async (): Promise<DeclarationOutcome> => ({
        ok: false,
        refusal: declarationRefusal(status, error),
        ...("window_closed_on" in extra ? { closedOn: extra.window_closed_on } : {}),
      }),
    );
    open({ declareImpl });
    await chooseFile(fileOf(10));
    await fillRest();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(words);
    await waitFor(() => expect(document.activeElement).toBe(alert));
  });

  it.each([
    [
      "invalid_evidence_title",
      "Title",
      "Give the title on one line, up to 200 characters, with no invisible characters.",
    ],
    ["evidence_date_in_future", "Date of the evidence", "The date of the evidence cannot be after today."],
    [
      "evidence_after_first_view",
      "Date of the evidence",
      "Prior knowledge comes before your organisation's first view of the full proposal: choose a date on or before 2 Oct 2026.",
    ],
  ] as const)("says %s on its field", async (code, label, words) => {
    const declareImpl = vi.fn(
      async (): Promise<DeclarationOutcome> => ({
        ok: false,
        refusal: declarationRefusal(422, { detail: { code, message: "x" } }),
      }),
    );
    open({ declareImpl });
    await chooseFile(fileOf(10));
    await fillRest();
    const field = screen.getByLabelText(label);
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(field.closest("div")!.textContent).toContain(words);
    expect(document.activeElement).toBe(field);
  });
});

const orgDetail = (prior_knowledge: unknown, overrides = {}) =>
  detail({
    my_party: "org",
    my_roles: ["signatory"],
    prior_knowledge: prior_knowledge as never,
    today: "2026-10-05",
    ...overrides,
  });

async function line(d: ReturnType<typeof detail>) {
  return renderWithIntl(<>{await resolveServerTree(<DeclarationLine detail={d} />)}</>);
}

describe("the declaration sheet's edges (P27 review)", () => {
  /** A digest whose answer the test gives when it chooses. */
  function controllable() {
    const pending: Array<(hex: string) => void> = [];
    const hashImpl = vi.fn(() => new Promise<string>((resolve) => pending.push(resolve)));
    return { hashImpl, answer: (index: number, hex: string) => act(async () => pending[index](hex)) };
  }

  it("keeps the latest file's fingerprint when an earlier, larger one finishes after it", async () => {
    const digest = controllable();
    const { declareImpl } = open({ hashImpl: digest.hashImpl });
    await chooseFile(fileOf(45 * 1024 * 1024, "archive.zip"));
    await chooseFile(fileOf(10, "minutes.pdf"));
    expect(digest.hashImpl).toHaveBeenCalledTimes(2);
    await digest.answer(1, HASH);
    expect(document.querySelector("[data-file-hash]")!.textContent).toBe(HASH);
    // The 45 MB file's digest arrives last: it is dropped.
    await digest.answer(0, "f".repeat(64));
    expect(document.querySelector("[data-file-hash]")!.textContent).toBe(HASH);
    expect(screen.getByText("Fingerprint of minutes.pdf:")).toBeTruthy();
    await fillRest();
    expect((declareImpl as ReturnType<typeof vi.fn>).mock.calls[0][2].evidence_sha256_hex).toBe(HASH);
  });

  it("waits for a fingerprint only on the file way: a pasted hash sends while a file is still hashing", async () => {
    const digest = controllable();
    const { declareImpl } = open({ hashImpl: digest.hashImpl });
    await chooseFile(fileOf(45 * 1024 * 1024));
    const submit = screen.getByRole("button", { name: "Record declaration" });
    expect(submit.getAttribute("aria-disabled")).toBe("true");
    await fillRest();
    expect(declareImpl).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("radio", { name: "Paste a SHA-256" }));
    expect(submit.getAttribute("aria-disabled")).toBeNull();
    fireEvent.change(screen.getByLabelText("SHA-256"), { target: { value: HASH } });
    await act(async () => fireEvent.click(submit));
    expect(declareImpl).toHaveBeenCalledTimes(1);
  });

  it("refuses a title with a control or invisible character before sending, with the field's sentence", async () => {
    for (const bad of [0x200b, 0x202e, 0x00a0, 0x0009]) {
      cleanup();
      const { declareImpl } = open();
      await chooseFile(fileOf(10));
      await fillRest(`Board${String.fromCharCode(bad)}minutes`);
      expect(declareImpl).not.toHaveBeenCalled();
      const title = screen.getByLabelText("Title");
      expect(title.getAttribute("aria-invalid")).toBe("true");
      expect(document.getElementById(`${title.id}-error`)!.textContent).toBe(
        "Give the title on one line, up to 200 characters, with no invisible characters.",
      );
      expect(document.activeElement).toBe(title);
    }
  });

  it.each([
    ["declaration_window_closed", 403, true],
    ["already_declared", 409, true],
    ["engagement_ended", 409, true],
    ["role_not_allowed", 403, false],
    ["no_tier2_access_yet", 403, false],
  ] as const)("closing after %s says the tracker changed: %s", async (code, status, changed) => {
    const declareImpl = vi.fn(
      async (): Promise<DeclarationOutcome> => ({
        ok: false,
        refusal: declarationRefusal(status, { detail: { code, message: "x" } }),
      }),
    );
    const { onClose } = open({ declareImpl });
    await chooseFile(fileOf(10));
    await fillRest();
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledWith(changed);
  });
});

describe("focus after the tracker refreshes", () => {
  function page(sentence: string) {
    document.body.innerHTML = `<div data-turn-card=""><h2 id="actions-heading" tabindex="-1">Your actions</h2>
      <span data-clock="">3 h 12 min</span>
      <section data-declaration="open"><p id="${LINE_ID}" tabindex="-1">${sentence}</p><button>Declare prior knowledge</button></section></div>`;
  }

  it("moves to the declaration line once its words change, and ignores the clock's", async () => {
    page("Your organisation can declare existing similar work until 16 Oct 2026.");
    const button = document.querySelector("button")!;
    button.focus();
    expect(focusLineWhenRefreshed()).not.toBeNull();
    // The clock ticks: not the line.
    document.querySelector("[data-clock]")!.textContent = "3 h 11 min";
    await Promise.resolve();
    expect(document.activeElement).toBe(button);
    // The refresh: the line says it was declared, and the button is gone.
    document.getElementById(LINE_ID)!.textContent = "Your organisation declared prior knowledge on 5 Oct 2026.";
    button.remove();
    await waitFor(() => expect(document.activeElement).toBe(document.getElementById(LINE_ID)));
  });

  it("moves to the actions' heading when the line goes (an ended engagement)", async () => {
    page("Your organisation can declare existing similar work until 16 Oct 2026.");
    focusLineWhenRefreshed();
    document.querySelector("[data-declaration]")!.remove();
    await waitFor(() => expect(document.activeElement).toBe(document.getElementById("actions-heading")));
  });

  it("arms nothing without a line", () => {
    document.body.innerHTML = "";
    expect(focusLineWhenRefreshed()).toBeNull();
  });
});

describe("the declaration line on the organisation's tracker", () => {
  const OPEN = {
    first_tier2_view_at: "2026-10-02T07:00:00Z",
    window_closes_on: "2026-10-16",
    declared_at: null,
    can_declare: true,
  };

  it("offers Declare prior knowledge while it may, as a secondary action, and says until when", async () => {
    const { container } = await line(orgDetail(OPEN));
    const section = container.querySelector("[data-declaration='open']")!;
    expect(section.textContent).toContain("Your organisation can declare existing similar work until 16 Oct 2026.");
    const button = within(section as HTMLElement).getByRole("button", { name: "Declare prior knowledge" });
    expect(button.getAttribute("data-opens")).toBe("declaration");
    expect(button.className).toContain("btn-secondary");
    expect(container.querySelector("[data-primary]")).toBeNull();
  });

  it("before the first full-proposal view: no action, one quiet line", async () => {
    const { container } = await line(
      orgDetail({ first_tier2_view_at: null, window_closes_on: null, declared_at: null, can_declare: false }),
    );
    expect(container.querySelector("[data-declaration='notYet']")!.textContent).toBe(
      "The declaration window opens after your organisation's first full-proposal view.",
    );
    expect(container.querySelector("button")).toBeNull();
  });

  it("after the window: the action gone and the day it closed", async () => {
    const { container } = await line(orgDetail({ ...OPEN, can_declare: false }, { today: "2026-10-17" }));
    expect(container.querySelector("[data-declaration='closed']")!.textContent).toBe(
      "The declaration window closed on 16 Oct 2026.",
    );
    expect(container.querySelector("button")).toBeNull();
  });

  it("once declared, says when; a reviewer inside the window reads who can declare, with no action", async () => {
    const declared = await line(orgDetail({ ...OPEN, can_declare: false, declared_at: "2026-10-05T08:00:00Z" }));
    expect(declared.container.textContent).toBe("Your organisation declared prior knowledge on 5 Oct 2026.");
    cleanup();
    const reviewer = await line(orgDetail({ ...OPEN, can_declare: false }, { my_roles: ["reviewer"] }));
    expect(reviewer.container.textContent).toBe(
      "An owner, admin or signatory of your organisation can declare existing similar work until 16 Oct 2026.",
    );
    expect(reviewer.container.querySelector("button")).toBeNull();
  });

  it("draws nothing on an ended engagement without a declaration, nor for a developer", async () => {
    const ended = await line(orgDetail({ ...OPEN, can_declare: false }, { state: "DECLINED" }));
    expect(ended.container.textContent).toBe("");
    cleanup();
    const dev = await line(detail({ my_party: "developer", prior_knowledge: OPEN as never }));
    expect(dev.container.textContent).toBe("");
  });
});

describe("the developer's declaration panel", () => {
  const RECEIVED = {
    org_name: "Telco A",
    declared_at: "2026-10-05T08:00:00Z",
    evidence_sha256_hex: HASH,
    evidence_title: "Board minutes <i>on</i> the pilot",
    evidence_dated_on: "2025-06-10",
  };

  it("names the organisation and the day, and shows the hash whole, the title as text and the evidence's date", async () => {
    const { container } = renderWithIntl(
      <>{await resolveServerTree(<ReceivedDeclaration detail={detail({ prior_knowledge: RECEIVED as never })} />)}</>,
    );
    const panel = within(container).getByRole("region", {
      name: "Prior-knowledge declaration from Telco A on 5 Oct 2026",
    });
    expect(panel.querySelector("[data-hash]")!.textContent).toBe(HASH);
    expect(panel.querySelector("[data-hash]")!.className).toContain("font-mono");
    expect(panel.textContent).toContain("Board minutes <i>on</i> the pilot");
    expect(panel.querySelector("i")).toBeNull();
    expect(panel.textContent).toContain("10 Jun 2025");
    expect(within(panel).getByRole("link", { name: "What a declaration means" }).getAttribute("href")).toBe(
      "/help#confidential",
    );
  });

  it("is absent without a declaration, and never on the organisation's tracker", async () => {
    const none = renderWithIntl(
      <>{await resolveServerTree(<ReceivedDeclaration detail={detail({ prior_knowledge: null })} />)}</>,
    );
    expect(none.container.textContent).toBe("");
    cleanup();
    const org = renderWithIntl(
      <>
        {await resolveServerTree(
          <ReceivedDeclaration detail={detail({ my_party: "org", prior_knowledge: RECEIVED as never })} />,
        )}
      </>,
    );
    expect(org.container.textContent).toBe("");
  });
});

describe("History", () => {
  it("names the declaration's event (it has no command label)", () => {
    const h = history();
    const event = {
      ...h.events[1],
      id: "x3",
      seq: 3,
      command: "prior_knowledge_declared",
      from_state: null,
      to_state: null,
    };
    const { container } = renderWithIntl(<HistoryList history={{ ...h, events: [...h.events, event as never] }} />);
    expect(container.querySelector("[data-event='prior_knowledge_declared'] h3")!.textContent).toBe(
      "Prior knowledge declared",
    );
  });
});
