import { Activity, Bell, BookOpen, Boxes, CircleUserRound, CreditCard, FileSearch, GitBranch, HeartPulse, Landmark, Network, Search, Settings } from "lucide-react";

const navItems = [
  { id: "overview", label: "Contract Overview", icon: Landmark },
  { id: "detail", label: "Contract Detail", icon: FileSearch },
  { id: "milestone", label: "Milestone Detail", icon: Boxes },
  { id: "workflow", label: "Payment Workflow", icon: CreditCard },
  { id: "query", label: "Contract Query", icon: GitBranch },
  { id: "wiki", label: "Contract Wiki", icon: BookOpen },
  { id: "graph", label: "Knowledge Graph", icon: Network },
  { id: "health", label: "System Health", icon: HeartPulse },
];

export function Layout({ page, setPage, health, children }) {
  const pageLabel = navItems.find((item) => item.id === page)?.label || "Contract Intelligence";
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">CI</div>
          <div>
            <h1>Contract Intel</h1>
            <p>Offline audit workstation</p>
          </div>
        </div>
        <nav className="nav-list">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={page === item.id ? "nav-item active" : "nav-item"} type="button" onClick={() => setPage(item.id)}>
                <Icon size={17} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="local-mode">
          <span className={health?.status === "ok" ? "pulse-dot" : "pulse-dot muted"} />
          <div>
            <strong>Local Mode</strong>
            <span>{health?.host_ollama_reachable ? "Ollama reachable" : "LLM not reachable"}</span>
          </div>
        </div>
      </aside>
      <main className="content">
        <header className="topbar">
          <div className="topbar-title">
            <h1>{pageLabel}</h1>
          </div>
          <div className="topbar-actions">
            <label className="topbar-search">
              <Search size={16} />
              <input type="text" placeholder={page === "wiki" ? "Search knowledge base..." : "Search resources..."} />
            </label>
            <button className="topbar-icon" type="button" aria-label="Notifications"><Bell size={18} /></button>
            <button className="topbar-icon" type="button" aria-label="Settings"><Settings size={18} /></button>
            <button className="topbar-icon" type="button" aria-label="Account"><CircleUserRound size={18} /></button>
            <div className="topbar-status">
              <Activity size={17} />
              <span>{health?.offline_only ? "Offline-only pipeline" : "Check offline mode"}</span>
            </div>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
