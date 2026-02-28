import { NavLink, Outlet } from "react-router-dom";
import { MessageSquare, Building2, Microscope, Map, Settings, Sun, Moon } from "lucide-react";
import { useState, useEffect } from "react";
import SettingsPanel from "./SettingsPanel";

const NAV = [
  { to: "/", icon: MessageSquare, label: "Chat" },
  { to: "/pharma", icon: Building2, label: "Pharma DD" },
  { to: "/biotech", icon: Microscope, label: "Biotech" },
  { to: "/landscape", icon: Map, label: "Landscape" },
];

export default function Layout() {
  const [showSettings, setShowSettings] = useState(false);
  const [dark, setDark] = useState(() => localStorage.getItem("theme") === "dark");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);

  return (
    <div className="flex h-screen bg-surface text-on-surface">
      {/* Sidebar */}
      <nav className="w-56 bg-primary text-on-primary flex flex-col shrink-0">
        <div className="p-4 border-b border-on-primary/20">
          <h1 className="text-lg font-bold tracking-tight font-heading">AGE-nt</h1>
          <p className="text-xs text-on-primary/70 mt-0.5">Longevity Evidence Platform</p>
        </div>

        <div className="flex-1 p-2 space-y-1">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? "bg-on-primary/20 text-on-primary font-medium"
                    : "text-on-primary/70 hover:bg-on-primary/10 hover:text-on-primary"
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </div>

        <div className="border-t border-on-primary/20">
          <button
            onClick={() => setDark(!dark)}
            className="flex items-center gap-3 w-full px-5 py-3 text-sm text-on-primary/70 hover:text-on-primary hover:bg-on-primary/10 transition-colors"
          >
            {dark ? <Sun size={18} /> : <Moon size={18} />}
            {dark ? "Light Mode" : "Dark Mode"}
          </button>
          <button
            onClick={() => setShowSettings(true)}
            className="flex items-center gap-3 w-full px-5 py-3 text-sm text-on-primary/70 hover:text-on-primary hover:bg-on-primary/10 transition-colors"
          >
            <Settings size={18} />
            Settings
          </button>
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>

      {/* Settings modal */}
      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </div>
  );
}
