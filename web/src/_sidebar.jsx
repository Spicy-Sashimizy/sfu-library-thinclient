
const NIcon = ({ name, size = 16, className = "", style = {} }) => {
  const icons = {
    search: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="9" cy="9" r="6"/><path d="m16 16-3.5-3.5"/></svg>,
    book: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 3h10a1 1 0 0 1 1 1v13l-2-1-2 1-2-1-2 1-2-1-2 1V4a1 1 0 0 1 1-1Z"/><path d="M7 8h6M7 11h4"/></svg>,
    history: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="10" cy="10" r="7"/><path d="M10 6v4l2.5 2.5"/></svg>,
    bookmark: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 3h10v14l-5-3-5 3V3Z"/></svg>,
    settings: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="10" cy="10" r="2.5"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42"/></svg>,
    database: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="10" cy="5.5" rx="7" ry="2.5"/><path d="M3 5.5v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5v-4"/><path d="M3 9.5v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5v-4"/></svg>,
    admin: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2L3 6v4c0 4.4 3.03 8.52 7 9.5 3.97-.98 7-5.1 7-9.5V6L10 2Z"/></svg>,
    copy: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="8" y="8" width="9" height="9" rx="1.5"/><path d="M4 12V4a1 1 0 0 1 1-1h8"/></svg>,
    zotero: <svg width={size} height={size} viewBox="0 0 20 20" fill="currentColor"><path d="M4 4h12v2.5L8.5 14H16v2H4v-2.5L11.5 6H4V4Z"/></svg>,
    download: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10 3v10m-4-4 4 4 4-4"/><path d="M4 16h12"/></svg>,
    externalLink: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4"/><path d="M13 3h4v4"/><path d="M9 11 17 3"/></svg>,
    chevronDown: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 8 5 5 5-5"/></svg>,
    chevronRight: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m8 5 5 5-5 5"/></svg>,
    close: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 5 15 15M15 5 5 15"/></svg>,
    filter: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 5h14M6 10h8M9 15h2"/></svg>,
    sparkle: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2v3M10 15v3M2 10h3M15 10h3M4.22 4.22l2.12 2.12M13.66 13.66l2.12 2.12M4.22 15.78l2.12-2.12M13.66 6.34l2.12-2.12"/><circle cx="10" cy="10" r="2"/></svg>,
    plus: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 4v12M4 10h12"/></svg>,
    edit: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 2.5a2.12 2.12 0 0 1 3 3L6 17l-4 1 1-4 11.5-11.5Z"/></svg>,
    trash: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h14M8 6V4h4v2M6 6v11a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V6"/></svg>,
    cpu: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="12" height="12" rx="1.5"/><rect x="7" y="7" width="6" height="6" rx="0.5"/><path d="M7 2v2M13 2v2M7 16v2M13 16v2M2 7h2M2 13h2M16 7h2M16 13h2"/></svg>,
    check: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="m4 10 4.5 4.5 7.5-8"/></svg>,
    warning: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10 3 2 17h16L10 3Z"/><path d="M10 9v4M10 14.5v1"/></svg>,
    activity: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M2 10h3l2-5 3 10 2-5h6"/></svg>,
    chart: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 17h14"/><path d="M6 14V9M10 14V5M14 14v-6"/></svg>,
    server: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3.5" width="14" height="5.5" rx="1.2"/><rect x="3" y="11" width="14" height="5.5" rx="1.2"/><path d="M6 6.25h.01M6 13.75h.01"/></svg>,
    arrowLeft: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m10 5-5 5 5 5"/><path d="M5 10h11"/></svg>,
    info: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="10" cy="10" r="7"/><path d="M10 9v5M10 6.5v.5"/></svg>,
    link: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M8 13H5a4 4 0 0 1 0-8h3M12 7h3a4 4 0 0 1 0 8h-3M7 10h6"/></svg>,
  };
  return <span className={className} style={{ display: "inline-flex", alignItems: "center", ...style }}>{icons[name] || null}</span>;
};


window.SFUHistory = (function () {
  const KEY = "sfu_search_history_v1";
  const PENDING_KEY = "sfu_pending_rerun";
  const CAP = 100; 
  function read() {
    try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch (e) { return []; }
  }
  function write(list) {
    try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, CAP))); } catch (e) {}
    try { window.dispatchEvent(new CustomEvent("sfu-history-changed")); } catch (e) {}
  }
  return {
    read: read,
    
    record: function (entry) {
      const list = read();
      
      
      const dup = list.findIndex(e => e.q === entry.q);
      if (dup !== -1) list.splice(dup, 1);
      list.unshift(entry);
      write(list);
    },
    remove: function (at) { write(read().filter(e => e.at !== at)); },
    clear: function () { write([]); },
    
    
    setPending: function (q) { try { localStorage.setItem(PENDING_KEY, q); } catch (e) {} },
    takePending: function () {
      try {
        const q = localStorage.getItem(PENDING_KEY);
        if (q) localStorage.removeItem(PENDING_KEY);
        return q || null;
      } catch (e) { return null; }
    },
    timeAgo: function (at) {
      const s = Math.max(0, (Date.now() - at) / 1000);
      if (s < 60) return "just now";
      if (s < 3600) return Math.floor(s / 60) + "m ago";
      if (s < 86400) return Math.floor(s / 3600) + "h ago";
      if (s < 172800) return "yesterday";
      return new Date(at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    },
  };
})();


const RecentSearchesPanel = ({ app }) => {
  const [entries, setEntries] = React.useState(() => (window.SFUHistory ? window.SFUHistory.read() : []));
  React.useEffect(() => {
    const refresh = () => setEntries(window.SFUHistory ? window.SFUHistory.read() : []);
    window.addEventListener("sfu-history-changed", refresh);
    window.addEventListener("storage", refresh); 
    return () => { window.removeEventListener("sfu-history-changed", refresh); window.removeEventListener("storage", refresh); };
  }, []);

  const rerun = (q) => {
    if (app === "search") {
      window.dispatchEvent(new CustomEvent("sfu-history-rerun", { detail: { q } }));
    } else {
      if (window.SFUHistory) window.SFUHistory.setPending(q);
      if (window.parent !== window) window.parent.postMessage({ suiteNav: "search" }, "*");
      else window.location.href = "search.html";
    }
  };

  if (!entries.length) {
    return (
      <div style={{ flex: 1, minHeight: 0, padding: "6px 12px", fontSize: 11, color: "oklch(55% 0.010 250)", lineHeight: 1.5 }}>
        No searches yet this session.<br />Your recent queries will appear here.
      </div>
    );
  }
  return (
    <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "0 4px 4px" }}>
      {entries.slice(0, 8).map(e => (
        <button key={e.at} onClick={() => rerun(e.q)} title={'Search again: ' + e.q}
          style={{ display: "block", width: "100%", border: "none", background: "transparent", textAlign: "left", padding: "4px 8px", borderRadius: 4, cursor: "pointer" }}
          onMouseEnter={ev => ev.currentTarget.style.background = "oklch(26% 0.014 250)"}
          onMouseLeave={ev => ev.currentTarget.style.background = "transparent"}>
          <span style={{ display: "block", fontSize: 11, color: "var(--text-sidebar)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", lineHeight: 1.35 }}>{e.q}</span>
          <span style={{ display: "block", fontSize: 9.5, color: "oklch(52% 0.010 250)", fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace" }}>
            {window.SFUHistory.timeAgo(e.at)}{typeof e.results === "number" ? " · " + e.results + " results" : ""}{e.live === false ? " · sample" : ""}
          </span>
        </button>
      ))}
    </div>
  );
};


const QuickFiltersPanel = () => {
  const [active, setActive] = React.useState(new Set(["oa"]));
  const filters = [
    { id: "oa",     label: "Open Access only",  count: 12 },
    { id: "sfu",    label: "Duck Library",      count: 23 },
    { id: "peer",   label: "Peer-reviewed",     count: 41 },
    { id: "recent", label: "Last 5 years",      count: 28 },
    { id: "review", label: "Review articles",   count: 6  },
  ];
  const toggle = (id) => setActive(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return (
    <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "2px 8px 8px", display: "flex", flexDirection: "column", gap: 2 }}>
      {filters.map(f => {
        const on = active.has(f.id);
        return (
          <button key={f.id} onClick={() => toggle(f.id)}
            style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 8px", borderRadius: 5, border: "none", background: on ? "oklch(28% 0.020 25)" : "transparent", color: on ? "var(--text-sidebar-active)" : "var(--text-sidebar)", fontSize: 11.5, fontFamily: "var(--font-ui)", textAlign: "left", cursor: "pointer", transition: "background 0.12s" }}>
            <span style={{ width: 12, height: 12, borderRadius: 3, border: `1.5px solid ${on ? "var(--accent-red-mid)" : "oklch(40% 0.010 250)"}`, background: on ? "var(--accent-red-mid)" : "transparent", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              {on && <NIcon name="check" size={8} style={{ color: "white" }} />}
            </span>
            <span style={{ flex: 1 }}>{f.label}</span>
            <span style={{ fontSize: 10, color: "oklch(55% 0.010 250)", fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace" }}>{f.count}</span>
          </button>
        );
      })}
    </div>
  );
};


const AiNotesPanel = () => (
  <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "2px 12px 8px" }}>
    <div style={{ fontSize: 11, color: "var(--text-sidebar)", lineHeight: 1.5, fontFamily: "var(--font-serif)", fontStyle: "italic", marginBottom: 8 }}>
      "Your last 3 searches converge on graph-based and transformer methods for molecular property prediction."
    </div>
    <div style={{ fontSize: 10, color: "oklch(60% 0.010 250)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4, fontWeight: 500 }}>Suggested next steps</div>
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      {[
        "→ Narrow to GNN architectures",
        "→ Add: \"reaction prediction\"",
        "→ Author cluster: Schwaller, Coley",
      ].map(s => (
        <div key={s} style={{ fontSize: 10.5, color: "var(--text-sidebar)", padding: "3px 6px", borderRadius: 4, cursor: "pointer", transition: "background 0.12s" }}
          onMouseEnter={e => e.currentTarget.style.background = "oklch(26% 0.014 250)"}
          onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
          {s}
        </div>
      ))}
    </div>
  </div>
);


const PANELS = {
  recent:  { label: "Recent Searches", icon: "history",   Comp: RecentSearchesPanel },
  filters: { label: "Quick Filters",   icon: "filter",    Comp: QuickFiltersPanel  },
  notes:   { label: "AI Notes",        icon: "sparkle",   Comp: AiNotesPanel       },
};

const SidebarPanel = ({ app }) => {
  const [panel, setPanel] = React.useState("recent");
  const [open, setOpen] = React.useState(true);
  const [menuOpen, setMenuOpen] = React.useState(false);

  
  React.useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menuOpen]);

  const cur = PANELS[panel];
  const Comp = cur.Comp;

  return (
    <div style={{ flex: open ? 1 : "0 0 auto", minHeight: 0, display: "flex", flexDirection: "column", borderTop: "1px solid oklch(26% 0.010 250)", marginTop: 4 }}>
      {}
      <div style={{ display: "flex", alignItems: "center", padding: "8px 8px 6px", gap: 4 }}>
        {}
        <button
          onClick={(e) => { e.stopPropagation(); setMenuOpen(o => !o); if (!open) setOpen(true); }}
          style={{ display: "flex", alignItems: "center", gap: 5, padding: "3px 6px 3px 8px", border: "none", background: menuOpen ? "oklch(26% 0.014 250)" : "transparent", borderRadius: 4, cursor: "pointer", color: "oklch(70% 0.010 250)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", fontWeight: 500, fontFamily: "var(--font-ui)" }}>
          <NIcon name={cur.icon} size={11} style={{ color: "oklch(60% 0.010 250)" }} />
          {cur.label}
          <NIcon name="chevronDown" size={9} style={{ color: "oklch(55% 0.010 250)", marginLeft: 1 }} />
        </button>

        {}
        <button onClick={() => setOpen(o => !o)}
          title={open ? "Hide panel" : "Show panel"}
          style={{ marginLeft: "auto", border: "none", background: "transparent", color: "oklch(55% 0.010 250)", cursor: "pointer", padding: 4, borderRadius: 4, display: "flex", alignItems: "center", transition: "color 0.12s, background 0.12s" }}
          onMouseEnter={e => { e.currentTarget.style.color = "var(--text-sidebar-active)"; e.currentTarget.style.background = "oklch(26% 0.014 250)"; }}
          onMouseLeave={e => { e.currentTarget.style.color = "oklch(55% 0.010 250)"; e.currentTarget.style.background = "transparent"; }}>
          <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
            {open
              ? <path d="M2 4l3.5 3.5L9 4" />        
              : <path d="M2 7l3.5-3.5L9 7" />}      {}
          </svg>
        </button>

        {}
        {menuOpen && (
          <div onClick={(e) => e.stopPropagation()}
            style={{ position: "absolute", left: 8, marginTop: 28, width: 196, background: "oklch(22% 0.012 250)", border: "1px solid oklch(32% 0.012 250)", borderRadius: 7, padding: 4, boxShadow: "0 8px 24px oklch(0% 0 0 / 0.4)", zIndex: 100 }}>
            <div style={{ fontSize: 9, color: "oklch(55% 0.010 250)", textTransform: "uppercase", letterSpacing: "0.08em", padding: "5px 8px 4px", fontWeight: 500 }}>Show in this slot</div>
            {Object.entries(PANELS).map(([key, p]) => (
              <button key={key}
                onClick={() => { setPanel(key); setMenuOpen(false); setOpen(true); }}
                style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "6px 8px", border: "none", background: panel === key ? "oklch(28% 0.014 250)" : "transparent", color: panel === key ? "var(--text-sidebar-active)" : "var(--text-sidebar)", borderRadius: 4, fontSize: 11.5, cursor: "pointer", textAlign: "left", fontFamily: "var(--font-ui)" }}
                onMouseEnter={e => { if (panel !== key) e.currentTarget.style.background = "oklch(26% 0.014 250)"; }}
                onMouseLeave={e => { if (panel !== key) e.currentTarget.style.background = "transparent"; }}>
                <NIcon name={p.icon} size={12} style={{ color: panel === key ? "var(--accent-red-mid)" : "oklch(60% 0.010 250)" }} />
                <span style={{ flex: 1 }}>{p.label}</span>
                {panel === key && <NIcon name="check" size={11} style={{ color: "var(--accent-red-mid)" }} />}
              </button>
            ))}
            <div style={{ height: 1, background: "oklch(28% 0.012 250)", margin: "4px 4px" }} />
            <button
              onClick={() => { setOpen(false); setMenuOpen(false); }}
              style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", padding: "6px 8px", border: "none", background: "transparent", color: "var(--text-sidebar)", borderRadius: 4, fontSize: 11.5, cursor: "pointer", textAlign: "left", fontFamily: "var(--font-ui)" }}
              onMouseEnter={e => e.currentTarget.style.background = "oklch(26% 0.014 250)"}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
              <NIcon name="close" size={11} style={{ color: "oklch(60% 0.010 250)" }} />
              <span style={{ flex: 1 }}>Hide panel</span>
            </button>
          </div>
        )}
      </div>

      {}
      {open && <Comp app={app} />}
    </div>
  );
};


const SUITE_SEARCH_SCREENS = ["search", "saved", "history", "databases", "settings", "admin"];

const SuiteSidebar = ({ app = "search", active, onScreen, hiddenScreens, interfacePrefs }) => {
  
  
  const [online, setOnline] = React.useState(true);
  React.useEffect(() => {
    const onMsg = (e) => { if (e.data && typeof e.data.suiteDemo === "boolean") setOnline(!e.data.suiteDemo); };
    window.addEventListener("message", onMsg);
    if (window.parent === window && window.SFUApi) {
      window.SFUApi.health().then((r) => setOnline(r.source === "live")).catch(() => {});
    }
    return () => window.removeEventListener("message", onMsg);
  }, []);

  
  
  
  
  
  const hid = hiddenScreens || {};
  const ip = interfacePrefs || {};
  const navItems = [
    { id: "search", icon: "search", label: "Search" },
    { id: "saved", icon: "bookmark", label: "Saved", hide: hid.saved || !ip.savedHistoryNav },
    { id: "history", icon: "history", label: "History", hide: hid.history || !ip.savedHistoryNav },
    { id: "databases", icon: "database", label: "Databases", hide: hid.databases || !ip.databasesTab },
    { id: "analytics", icon: "info", label: "About index", hide: !ip.analyticsApp && app === "search" },
    { id: "index", icon: "server", label: "Index", hide: !ip.indexManagerApp && app === "search" },
  ].filter((i) => !i.hide);
  const bottomItems = [
    { id: "settings", icon: "settings", label: "Settings" },
    { id: "admin", icon: "admin", label: "Admin", hide: hid.admin || !ip.adminPanels },
  ].filter((i) => !i.hide);
  const files = { search: "search.html", analytics: "analytics.html", index: "index_manager.html" };
  const go = (id) => {
    const isSearchScreen = SUITE_SEARCH_SCREENS.indexOf(id) !== -1;
    if (isSearchScreen && app === "search") { if (onScreen) onScreen(id); return; }
    if (id === app) return;
    if (window.parent !== window) window.parent.postMessage({ suiteNav: id }, "*");
    else { const t = isSearchScreen ? "search.html" : files[id]; if (t) window.location.href = t; }
  };
  const btn = (item) => (
    <button key={item.id} onClick={() => go(item.id)}
      style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 12px", borderRadius: 7, border: "none", background: active === item.id ? "var(--bg-sidebar-active)" : "transparent", color: active === item.id ? "var(--text-sidebar-active)" : "var(--text-sidebar)", fontSize: 14, fontWeight: active === item.id ? 500 : 400, textAlign: "left", width: "100%", transition: "background 0.15s, color 0.15s", cursor: "pointer" }}
      onMouseEnter={(e) => { if (active !== item.id) e.currentTarget.style.background = "var(--bg-sidebar-hover)"; }}
      onMouseLeave={(e) => { if (active !== item.id) e.currentTarget.style.background = "transparent"; }}>
      <NIcon name={item.icon} size={18} />
      {item.label}
    </button>
  );

  return (
    <aside style={{ width: "var(--sidebar-width)", background: "var(--bg-sidebar)", display: "flex", flexDirection: "column", height: "100%", flexShrink: 0, position: "relative" }}>
      <div style={{ padding: "20px 18px 16px", borderBottom: "1px solid oklch(28% 0.010 250)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <div style={{ width: 28, height: 28, borderRadius: 6, background: "var(--accent-red, var(--c-red))", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <NIcon name="search" size={14} style={{ color: "white" }} />
          </div>
          <div>
            <div style={{ color: "var(--text-sidebar-active)", fontSize: 13, fontWeight: 600, lineHeight: 1.2 }}>Duck Library</div>
            <div style={{ color: "oklch(55% 0.010 250)", fontSize: 11, lineHeight: 1.2 }}>Academic Search</div>
          </div>
        </div>
      </div>
      <nav style={{ padding: "10px 8px 6px", display: "flex", flexDirection: "column", gap: 2 }}>
        {navItems.map(btn)}
      </nav>
      <SidebarPanel app={app} />
      <div style={{ margin: "0 8px 10px", padding: "10px 12px", borderRadius: 7, background: online ? "oklch(28% 0.035 145)" : "oklch(28% 0.012 250)", border: `1px solid ${online ? "oklch(36% 0.055 145)" : "oklch(32% 0.010 250)"}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: online ? "oklch(72% 0.17 145)" : "oklch(55% 0.010 250)", flexShrink: 0 }} />
          <div>
            <div style={{ fontSize: 11, color: online ? "oklch(72% 0.17 145)" : "oklch(55% 0.010 250)", fontWeight: 500 }}>Search engine {online ? "Online" : "Offline"}</div>
            <div style={{ fontSize: 10, color: "oklch(50% 0.010 250)", marginTop: 1 }}>{online ? "Semantic index · 150M works" : "Sample data shown"}</div>
          </div>
        </div>
      </div>
      <div style={{ padding: "8px", borderTop: "1px solid oklch(28% 0.010 250)", display: "flex", flexDirection: "column", gap: 2 }}>
        {bottomItems.map(btn)}
      </div>
    </aside>
  );
};
