import Link from "next/link";
import { notFound } from "next/navigation";
import { CampaignDetailView } from "@/components/CampaignDetailView";
import { getCampaign } from "@/lib/api";
import { ArrowLeft, ShieldCheck } from "lucide-react";

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
    <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-6">
      <Link
        href="/demo"
        className="inline-flex items-center gap-1 text-xs font-semibold text-slate-600 hover:text-slate-900"
      >
        <ArrowLeft className="h-4 w-4" /> Back to Demo Control Panel
      </Link>
      
      <div className="border-b border-slate-200/80 pb-5">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
            <ShieldCheck className="h-3 w-3" /> AUDIT TRAIL
          </span>
        </div>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          Campaign Audit Trail
        </h1>
        <p className="mt-1 text-xs sm:text-sm text-slate-500">
          What AI concluded &amp; recommended, what the merchant approved, what the system executed, and what actually happened.
        </p>
      </div>

      <CampaignDetailView campaign={campaign} />
    </main>
  );
}
