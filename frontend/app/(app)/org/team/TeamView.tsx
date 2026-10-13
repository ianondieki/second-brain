import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { DemoLocked } from "@/components/DemoLocked";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { standaloneLinkClass } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { EmptyState } from "@/components/ui/EmptyState";
import { Section } from "@/components/ui/Section";

import { formatDay } from "../format";
import { EscalationContact } from "./EscalationContact";
import { InvitationActions } from "./InvitationActions";
import { InviteForm } from "./InviteForm";
import { MemberActions } from "./MemberActions";
import { NicheDefaults } from "./NicheDefaults";
import {
  grantableRoles,
  isOwner,
  manages,
  MAX_OPEN_INVITATIONS,
  mayRemove,
  nicheRows,
  reviewerChoices,
  roleWords,
  sortRoles,
  splitRoles,
  type OpenInvitation,
  type OrgVerification,
  type Paywall,
  type OrgRole,
  type OrgTeam,
  type TeamMember,
} from "./team";

export interface TeamViewProps {
  team: OrgTeam;
  orgId: string;
  orgName: string;
  /** The signed-in person: their id (the "You" mark), their roles here and whether two-step sign-in is on. */
  me: { userId: string; roles: readonly string[]; enrolled: boolean };
  /** The organisation's niches, as its directory card lists them. */
  niches: readonly { slug: string; label: string }[];
  /** The seats paywall's links (team.ts Paywall). */
  paywall?: Paywall;
  /** The organisation's verification level, or null when it could not be read. */
  verification?: OrgVerification | null;
  /**
   * The public demo is on: invitations, removals and role changes are switched off (the API refuses them), so those
   * controls are one calm line instead; the niche defaults and the escalation contact stay open.
   */
  demo: boolean;
}

/**
 * Organisation › Team below its hero (REQ-TEN-02; docs/spec/07 item 1): Members, then for owners and admins the
 * Invitations, then New engagements (the default reviewer per niche) and Escalations (the escalation contact). Every
 * member reads all of it; only owners and admins get the controls (role changes are an owner's alone), each a small
 * client island of its own. In the public demo every control is the calm "switched off" line instead.
 */
export async function TeamView({
  team,
  orgId,
  orgName,
  me,
  niches,
  paywall,
  verification = null,
  demo,
}: TeamViewProps) {
  const [t, ta, locale] = await Promise.all([getTranslations("orgTeam"), getTranslations("teamAdmin"), getLocale()]);
  const manager = manages(me.roles);
  // Membership changes (invite, remove, roles) are switched off in the public demo; the settings below them are not.
  const admin = manager && !demo;
  const label = (role: OrgRole) => ta(`role.${role}`);
  const locked = <DemoLocked variant="change" className="mt-4" />;
  // Invitations open once the organisation is verified (E1 or E2; the API answers 403 org_not_verified before): an
  // unknown level (unread) leaves the form, and the API's answer says the same if it comes to that.
  const unverified = verification !== null && verification !== "e1" && verification !== "e2";
  const grantable = grantableRoles(me.roles);
  const names = new Map(team.members.map((m) => [m.user_id, m.name]));
  const rows = nicheRows(niches, team.niche_defaults);
  const choices = reviewerChoices(team.members).map(({ user_id, name }) => ({ user_id, name }));

  return (
    <div className="flex max-w-3xl flex-col gap-12 lg:gap-14">
      <Section
        title={t("membersTitle")}
        headingId="team-members"
        focusable
        description={t("membersCount", { count: team.members.length })}
        data-team="members"
      >
        <ul className="flex flex-col">
          {team.members.map((member) => (
            <li key={member.user_id} className="border-t border-line py-5 first:border-t-0 first:pt-1">
              <MemberRow
                member={member}
                self={member.user_id === me.userId}
                roleLabel={label}
                locale={locale}
                actions={
                  admin ? (
                    <MemberActions
                      orgId={orgId}
                      orgName={orgName}
                      member={{ user_id: member.user_id, name: member.name, roles: member.roles }}
                      canChangeRoles={isOwner(me.roles)}
                      canRemove={member.user_id !== me.userId && mayRemove(me.roles, member)}
                      enrolled={me.enrolled}
                    />
                  ) : null
                }
              />
            </li>
          ))}
        </ul>
        {demo && manager ? (
          locked
        ) : !admin ? (
          <p className="mt-4 text-sm text-ink-soft">{t("readOnly")}</p>
        ) : null}
      </Section>

      {team.invitations ? (
        <Section
          title={t("invitationsTitle")}
          headingId="team-invitations"
          description={t("invitationsLead", { limit: MAX_OPEN_INVITATIONS })}
          data-team="invitations"
        >
          {!admin ? (
            locked
          ) : unverified ? (
            <Callout data-invite-unverified="">
              <p>{ta("refusal.org_not_verified")}</p>
              <Link href="/help" className={standaloneLinkClass}>
                {ta("verificationHelp")}
              </Link>
            </Callout>
          ) : openCount(team.invitations) >= MAX_OPEN_INVITATIONS ? (
            <Callout data-invite-cap="">
              <p>{t("capReached", { limit: MAX_OPEN_INVITATIONS })}</p>
            </Callout>
          ) : (
            <div className="rounded-panel border border-line bg-field p-5 sm:p-6">
              <h3 className="mb-4 text-lg text-ink">{t("inviteTitle")}</h3>
              <InviteForm
                orgId={orgId}
                roles={grantable}
                enrolled={me.enrolled}
                paywall={paywall}
              />
            </div>
          )}
          {team.invitations.length > 0 ? (
            <div className="mt-8">
              <h3 className="text-lg text-ink">{t("openTitle", { count: team.invitations.length })}</h3>
              <ul className="mt-2 flex flex-col">
                {/* Keyed by address (one open invitation per address): a resent invitation has a new id, and its row
                    keeps its "sent" line across the re-read. */}
                {team.invitations.map((invitation) => (
                  <li key={invitation.email} className="border-t border-line py-5 first:border-t-0">
                    <InvitationRow
                      invitation={invitation}
                      roles={roleWords(invitation.roles, label, locale)}
                      locale={locale}
                      actions={
                        // Only an invitation this person could have sent: an admin does not resend or revoke an
                        // owner's or a signatory's (the API refuses it; the controls are not offered).
                        admin && invitation.roles.every((role) => grantable.includes(role)) ? (
                          <InvitationActions
                            orgId={orgId}
                            invitationId={invitation.id}
                            email={invitation.email}
                            enrolled={me.enrolled}
                            paywall={paywall}
                          />
                        ) : null
                      }
                    />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Section>
      ) : null}

      <Section
        title={t("defaultsTitle")}
        headingId="team-defaults"
        description={t("defaultsLead")}
        data-team="defaults"
      >
        {rows.length === 0 ? (
          <EmptyState sentence={t("noNiches")} action={t("noNichesAction")} href="/help" />
        ) : manager ? (
          <NicheDefaults orgId={orgId} rows={rows} choices={choices} enrolled={me.enrolled} />
        ) : (
          <DescriptionList aria-label={t("defaultsLabel")}>
            {rows.map((row) => (
              <Description key={row.slug} label={row.name}>
                <span data-niche-default={row.slug} className={row.userId ? undefined : "text-ink-soft"}>
                  {row.userId ? (names.get(row.userId) ?? t("notSet")) : t("notSet")}
                </span>
              </Description>
            ))}
          </DescriptionList>
        )}
      </Section>

      <Section
        title={t("escalationTitle")}
        headingId="team-escalation"
        description={t("escalationLead")}
        data-team="escalation"
      >
        {manager ? (
          <EscalationContact
            orgId={orgId}
            members={team.members.map(({ user_id, name }) => ({ user_id, name }))}
            current={team.escalation_contact?.user_id ?? null}
            enrolled={me.enrolled}
          />
        ) : (
          <p className="text-ink" data-escalation-contact={team.escalation_contact?.user_id ?? ""}>
            {team.escalation_contact ? t("escalationIs", { name: team.escalation_contact.name }) : t("escalationNone")}
          </p>
        )}
      </Section>
    </div>
  );
}

/** Open invitations still counting against the cap (an expired one does not: the API revokes it when re-invited). */
function openCount(invitations: readonly OpenInvitation[]): number {
  return invitations.filter((invitation) => !invitation.expired).length;
}

/**
 * One member: their initials, name (and "You"), the email (owners and admins only), when they joined, and their roles
 * as at most two chips with the rest named after them; the actions island beside it from 640 px, under it on a phone.
 */
async function MemberRow({
  member,
  self,
  roleLabel,
  locale,
  actions,
}: {
  member: TeamMember;
  self: boolean;
  roleLabel: (role: OrgRole) => string;
  locale: string;
  actions: ReactNode;
}) {
  const t = await getTranslations("orgTeam");
  const { chips, rest } = splitRoles(member.roles);
  return (
    <article
      className="grid gap-x-6 gap-y-3 sm:grid-cols-[minmax(0,1fr)_auto]"
      data-member={member.user_id}
      aria-labelledby={`member-${member.user_id}`}
    >
      <div className="flex min-w-0 items-start gap-3.5">
        <Avatar name={member.name} active={self} className="mt-0.5 shrink-0" />
        <div className="flex min-w-0 flex-col gap-1.5">
          <h3 id={`member-${member.user_id}`} className="text-base font-semibold [overflow-wrap:anywhere] text-ink">
            {member.name}
            {self ? <span className="ml-2 text-sm font-medium text-ink-soft">{t("you")}</span> : null}
          </h3>
          <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-sm text-ink-soft">
            {member.email ? <span className="[overflow-wrap:anywhere]">{member.email}</span> : null}
            <span>{t("joined", { date: formatDay(locale, member.joined_at) })}</span>
          </p>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5" data-roles={sortRoles(member.roles).join(" ")}>
            {chips.map((role) => (
              <Badge key={role} tone={role === "owner" || role === "admin" ? "accent" : "neutral"} data-chip={role}>
                {roleLabel(role)}
              </Badge>
            ))}
            {rest.length > 0 ? (
              <span className="text-sm text-ink-soft">
                {t("alsoRoles", { roles: roleWords(rest, roleLabel, locale) })}
              </span>
            ) : null}
          </div>
        </div>
      </div>
      {actions}
    </article>
  );
}

/** One open invitation: the address, its roles in words, who sent it and until when its link works (or that it expired). */
async function InvitationRow({
  invitation,
  roles,
  locale,
  actions,
}: {
  invitation: OpenInvitation;
  roles: string;
  locale: string;
  actions: ReactNode;
}) {
  const t = await getTranslations("orgTeam");
  const sent = formatDay(locale, invitation.created_at);
  const until = formatDay(locale, invitation.expires_at);
  return (
    <article className="grid gap-x-6 gap-y-3 sm:grid-cols-[minmax(0,1fr)_auto]" data-invitation={invitation.email}>
      <div className="flex min-w-0 flex-col gap-1.5">
        <h4 className="text-base font-semibold [overflow-wrap:anywhere] text-ink">{invitation.email}</h4>
        <p className="text-sm text-ink first-letter:uppercase">{roles}</p>
        <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-sm text-ink-soft">
          <span>{t("invitedBy", { name: invitation.invited_by_name, date: sent })}</span>
          {invitation.expired ? null : <span>{t("expiresOn", { date: until })}</span>}
        </p>
        {invitation.expired ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <Badge tone="warm" data-chip="expired">
              {t("expired")}
            </Badge>
            <span className="text-sm text-ink-soft">{t("expiredOn", { date: until })}</span>
          </div>
        ) : null}
      </div>
      {actions}
    </article>
  );
}
