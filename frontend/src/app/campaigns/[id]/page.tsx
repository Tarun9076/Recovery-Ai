import Link from "next/link";
import { notFound } from "next/navigation";

import { CampaignDetailView } from "@/components/CampaignDetailView";
import { getCampaign } from "@/lib/api";

export default async function CampaignDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let campaign;
  try {
    campaign = await getCampaign(id);
  } catch {
    notFound();
  }

  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10">
      <Link href="/demo" className="text-sm text-slate-500 hover:text-slate-900">
        &larr; Back to Demo Control Panel
      </Link>
      <header className="mt-4 mb-8">
        <h1 className="text-2xl font-semibold text-slate-900">Campaign Audit Trail</h1>
        <p className="mt-1 text-sm text-slate-500">
          What AI saw and recommended, what the merchant approved, what the system executed, and what actually happened.
        </p>
      </header>
      <CampaignDetailView campaign={campaign} />
    </main>
  );
}
