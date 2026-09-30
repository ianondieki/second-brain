import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ClientStrings } from "@/components/ClientStrings";
import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { buttonClass } from "@/components/ui/Button";
import { ClockIcon, SendIcon } from "@/components/ui/icons";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { requireMe } from "@/lib/api/server";
import { started } from "@/lib/api/started";
import { homeFor } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";

import { VerificationBadge } from "../../../companies/VerificationBadge";
import { myIdeas } from "../../data";
import { BASE_PATH, ideaHref } from "../../ideas";
import { isProposalId } from "../../routes";
import { ideaStatus } from "../../status";
import { chosenOptions, nicheTree, pickerPage } from "./data";
import { PitchForm, type PickerGroup, type PickerRow } from "./PitchForm";
import {
  orgKey,
  parsePickerQuery,
  pitchesLeft,
  pitchHref,
  type PickerQuery,
  type PitchOption,
  type PitchPicker,
} from "./picker";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pitch");
  return { title: t("pageTitle") };
}

/**
 * Developer › My ideas › Pitch to companies (REQ-PROP-03, REQ-DIR-04; docs/spec/06 6.2 and 6.3). Rendered on the server
 * from GET /api/me/proposals/{id}/pitch/orgs: the directory by niche, each organisation's verification badge and what a
 * tag would do there (sent now to an E2 organisation, saved until an E0 or E1 one verifies) or why it cannot be pitched,
 * and the plan's cap. A published idea that is clear of review can be pitched; any other says why in one sentence.
 * Its own route, so the idea page does not carry the picker's code (docs/spec/07 item 5).
 */
export default async function PitchPage({ params, searchParams }: PageProps<"/dev/ideas/[id]/pitch">) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("pitch");
  const { id } = await params;
  const query = parsePickerQuery(await searchParams);

  const shell = (children: ReactNode) => (
    <SignedInShell homeHref={home} nav={<DevNav current="ideas" />} wide>
      {children}
    </SignedInShell>
  );

  // The list of ideas carries the title and status without reading the confidential details (that read is audited).
  // The picker's page and the niche tree are read alongside it (owner-scoped reads without side effects: the API
  // answers 404 for an idea that is not yours) and awaited only once the idea is found and can be pitched.
  const valid = isProposalId(id);
  const pickerRead = valid ? started(pickerPage(id, query)) : null;
  const nichesRead = valid ? started(nicheTree()) : null;
  const idea = valid ? (await myIdeas()).find((item) => item.id === id) : undefined;
  if (!idea || !pickerRead || !nichesRead) {
    return shell(
      <Header>
        <EmptyState className="mt-8" sentence={t("notFound")} action={t("allIdeas")} href={BASE_PATH} />
      </Header>,
    );
  }
  const back = ideaHref(idea.id);
  const status = ideaStatus(idea.status, idea.moderation_state);
  const header = (children: ReactNode) =>
    shell(
      <Header back={back} title={idea.title}>
        {children}
      </Header>,
    );
  if (status !== "published") {
    return header(<EmptyState className="mt-8" sentence={t(`blocked.${status}`)} action={t("back")} href={back} />);
  }

  const [page, niches] = await Promise.all([pickerRead, nichesRead]);
  if (page.kind === "notFound") return header(<EmptyState className="mt-8" sentence={t("notFound")} action={t("allIdeas")} href={BASE_PATH} />);
  if (page.kind === "staleCursor") {
    const first = pitchHref(idea.id, { ...query, cursor: undefined });
    return header(<EmptyState className="mt-8" sentence={t("staleCursor")} action={t("firstPage")} href={first} />);
  }
  const { picker } = page;
  // Published but not public to the API: moderation changed after the list was read.
  if (!picker.proposal_public) return header(<EmptyState className="mt-8" sentence={t("blocked.held")} action={t("back")} href={back} />);
  if (pitchesLeft(picker.cap) === 0) {
    return header(<EmptyState className="mt-8" sentence={t("capUsed", { limit: picker.cap.limit ?? 0 })} action={t("back")} href={back} />);
  }
  const groups = await pickerGroups(picker);
  // Choices made on another page or search, resolved by id so each is shown by name with its outcome (else dropped).
  const onPage = new Set(groups.flatMap((group) => group.rows.map((row) => row.id)));
  const offPage = query.selected.filter((id) => !onPage.has(orgKey(id)));
  const chosen = await Promise.all((await chosenOptions(idea.id, offPage)).map(pickerRow));
  const narrowed = Boolean(query.q || query.niche);
  if (groups.length === 0 && !query.cursor) {
    return header(
      narrowed ? (
        <EmptyState
          className="mt-8"
          sentence={t("emptyFiltered")}
          action={t("clear")}
          href={pitchHref(idea.id, { selected: query.selected })}
        />
      ) : (
        <EmptyState className="mt-8" sentence={t("emptyAll")} action={t("back")} href={back} />
      ),
    );
  }

  return header(
    <>
      <ClientStrings strings={await clientStrings(["pitch"])}>
        <PitchForm
          // A new search or page is a new form: choices come from the URL, nothing else carries over.
          key={JSON.stringify(query)}
          proposalId={idea.id}
          ideaHref={back}
          cap={picker.cap}
          groups={groups}
          chosen={chosen}
          initialSelected={query.selected}
          filters={<Filters query={query} niches={niches} />}
          narrowed={narrowed}
          cursor={query.cursor}
          nextCursor={picker.next_cursor}
        />
      </ClientStrings>
    </>,
  );
}

async function Header({ back, title, children }: { back?: string; title?: string | null; children: ReactNode }) {
  const t = await getTranslations("pitch");
  const ideas = await getTranslations("ideas");
  return (
    <>
      <PageHeader
        back={{ href: back ?? BASE_PATH, label: back ? t("back") : t("allIdeas") }}
        title={t("title")}
        lead={back ? t("forIdea", { title: title?.trim() || ideas("untitled") }) : undefined}
      />
      {children}
    </>
  );
}

type NicheNode = Awaited<ReturnType<typeof nicheTree>>[number];

/** Search and niche, as fields of the picker's GET form (the choices travel with them as `sel`). */
async function Filters({ query, niches }: { query: PickerQuery; niches: NicheNode[] }) {
  const t = await getTranslations("pitch");
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
      <div className="min-w-0 flex-1">
        <TextField
          id="pitch-q"
          name="q"
          type="search"
          label={t("searchLabel")}
          defaultValue={query.q}
          maxLength={100}
          autoComplete="off"
          enterKeyHint="search"
        />
      </div>
      <div className="sm:w-64">
        <SelectField id="pitch-niche" name="niche" label={t("nicheLabel")} defaultValue={query.niche ?? ""}>
          <option value="">{t("nicheAll")}</option>
          {niches.map((parent) =>
            parent.children.length > 0 ? (
              <optgroup key={parent.id} label={parent.name}>
                <option value={parent.slug}>{t("nicheAllIn", { name: parent.name })}</option>
                {parent.children.map((child) => (
                  <option key={child.id} value={child.slug}>
                    {child.name}
                  </option>
                ))}
              </optgroup>
            ) : (
              <option key={parent.id} value={parent.slug}>
                {parent.name}
              </option>
            ),
          )}
        </SelectField>
      </div>
      {/* The form's first submit button, so Enter in the search box searches rather than pitches. */}
      <button type="submit" className={buttonClass("secondary", "shrink-0")}>
        {t("search")}
      </button>
    </div>
  );
}

/** The picker's groups with each row's details drawn here: type and county, the badge, and the outcome or the reason. */
async function pickerGroups(picker: PitchPicker): Promise<PickerGroup[]> {
  const t = await getTranslations("pitch");
  return Promise.all(
    picker.groups
      .filter((group) => group.orgs.length > 0)
      .map(async (group, index) => {
        return {
          key: `${group.niche?.id ?? "none"}-${index}`,
          name: group.niche ? group.niche.label : t("noNiche"),
          rows: await Promise.all(group.orgs.map(pickerRow)),
        };
      }),
  );
}

/** One organisation as a picker row: type, county and badge, then the outcome or the reason, drawn here. */
async function pickerRow(option: PitchOption): Promise<PickerRow> {
  const companies = await getTranslations("companies");
  const kinds = await getTranslations("orgKind");
  const { card } = option;
  const kind = kinds(card.kind);
  return {
    id: orgKey(card.id),
    name: card.name,
    available: option.available,
    about: (
      <>
        <p className="text-sm text-ink-soft">{card.county ? companies("meta", { kind, county: card.county.name }) : kind}</p>
        <VerificationBadge badge={card.badge} />
      </>
    ),
    outcome: <Outcome option={option} />,
  };
}

async function Outcome({ option }: { option: PitchOption }) {
  const t = await getTranslations("pitch");
  const { card } = option;
  return (
    <>
      {!option.available && option.reason ? (
        <p className="text-sm text-ink" data-reason={option.reason}>
          {t(`reason.${option.reason}`, { name: card.name })}
        </p>
      ) : option.outcome === "delivered" ? (
        <p>
          <Badge data-outcome="sent" tone="ok" icon={<SendIcon />}>
            {t("outcomeSent")}
          </Badge>
        </p>
      ) : (
        <p>
          <Badge data-outcome="saved" tone="neutral" icon={<ClockIcon />}>
            {t("outcomeSaved")}
          </Badge>
        </p>
      )}
    </>
  );
}
