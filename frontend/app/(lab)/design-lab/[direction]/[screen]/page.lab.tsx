import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { asTheme, DIRECTION, isDirection } from "../../directions";
import { LabBar } from "../../LabBar";
import { CertificateScreen } from "../../screens/Certificate";
import { CheckoutScreen } from "../../screens/Checkout";
import { EmailScreen } from "../../screens/Email";
import { HomeScreen } from "../../screens/Home";
import { isScreen } from "../../screens";
import { LandingScreen } from "../../screens/Landing";
import { ProposalScreen } from "../../screens/Proposal";
import { TokensScreen } from "../../screens/Tokens";
import { TrackerScreen } from "../../screens/Tracker";

type Props = { params: Promise<{ direction: string; screen: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { direction, screen } = await params;
  return { title: `Design lab ${direction.toUpperCase()} · ${screen}`, robots: { index: false } };
}

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/**
 * One screen under one direction: `/design-lab/<a|b|c>/<screen>?theme=dark&bare=1`. The wrapper carries the
 * direction and theme as data attributes that directions.ts's token sheet and lab.css key on; everything inside is
 * the product's own components on fixture data.
 */
export default async function LabScreen({ params, searchParams }: Props) {
  const [{ direction, screen }, query] = await Promise.all([params, searchParams]);
  if (!isDirection(direction) || !isScreen(screen)) notFound();
  const theme = asTheme(query.theme);
  const bare = one(query.bare) === "1";
  const d = DIRECTION[direction];
  return (
    <div data-direction={direction} data-theme={theme} data-screen={screen} className="flex min-h-dvh flex-col">
      {bare ? null : <LabBar direction={direction} screen={screen} theme={theme} />}
      <p className="sr-only">
        {d.name}, {theme}
      </p>
      {screen === "landing" ? <LandingScreen /> : null}
      {screen === "home" ? <HomeScreen /> : null}
      {screen === "certificate" ? <CertificateScreen direction={direction} /> : null}
      {screen === "tracker" ? <TrackerScreen /> : null}
      {screen === "proposal" ? <ProposalScreen /> : null}
      {screen === "checkout" ? <CheckoutScreen succeeded={one(query.variant) === "success"} /> : null}
      {screen === "email" ? <EmailScreen direction={direction} theme={theme} /> : null}
      {screen === "tokens" ? <TokensScreen direction={direction} theme={theme} /> : null}
    </div>
  );
}
