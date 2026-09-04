import React from "react";
import { TrendingUp, TrendingDown, HelpCircle, LucideIcon } from "lucide-react";

interface KPICardProps {
  title: string;
  value: string;
  subtitle?: string;
  icon?: LucideIcon;
  variant?: "danger" | "success" | "warning" | "info" | "neutral";
  trend?: {
    value: string;
    isUp?: boolean;
    label?: string;
  };
  highlight?: boolean;
}

export function KPICard({
  title,
  value,
  subtitle,
  icon: Icon,
  variant = "neutral",
  trend,
  highlight = false,
}: KPICardProps) {
  const variantStyles = {
    danger: {
      border: "border-rose-200 hover:border-rose-300",
      iconBg: "bg-rose-50 text-rose-600",
      valueColor: "text-rose-600",
      topBorder: "border-t-2 border-t-rose-500",
    },
    success: {
      border: "border-emerald-200 hover:border-emerald-300",
      iconBg: "bg-emerald-50 text-emerald-600",
      valueColor: "text-emerald-700",
      topBorder: "border-t-2 border-t-emerald-500",
    },
    warning: {
      border: "border-amber-200 hover:border-amber-300",
      iconBg: "bg-amber-50 text-amber-600",
      valueColor: "text-amber-700",
      topBorder: "border-t-2 border-t-amber-500",
    },
    info: {
      border: "border-blue-200 hover:border-blue-300",
      iconBg: "bg-blue-50 text-blue-600",
      valueColor: "text-blue-700",
      topBorder: "border-t-2 border-t-blue-500",
    },
    neutral: {
      border: "border-slate-200 hover:border-slate-300",
      iconBg: "bg-slate-100 text-slate-600",
      valueColor: "text-slate-900",
      topBorder: "border-t-2 border-t-slate-300",
    },
  };

  const currentStyle = variantStyles[variant];

  return (
    <div
      className={`relative overflow-hidden rounded-xl border bg-white p-5 shadow-xs transition-all duration-150 ${
        currentStyle.border
      } ${highlight ? currentStyle.topBorder : ""}`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {title}
        </span>
        {Icon && (
          <div className={`rounded-lg p-2 ${currentStyle.iconBg}`}>
            <Icon className="h-4 w-4" />
          </div>
        )}
      </div>

      <div className="mt-3 flex items-baseline justify-between">
        <p className={`text-2xl font-bold tracking-tight sm:text-3xl ${currentStyle.valueColor}`}>
          {value}
        </p>
      </div>

      {(subtitle || trend) && (
        <div className="mt-2 flex items-center gap-2 text-xs">
          {trend && (
            <span
              className={`inline-flex items-center font-medium ${
                trend.isUp ? "text-emerald-600" : "text-rose-600"
              }`}
            >
              {trend.isUp ? (
                <TrendingUp className="mr-0.5 h-3 w-3" />
              ) : (
                <TrendingDown className="mr-0.5 h-3 w-3" />
              )}
              {trend.value}
            </span>
          )}
          {subtitle && <span className="text-slate-500">{subtitle}</span>}
        </div>
      )}
    </div>
  );
}
