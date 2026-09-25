import Link from "next/link";
import { getTranslations } from "next-intl/server";

export default async function Home() {
  const t = await getTranslations("home");
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-4 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
      <p className="text-lg leading-8">{t("lead")}</p>
      <div className="flex flex-wrap gap-3">
        <Link className="rounded-md bg-foreground px-4 py-2 font-medium text-background" href="/signup">
          {t("signUp")}
        </Link>
        <Link className="rounded-md border px-4 py-2 font-medium" href="/login">
          {t("logIn")}
        </Link>
      </div>
    </main>
  );
}
