import { DemoControlPanel } from "@/components/DemoControlPanel";
import { getHighRecoveryOpportunities, type RecoveryOpportunity } from "@/lib/api";

export default async function DemoPage() {
  let initialCandidates: RecoveryOpportunity[] = [];
  let error: string | null = null;

  try {
    initialCandidates = await getHighRecoveryOpportunities(15);
  } catch {
    error = "Could not reach the RecoverAI API. Is the backend running?";
  }

  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-900">Demo Control Panel</h1>
        <p className="mt-1 text-sm text-slate-500">
          Every button here calls the real backend -- no data on this page is fabricated in the browser.
        </p>
      </header>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      ) : (
        <DemoControlPanel initialCandidates={initialCandidates} />
      )}
    </main>
  );
}
