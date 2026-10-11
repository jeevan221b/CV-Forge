import { FileText, History, LayoutDashboard, Menu, PlusCircle, Settings as SettingsIcon, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { getToken, setToken, setUnauthorizedHandler } from "./api";
import { Alert, Button, Modal, cx } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import HistoryPage from "./pages/History";
import MasterResume from "./pages/MasterResume";
import NewSession from "./pages/NewSession";
import ResumeEditor from "./pages/ResumeEditor";
import SessionPage from "./pages/Session";
import SettingsPage from "./pages/Settings";
import { SystemProvider, useSystem } from "./system";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/resume", label: "Master Resume", icon: FileText },
  { to: "/sessions/new", label: "New Tailoring Session", icon: PlusCircle },
  { to: "/history", label: "Application History", icon: History },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { system } = useSystem();
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent-700 text-white">
          <FileText className="h-4 w-4" aria-hidden />
        </div>
        <div>
          <p className="text-sm font-semibold leading-tight text-slate-900">CV Forge</p>
          <p className="text-[11px] leading-tight text-slate-500">Evidence-based tailoring</p>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 px-3" aria-label="Main">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cx(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                isActive ? "bg-accent-50 font-medium text-accent-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>
      {system && (
        <dl className="space-y-1.5 border-t border-slate-200 px-5 py-4 text-[11px] text-slate-500">
          <Status label="AI tailoring" ok={system.ai.configured} okText={system.ai.model} badText="no API key" />
          <Status label="PDF compiler" ok={system.toolchain.can_compile} okText={system.toolchain.engine ?? ""} badText="not installed" />
          <Status label="Network" ok={system.server.local_only} okText="local only" badText={system.server.host} neutral />
        </dl>
      )}
    </div>
  );
}

function Status({ label, ok, okText, badText, neutral }: { label: string; ok: boolean; okText: string; badText: string; neutral?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt>{label}</dt>
      <dd className="flex min-w-0 items-center gap-1.5">
        <span className={cx("h-1.5 w-1.5 shrink-0 rounded-full", ok ? "bg-emerald-500" : neutral ? "bg-sky-500" : "bg-amber-500")} />
        <span className="truncate text-slate-700">{ok ? okText : badText}</span>
      </dd>
    </div>
  );
}

function TokenPrompt({ onDone }: { onDone: () => void }) {
  const [value, setValue] = useState(getToken());
  return (
    <Modal
      title="Access token required"
      onClose={onDone}
      footer={
        <Button
          variant="primary"
          onClick={() => {
            setToken(value.trim());
            window.location.reload();
          }}
        >
          Save and reload
        </Button>
      }
    >
      <p className="mb-3">
        This CV Forge server is protected by an access token (CVFORGE_ACCESS_TOKEN in the backend configuration). The
        token is stored only in this browser.
      </p>
      <input className="field" type="password" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Access token" autoFocus />
    </Modal>
  );
}

function Shell() {
  const [open, setOpen] = useState(false);
  const [needToken, setNeedToken] = useState(false);
  const { error } = useSystem();
  const location = useLocation();
  useEffect(() => {
    setUnauthorizedHandler(() => setNeedToken(true));
  }, []);
  useEffect(() => {
    // Block body on purpose: newer browsers return a Promise from scrollTo, which must not become the effect's cleanup.
    window.scrollTo(0, 0);
  }, [location.pathname]);

  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white lg:block">
        <div className="sticky top-0 h-screen">
          <Sidebar />
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:hidden">
        <span className="text-sm font-semibold text-slate-900">CV Forge</span>
        <button type="button" aria-label="Open menu" onClick={() => setOpen(true)} className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100">
          <Menu className="h-5 w-5" />
        </button>
      </header>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-72 bg-white shadow-xl">
            <button type="button" aria-label="Close menu" onClick={() => setOpen(false)} className="absolute right-3 top-4 rounded-md p-1.5 text-slate-500 hover:bg-slate-100">
              <X className="h-5 w-5" />
            </button>
            <Sidebar onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}

      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
          {error && !needToken && (
            <Alert kind="error" title="Backend unavailable" className="mb-6">
              {error} Start it with <code className="font-mono text-xs">python -m app</code> in the backend folder.
            </Alert>
          )}
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/resume" element={<MasterResume />} />
            <Route path="/resume/:id" element={<ResumeEditor />} />
            <Route path="/sessions/new" element={<NewSession />} />
            <Route path="/sessions/:id" element={<SessionPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<p className="py-16 text-center text-sm text-slate-500">Page not found.</p>} />
          </Routes>
        </div>
      </main>
      {needToken && <TokenPrompt onDone={() => setNeedToken(false)} />}
    </div>
  );
}

export default function App() {
  return (
    <SystemProvider>
      <Shell />
    </SystemProvider>
  );
}
