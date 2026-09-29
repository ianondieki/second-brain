import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { fingerprintGroups, formatKenyan, normaliseCertId, tokenHref, type CertificateCheck } from "./certificate";
import { FileCheck } from "./FileCheck";
import { checkFile, fileProblem, type FileOutcome } from "./upload";
import { VerifyRecord } from "./VerifyRecord";

// REQ-PROV-02 (F3): the public /verify screens. docs/spec/06 6.4 item 2: hash, timestamp, TSA serial and match only
// (plus signature and key id, approved in T2.4 review); never the owner or the title (D-33 default).

afterEach(cleanup);

const HASH = "03ed86af3435a56375e52570f69d97cbee68cadf4c63d75ab69112204108c789";
const RECORD: CertificateCheck = {
  cert_id: "TXEMFBJ89RRTQS87",
  status: "timestamped",
  status_label: "Timestamped",
  content_hash: HASH,
  timestamp: "2026-09-29T11:06:25Z",
  tsa_serial: "0x01",
  key_id: "ed25519:e60ca1fa824c4587",
  signature: "yOb8f/tzOczTbHQKg5eZY9ru2rIRb/26WUfNJKBr0LtcFTgXeoDKO6d/BOQCRSLT5iDow/VUlOTTf+P/lWtYDw==",
};
const PENDING: CertificateCheck = {
  ...RECORD,
  status: "timestamp_pending",
  status_label: "Timestamp pending",
  timestamp: null,
  tsa_serial: null,
};

describe("certificate ids", () => {
  it.each([
    ["TXEMFBJ89RRTQS87", "TXEMFBJ89RRTQS87"],
    ["txemfbj89rrtqs87", "TXEMFBJ89RRTQS87"],
    [" TXEM-FBJ8 9RRT–QS87 ", "TXEMFBJ89RRTQS87"],
    ["ABCDEFGH", "ABCDEFGH"],
  ])("tidies %j to %s", (typed, id) => {
    expect(normaliseCertId(typed)).toBe(id);
  });

  it.each(["", "short", "A".repeat(25), "not an id!", "ABCD/EFGH1", "../../api", undefined, null])(
    "refuses %j without a request",
    (typed) => {
      expect(normaliseCertId(typed)).toBeNull();
    },
  );

  it("splits a fingerprint into eight groups of eight and builds the token link", () => {
    expect(fingerprintGroups(HASH)).toEqual([
      "03ed86af",
      "3435a563",
      "75e52570",
      "f69d97cb",
      "ee68cadf",
      "4c63d75a",
      "b6911220",
      "4108c789",
    ]);
    expect(tokenHref("TXEMFBJ89RRTQS87")).toBe("/api/verify/TXEMFBJ89RRTQS87/timestamp.tsr");
  });

  it("writes times day first, in Nairobi time (UTC+3)", () => {
    const text = formatKenyan("en", new Date(RECORD.timestamp!), {
      dateStyle: "long",
      timeStyle: "medium",
      timeZone: "Africa/Nairobi",
    });
    expect(text).toMatch(/^29 September 2026\b/);
    expect(text).toContain("14:06:25");
  });
});

describe("VerifyRecord", () => {
  it("shows the evidence: status, fingerprint, both times, serial, key, signature and the token", () => {
    const { container } = renderWithIntl(<VerifyRecord record={RECORD} />);
    expect(screen.getByTestId("verify-status").textContent).toContain("Timestamped");
    const fingerprint = container.querySelector("[data-fingerprint]");
    expect(fingerprint?.getAttribute("data-fingerprint")).toBe(HASH);
    expect(fingerprint?.textContent).toBe(HASH); // copies as one string, no spaces
    expect(screen.getByText(/29 September 2026 at 14:06:25 Nairobi time/)).toBeTruthy();
    expect(screen.getByText(/11:06:25 UTC/)).toBeTruthy();
    expect(container.querySelector("time")?.getAttribute("dateTime")).toBe(RECORD.timestamp);
    const terms = screen.getAllByRole("term").map((term) => term.textContent);
    expect(terms).toEqual(["Timestamp", "Timestamp serial number", "Signing key ID", "Signature (Ed25519)"]);
    expect(screen.getByText("0x01")).toBeTruthy();
    expect(screen.getByText(RECORD.key_id!)).toBeTruthy();
    expect(screen.getByText(RECORD.signature!)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download the timestamp token (.tsr)" }).getAttribute("href")).toBe(
      "/api/verify/TXEMFBJ89RRTQS87/timestamp.tsr",
    );
    expect(screen.getByRole("link", { name: "See the published signing keys" }).getAttribute("href")).toBe(
      "/.well-known/provenance-keys.json",
    );
    expect(screen.getByText(en.verify.evidence)).toBeTruthy();
    expect(screen.getByText(en.verify.private)).toBeTruthy();
  });

  it("gives each stacked record link its own 44 px band (no shared tap area)", () => {
    renderWithIntl(<VerifyRecord record={RECORD} />);
    const links = within(screen.getByTestId("record-links")).getAllByRole("link");
    expect(links).toHaveLength(2);
    for (const link of links) {
      const classes = link.className.split(" ");
      expect(classes).toEqual(expect.arrayContaining(["inline-flex", "min-h-11", "items-center"]));
      expect(classes).not.toContain("py-2.5"); // the in-sentence padding that made neighbouring boxes overlap
    }
  });

  it("says a pending timestamp is pending and offers no token", () => {
    renderWithIntl(<VerifyRecord record={PENDING} />);
    expect(screen.getByTestId("verify-status").textContent).toContain("Timestamp pending");
    expect(screen.getByText(en.verify.explainPending)).toBeTruthy();
    expect(screen.getAllByText("Not available yet")).toHaveLength(2); // timestamp and serial
    expect(screen.queryByRole("link", { name: /timestamp token/ })).toBeNull();
  });

  it("never claims legal protection (docs/spec/04 principle 2)", () => {
    const { container } = renderWithIntl(<VerifyRecord record={RECORD} />);
    expect(container.textContent).not.toMatch(/theft[\s-]?proof|cannot be stolen|protected idea|\bpatented\b/i);
  });
});

describe("checkFile", () => {
  const file = new Blob(["{}"], { type: "application/json" });

  it("posts the raw bytes, against one certificate when given", async () => {
    const send = vi.fn(async () => Response.json({ match: false, content_hash: HASH, certificate: null }));
    const outcome = await checkFile(file, "TXEMFBJ89RRTQS87", send);
    expect(outcome).toEqual({ ok: true, result: { match: false, content_hash: HASH, certificate: null } });
    const [url, init] = send.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/verify?cert_id=TXEMFBJ89RRTQS87");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(file);
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/octet-stream");
  });

  it("matches against every record without a certificate id", async () => {
    const send = vi.fn(async () => Response.json({ match: true, content_hash: HASH, certificate: RECORD }));
    await checkFile(file, undefined, send);
    expect((send.mock.calls[0] as unknown as [string])[0]).toBe("/api/verify");
  });

  it.each<[number | "throw", FileOutcome]>([
    [413, { ok: false, problem: "tooLarge" }],
    [429, { ok: false, problem: "rateLimited" }],
    [404, { ok: false, problem: "failed" }],
    [500, { ok: false, problem: "failed" }],
    ["throw", { ok: false, problem: "network" }],
  ])("maps %s to a message", async (status, outcome) => {
    const send = vi.fn(async () => {
      if (status === "throw") throw new TypeError("offline");
      return Response.json({ detail: { code: "x", message: "x" } }, { status });
    });
    expect(await checkFile(file, undefined, send)).toEqual(outcome);
  });

  it("stops before sending when no file is chosen or it is over 10 MB", () => {
    expect(fileProblem(undefined)).toBe("noFile");
    const big = new File(["x"], "big.json");
    Object.defineProperty(big, "size", { value: 10 * 1024 * 1024 + 1 });
    expect(fileProblem(big)).toBe("tooLarge");
    expect(fileProblem(new File(["{}"], "manifest.json"))).toBeNull();
  });
});

describe("FileCheck", () => {
  function choose(file: File) {
    fireEvent.change(screen.getByLabelText("Manifest file"), { target: { files: [file] } });
  }

  it("asks for a file at the field when none is chosen", async () => {
    const checkFileImpl = vi.fn();
    renderWithIntl(<FileCheck checkFileImpl={checkFileImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Check file" }));
    expect(await screen.findByText("Choose a file first.")).toBeTruthy();
    expect(screen.getByLabelText("Manifest file").getAttribute("aria-invalid")).toBe("true");
    expect(checkFileImpl).not.toHaveBeenCalled();
  });

  it("shows a match with the file's fingerprint and a link to the certificate", async () => {
    const checkFileImpl = vi.fn(
      async (): Promise<FileOutcome> => ({
        ok: true,
        result: { match: true, content_hash: HASH, certificate: RECORD },
      }),
    );
    const { container } = renderWithIntl(<FileCheck checkFileImpl={checkFileImpl} />);
    choose(new File(["{}"], "manifest.json"));
    fireEvent.click(screen.getByRole("button", { name: "Check file" }));
    const status = await screen.findByRole("status");
    await waitFor(() => expect(within(status).getByTestId("file-result")).toBeTruthy());
    expect(screen.getByTestId("file-result").textContent).toContain("This file matches certificate TXEMFBJ89RRTQS87.");
    expect(container.querySelector(`[data-fingerprint="${HASH}"]`)).not.toBeNull();
    expect(screen.getByRole("link", { name: "View certificate TXEMFBJ89RRTQS87" }).getAttribute("href")).toBe(
      "/verify/TXEMFBJ89RRTQS87",
    );
    expect(checkFileImpl).toHaveBeenCalledWith(expect.any(File), undefined);
  });

  it("on a certificate page checks against that certificate and is the primary action", async () => {
    const checkFileImpl = vi.fn(
      async (): Promise<FileOutcome> => ({ ok: true, result: { match: false, content_hash: HASH, certificate: null } }),
    );
    renderWithIntl(<FileCheck certId="TXEMFBJ89RRTQS87" primary checkFileImpl={checkFileImpl} />);
    expect(screen.getByRole("button", { name: "Check file" }).hasAttribute("data-primary")).toBe(true);
    choose(new File(["{}"], "manifest.json"));
    fireEvent.click(screen.getByRole("button", { name: "Check file" }));
    expect((await screen.findByTestId("file-result")).textContent).toContain(
      "This file does not match this certificate.",
    );
    expect(checkFileImpl).toHaveBeenCalledWith(expect.any(File), "TXEMFBJ89RRTQS87");
    expect(screen.queryByRole("link", { name: /View certificate/ })).toBeNull();
  });

  it("reports a throttled check as an alert", async () => {
    const checkFileImpl = vi.fn(async (): Promise<FileOutcome> => ({ ok: false, problem: "rateLimited" }));
    renderWithIntl(<FileCheck checkFileImpl={checkFileImpl} />);
    expect(screen.getByRole("button", { name: "Check file" }).hasAttribute("data-primary")).toBe(false);
    choose(new File(["{}"], "manifest.json"));
    fireEvent.click(screen.getByRole("button", { name: "Check file" }));
    expect((await screen.findByRole("alert")).textContent).toContain(en.verifyFile.rateLimited);
  });
});
