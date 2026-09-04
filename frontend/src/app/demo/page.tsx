import { DemoControlPanel } from "@/components/DemoControlPanel";
import { getHighRecoveryOpportunities, type RecoveryOpportunity } from "@/lib/api";
import { SlidersHorizontal } from "lucide-react";

export default async function DemoPage() {
  let initialCandidates: RecoveryOpportunity[] = [];
  let error: string | null = null;

  try {
    initialCandidates = await getHighRecoveryOpportunities(15);
  } catch {
    error = "Could not reach the RecoverAI API backend. Is the server running?";
  }

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
      <div className="border-b border-slate-200/80 pb-5">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
            <SlidersHorizontal className="h-3 w-3" /> END-TO-END DEMO CONTROLS
          </span>
        </div>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          Demo Control Panel
        </h1>
        <p className="mt-1 text-xs sm:text-sm text-slate-500">
          Run the complete RecoverAI recovery workflow against the real backend.
        </p>
      </div>

      {error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-sm text-rose-800 shadow-xs">
          {error}
        </div>
      ) : (
        <DemoControlPanel initialCandidates={initialCandidates} />
      )}
    </main>
  );
}
