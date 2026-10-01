import type { Metadata } from "next";
import Link from "next/link";

import { Wordmark } from "./brand/Logo";
import { DIRECTION, DIRECTIONS } from "./directions";
import { SCREENS } from "./screens";

export const metadata: Metadata = { title: "Design lab", robots: { index: false } };

/** The five name candidates (P18 step 1): the owner picks one; the lab letters its wordmarks until then. */
export const NAME_CANDIDATES = [
  { name: "Wazo", say: "WAH-zo", meaning: "idea (Swahili)", note: "short, two syllables in both languages; wazo.co.ke style" },
  { name: "Kiungo", say: "kee-OON-go", meaning: "link, joint, connector (Swahili)", note: "says what the product does; three syllables" },
  { name: "Hati", say: "HAH-tee", meaning: "certificate, document, deed (Swahili: hati miliki)", note: "names the proof of authorship; four letters" },
  { name: "Buni", say: "BOO-nee", meaning: "to invent, to design (Swahili: kubuni)", note: "flag: Buni Media is a Nairobi animation studio" },
  { name: "Kuza", say: "KOO-za", meaning: "to grow, to nurture (Swahili)", note: "flag: used by a Kenyan agribusiness programme (Kuza Biashara)" },
] as const;

/** The lab's front page: the brand board, then every screen under every direction, light and dark. */
export default function DesignLabIndex() {
  return (
    <main id="main" className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 lg:py-16">
      <h1 className="text-2xl text-ink lg:text-3xl">Design lab</h1>
      <p className="mt-2 max-w-[60ch] text-ink-soft">
        Development only. The same product components under three directions, on fixture data. Add <code>?theme=dark</code> for
        dark mode and <code>&amp;bare=1</code> to hide the switch bar.
      </p>

      <section aria-labelledby="names" className="mt-12">
        <h2 id="names" className="text-lg text-ink">Name candidates</h2>
        <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">
          Easy to say in English and Swahili; no trademark search was run (docs/demo/directions/directions.md lists the obvious clashes
          left out: Daraja, Jenga, Tuko, Soko, Ushahidi).
        </p>
        <ul className="mt-4 divide-y divide-line border-y border-line">
          {NAME_CANDIDATES.map((c) => (
            <li key={c.name} className="grid gap-x-6 gap-y-1 py-4 sm:grid-cols-[8rem_minmax(0,1fr)]">
              <span className="text-lg font-semibold text-ink">{c.name}</span>
              <span className="text-sm text-ink-soft">
                {c.say} · {c.meaning} · {c.note}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="marks" className="mt-12">
        <h2 id="marks" className="text-lg text-ink">Wordmarks and marks</h2>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {DIRECTIONS.map((key) => (
            <div key={key} data-direction={key} data-theme="light" className="rounded-panel border border-line bg-paper p-6" style={{ minHeight: 0 }}>
              <p className="text-sm font-semibold text-ink-soft">
                {key.toUpperCase()} · {DIRECTION[key].name}
              </p>
              <ul className="mt-4 flex flex-col gap-4">
                {NAME_CANDIDATES.map((c) => (
                  <li key={c.name}>
                    <Wordmark direction={key} name={c.name} size={30} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="matrix" className="mt-12">
        <h2 id="matrix" className="text-lg text-ink">Screens</h2>
        <table className="mt-4 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              <th className="py-2 pr-4 font-semibold text-ink">Screen</th>
              {DIRECTIONS.map((key) => (
                <th key={key} className="py-2 pr-4 font-semibold text-ink">
                  {key.toUpperCase()} {DIRECTION[key].name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {SCREENS.map((s) => (
              <tr key={s.key} className="border-b border-line">
                <td className="py-2 pr-4 text-ink">{s.label}</td>
                {DIRECTIONS.map((key) => (
                  <td key={key} className="py-2 pr-4">
                    <Link href={`/design-lab/${key}/${s.key}`} className="font-semibold text-jacaranda underline">
                      light
                    </Link>
                    {" · "}
                    <Link href={`/design-lab/${key}/${s.key}?theme=dark`} className="font-semibold text-jacaranda underline">
                      dark
                    </Link>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
