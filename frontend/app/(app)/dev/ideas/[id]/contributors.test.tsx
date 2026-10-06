import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { CertificateSheet } from "@/components/certificate/CertificateSheet";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { ContributorsLine } from "./ContributorsLine";

// REQ-DEV-03 (P22-CF; D-62 (a)): "Contributors: <handles>" on the certificate sheet after "Registered by …" (handles
// only, nothing about shares) and on the owner's idea page, each handle with Remove behind a confirmation.

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }) }));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
afterEach(cleanup);

const SHEET = {
  title: "Fuel-level alerts for off-grid tower sites",
  ownerName: "Amina Wanjiru",
  versionNo: 1,
  certId: "HC9DHW2W2617RZ3T",
  registeredAt: "2026-10-06T16:54:00Z",
  stamped: true,
  verifyUrl: "/verify/HC9DHW2W2617RZ3T",
};

describe("the certificate sheet", () => {
  it("lists the contributors after the registrant, by handle only", async () => {
    render(await resolveServerTree(await CertificateSheet({ ...SHEET, contributors: ["dev-kb3dysnk", "dev-5jtjq2m3"] })));
    const line = document.querySelector("[data-certificate-contributors]") as HTMLElement;
    expect(line.textContent).toBe("Contributors: dev-kb3dysnk and dev-5jtjq2m3");
    // Right after "Registered by …", and the registrant stays the one person.
    expect(line.previousElementSibling?.textContent).toBe("Registered by Amina Wanjiru, version 1");
    expect(document.body.textContent).not.toMatch(/share/i);
  });

  it("has no contributors line when there are none", async () => {
    render(await resolveServerTree(await CertificateSheet(SHEET)));
    expect(document.querySelector("[data-certificate-contributors]")).toBeNull();
  });
});

describe("the idea page's contributors line", () => {
  const CREDITED = [
    { user_id: "01a11222-e68f-71fd-aa2e-f66d099bfab0", handle: "dev-kb3dysnk" },
    { user_id: "01a11222-e704-715c-94b6-403e7159f446", handle: "dev-5jtjq2m3" },
  ];

  it("shows the handles with Remove each, which asks first and says what happens", async () => {
    const remove = vi.fn(async () => true);
    renderWithIntl(<ContributorsLine ideaId="idea-1" initial={CREDITED} remove={remove} />);
    const line = document.querySelector("[data-contributors]") as HTMLElement;
    expect(line.textContent).toContain("Contributors: dev-kb3dysnk");
    const first = line.querySelector('[data-contributor="dev-kb3dysnk"]') as HTMLElement;
    fireEvent.click(within(first).getByRole("button", { name: "Remove" }));
    const dialog = screen.getByRole("dialog", { name: "Remove dev-kb3dysnk as a contributor?" });
    expect(dialog.textContent).toContain(en.ideaContributors.confirmBody);
    expect(remove).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Remove" })));
    expect(remove).toHaveBeenCalledWith("idea-1", CREDITED[0].user_id);
    expect(document.querySelector('[data-contributor="dev-kb3dysnk"]')).toBeNull();
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("dev-kb3dysnk is no longer a contributor on this idea.");
    await waitFor(() => expect(document.activeElement).toBe(status));
    expect(refresh).toHaveBeenCalled();
  });

  it("a failed removal stays in the dialog with one sentence", async () => {
    renderWithIntl(<ContributorsLine ideaId="idea-1" initial={CREDITED} remove={vi.fn(async () => false)} />);
    fireEvent.click(within(document.querySelector('[data-contributor="dev-5jtjq2m3"]') as HTMLElement).getByRole("button", { name: "Remove" }));
    const dialog = screen.getByRole("dialog", { name: "Remove dev-5jtjq2m3 as a contributor?" });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Remove" })));
    expect(within(dialog).getByRole("alert").textContent).toBe(en.ideaContributors.failed);
    expect(document.querySelector('[data-contributor="dev-5jtjq2m3"]')).not.toBeNull();
  });
});
