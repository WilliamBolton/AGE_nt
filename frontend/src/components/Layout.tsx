import { NavLink, Outlet } from "react-router-dom";
import { MessageSquare, Building2, Microscope, Settings, Sun, Moon } from "lucide-react";
import { useState, useEffect } from "react";
import SettingsPanel from "./SettingsPanel";

const NAV = [
  { to: "/", icon: MessageSquare, label: "Chat" },
  { to: "/biotech", icon: Microscope, label: "Biotech" },
  { to: "/pharma", icon: Building2, label: "Pharma DD" },
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
      <nav className="w-56 bg-[#DBC66E] flex flex-col shrink-0">
        <div className="p-4 border-b border-[#534600]/20">
          <h1 className="text-lg font-bold tracking-tight font-heading text-[#15130B]">AGE-nt</h1>
          <p className="text-xs text-[#534600] mt-0.5">Longevity Intervention Intelligence</p>
        </div>

        <div className="flex-1 p-2 space-y-1">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? "bg-[#534600]/20 text-[#15130B] font-medium"
                    : "text-[#534600] hover:bg-[#534600]/10 hover:text-[#15130B]"
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </div>

        <div className="border-t border-[#534600]/20">
          <button
            onClick={() => setDark(!dark)}
            className="flex items-center gap-3 w-full px-5 py-3 text-sm text-[#534600] hover:text-[#15130B] hover:bg-[#534600]/10 transition-colors"
          >
            {dark ? <Sun size={18} /> : <Moon size={18} />}
            {dark ? "Light Mode" : "Dark Mode"}
          </button>
          <button
            onClick={() => setShowSettings(true)}
            className="flex items-center gap-3 w-full px-5 py-3 text-sm text-[#534600] hover:text-[#15130B] hover:bg-[#534600]/10 transition-colors"
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
