import Link from "next/link";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/evaluation", label: "Evaluation" },
  { href: "/demo", label: "Demo Control Panel" },
];

export function NavBar() {
  return (
    <nav className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-6 px-6 py-3">
        <span className="text-sm font-semibold text-slate-900">RecoverAI</span>
        <div className="flex gap-4">
          {LINKS.map((link) => (
            <Link key={link.href} href={link.href} className="text-sm text-slate-500 hover:text-slate-900">
              {link.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
