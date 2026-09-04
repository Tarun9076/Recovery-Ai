export function StatCard({
  label,
  value,
  accent = "default",
}: {
  label: string;
  value: string;
  accent?: "default" | "danger" | "success";
}) {
  const accentClass =
    accent === "danger"
      ? "text-red-600"
      : accent === "success"
        ? "text-emerald-600"
        : "text-slate-900";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`mt-2 text-3xl font-semibold ${accentClass}`}>{value}</p>
    </div>
  );
}
