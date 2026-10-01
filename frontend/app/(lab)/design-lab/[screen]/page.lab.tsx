import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LabBar } from "../LabBar";
import { CertificateScreen } from "../screens/Certificate";
import { CheckoutScreen } from "../screens/Checkout";
import { HomeScreen } from "../screens/Home";
import { isScreen } from "../screens";
import { LandingScreen } from "../screens/Landing";
import { ProposalScreen } from "../screens/Proposal";
import { TrackerScreen } from "../screens/Tracker";

type Props = { params: Promise<{ screen: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return { title: `Design lab · ${(await params).screen}`, robots: { index: false } };
}

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/**
 * One product screen on fixture data: `/design-lab/<screen>?bare=1` (dark mode through the app's own appearance
 * setting; frontend/scripts/design-lab-shots.mjs sets it before each shot). Everything inside is the product's own
 * components; nothing reads the API.
 */
export default async function LabScreen({ params, searchParams }: Props) {
  const [{ screen }, query] = await Promise.all([params, searchParams]);
  if (!isScreen(screen)) notFound();
  const bare = one(query.bare) === "1";
  return (
    <div data-screen={screen} className="flex min-h-dvh flex-col">
      {bare ? null : <LabBar screen={screen} />}
      {screen === "landing" ? <LandingScreen /> : null}
      {screen === "home" ? <HomeScreen /> : null}
      {screen === "certificate" ? <CertificateScreen /> : null}
      {screen === "tracker" ? <TrackerScreen /> : null}
      {screen === "proposal" ? <ProposalScreen /> : null}
      {screen === "checkout" ? <CheckoutScreen succeeded={one(query.variant) === "success"} /> : null}
    </div>
  );
}
