import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth";

const nav = [
  { to: "/", label: "Home", icon: "🏠", end: true },
  { to: "/dashboard", label: "Dashboard", icon: "📊" },
  { to: "/tenants", label: "Tenants", icon: "👥" },
  { to: "/payments", label: "Payments", icon: "₹" },
  { to: "/properties", label: "Properties", icon: "🏢" },
  { to: "/links", label: "Links", icon: "🔗" },
  { to: "/settings", label: "Settings", icon: "⚙️" },
];
const mobileNav = nav.filter((n) => ["/", "/dashboard", "/tenants", "/payments", "/settings"].includes(n.to));

export default function Layout() {
  const { owner, logout } = useAuth();
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          <span className="text-lg font-bold text-slate-900">Rent Manager</span>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${
                  isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
                }`
              }
            >
              <span className="w-5 text-center">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-4 text-sm">
          <p className="truncate font-medium text-slate-800">{owner?.name}</p>
          <p className="truncate text-xs text-slate-500">{owner?.email}</p>
          <button onClick={logout} className="mt-2 text-xs font-medium text-red-600 hover:underline">
            Log out
          </button>
        </div>
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur md:hidden">
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <span className="font-bold text-slate-900">Rent Manager</span>
        </div>
        <div className="flex gap-1">
          <NavLink to="/properties" className="rounded-lg px-2 py-1 text-sm font-medium text-brand-700">🏢 Properties</NavLink>
          <NavLink to="/links" className="rounded-lg px-2 py-1 text-sm font-medium text-brand-700">🔗 Links</NavLink>
        </div>
      </header>

      <main className="px-4 pb-24 pt-4 md:ml-60 md:px-8 md:pb-10 md:pt-8">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>

      {/* Mobile bottom nav */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-slate-200 bg-white pb-[env(safe-area-inset-bottom)] md:hidden">
        {mobileNav.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              `flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${
                isActive ? "text-brand-700" : "text-slate-500"
              }`
            }
          >
            <span className="text-lg leading-none">{n.icon}</span>
            {n.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
