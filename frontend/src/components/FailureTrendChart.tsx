import type { FailureTrendPoint } from "@/lib/api";

const WIDTH = 900;
const HEIGHT = 260;
const PADDING = 32;

export function FailureTrendChart({ points }: { points: FailureTrendPoint[] }) {
  if (points.length === 0) {
    return <p className="text-sm text-slate-500">No trend data yet.</p>;
  }

  const maxVolume = Math.max(...points.map((p) => p.total_payments), 1);
  const maxRate = Math.max(...points.map((p) => p.failure_rate), 0.01);

  const innerWidth = WIDTH - PADDING * 2;
  const innerHeight = HEIGHT - PADDING * 2;
  const step = points.length > 1 ? innerWidth / (points.length - 1) : 0;

  const barWidth = Math.max(2, (innerWidth / points.length) * 0.6);

  const linePoints = points
    .map((p, i) => {
      const x = PADDING + i * step;
      const y = PADDING + innerHeight - (p.failure_rate / maxRate) * innerHeight;
      return `${x},${y}`;
    })
    .join(" ");

  const tickIndexes = points.length <= 8
    ? points.map((_, i) => i)
    : [0, Math.floor(points.length / 4), Math.floor(points.length / 2), Math.floor((3 * points.length) / 4), points.length - 1];

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" role="img" aria-label="Payment failure trend">
      {/* volume bars */}
      {points.map((p, i) => {
        const x = PADDING + i * step - barWidth / 2;
        const barHeight = (p.total_payments / maxVolume) * innerHeight;
        const y = PADDING + innerHeight - barHeight;
        return (
          <rect key={`bar-${p.date}`} x={x} y={y} width={barWidth} height={barHeight} fill="#e2e8f0" />
        );
      })}

      {/* failure rate line */}
      <polyline points={linePoints} fill="none" stroke="#dc2626" strokeWidth={2} />
      {points.map((p, i) => {
        const x = PADDING + i * step;
        const y = PADDING + innerHeight - (p.failure_rate / maxRate) * innerHeight;
        return <circle key={`pt-${p.date}`} cx={x} cy={y} r={2.5} fill="#dc2626" />;
      })}

      {/* x axis labels */}
      {tickIndexes.map((i) => {
        const p = points[i];
        const x = PADDING + i * step;
        return (
          <text key={`label-${p.date}`} x={x} y={HEIGHT - 6} fontSize={10} textAnchor="middle" fill="#64748b">
            {p.date.slice(5)}
          </text>
        );
      })}
    </svg>
  );
}
