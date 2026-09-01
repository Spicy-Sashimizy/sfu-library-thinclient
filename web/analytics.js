/* AUTO-GENERATED from src/analytics.jsx by scripts/build_web.mjs — do not edit. */
const NIcon = ({
  name,
  size = 16,
  className = "",
  style = {}
}) => {
  const icons = {
    search: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "9",
      cy: "9",
      r: "6"
    }), /*#__PURE__*/React.createElement("path", {
      d: "m16 16-3.5-3.5"
    })),
    book: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M4 3h10a1 1 0 0 1 1 1v13l-2-1-2 1-2-1-2 1-2-1-2 1V4a1 1 0 0 1 1-1Z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M7 8h6M7 11h4"
    })),
    history: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "10",
      cy: "10",
      r: "7"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 6v4l2.5 2.5"
    })),
    bookmark: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M5 3h10v14l-5-3-5 3V3Z"
    })),
    settings: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "10",
      cy: "10",
      r: "2.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42"
    })),
    database: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("ellipse", {
      cx: "10",
      cy: "5.5",
      rx: "7",
      ry: "2.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M3 5.5v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5v-4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M3 9.5v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5v-4"
    })),
    admin: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 2L3 6v4c0 4.4 3.03 8.52 7 9.5 3.97-.98 7-5.1 7-9.5V6L10 2Z"
    })),
    copy: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("rect", {
      x: "8",
      y: "8",
      width: "9",
      height: "9",
      rx: "1.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M4 12V4a1 1 0 0 1 1-1h8"
    })),
    zotero: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "currentColor"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M4 4h12v2.5L8.5 14H16v2H4v-2.5L11.5 6H4V4Z"
    })),
    download: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 3v10m-4-4 4 4 4-4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M4 16h12"
    })),
    externalLink: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M8 3H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M13 3h4v4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M9 11 17 3"
    })),
    chevronDown: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "m5 8 5 5 5-5"
    })),
    chevronRight: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "m8 5 5 5-5 5"
    })),
    close: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M5 5 15 15M15 5 5 15"
    })),
    filter: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M3 5h14M6 10h8M9 15h2"
    })),
    sparkle: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 2v3M10 15v3M2 10h3M15 10h3M4.22 4.22l2.12 2.12M13.66 13.66l2.12 2.12M4.22 15.78l2.12-2.12M13.66 6.34l2.12-2.12"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: "10",
      cy: "10",
      r: "2"
    })),
    plus: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 4v12M4 10h12"
    })),
    edit: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M14.5 2.5a2.12 2.12 0 0 1 3 3L6 17l-4 1 1-4 11.5-11.5Z"
    })),
    trash: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M3 6h14M8 6V4h4v2M6 6v11a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V6"
    })),
    cpu: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("rect", {
      x: "4",
      y: "4",
      width: "12",
      height: "12",
      rx: "1.5"
    }), /*#__PURE__*/React.createElement("rect", {
      x: "7",
      y: "7",
      width: "6",
      height: "6",
      rx: "0.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M7 2v2M13 2v2M7 16v2M13 16v2M2 7h2M2 13h2M16 7h2M16 13h2"
    })),
    check: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2.2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "m4 10 4.5 4.5 7.5-8"
    })),
    warning: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 3 2 17h16L10 3Z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 9v4M10 14.5v1"
    })),
    activity: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M2 10h3l2-5 3 10 2-5h6"
    })),
    chart: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M3 17h14"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M6 14V9M10 14V5M14 14v-6"
    })),
    server: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("rect", {
      x: "3",
      y: "3.5",
      width: "14",
      height: "5.5",
      rx: "1.2"
    }), /*#__PURE__*/React.createElement("rect", {
      x: "3",
      y: "11",
      width: "14",
      height: "5.5",
      rx: "1.2"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M6 6.25h.01M6 13.75h.01"
    })),
    arrowLeft: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "m10 5-5 5 5 5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M5 10h11"
    })),
    info: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "10",
      cy: "10",
      r: "7"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 9v5M10 6.5v.5"
    })),
    link: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M8 13H5a4 4 0 0 1 0-8h3M12 7h3a4 4 0 0 1 0 8h-3M7 10h6"
    }))
  };
  return /*#__PURE__*/React.createElement("span", {
    className: className,
    style: {
      display: "inline-flex",
      alignItems: "center",
      ...style
    }
  }, icons[name] || null);
};
window.SFUHistory = function () {
  const KEY = "sfu_search_history_v1";
  const PENDING_KEY = "sfu_pending_rerun";
  const CAP = 100;
  function read() {
    try {
      return JSON.parse(localStorage.getItem(KEY)) || [];
    } catch (e) {
      return [];
    }
  }
  function write(list) {
    try {
      localStorage.setItem(KEY, JSON.stringify(list.slice(0, CAP)));
    } catch (e) {}
    try {
      window.dispatchEvent(new CustomEvent("sfu-history-changed"));
    } catch (e) {}
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
    remove: function (at) {
      write(read().filter(e => e.at !== at));
    },
    clear: function () {
      write([]);
    },
    setPending: function (q) {
      try {
        localStorage.setItem(PENDING_KEY, q);
      } catch (e) {}
    },
    takePending: function () {
      try {
        const q = localStorage.getItem(PENDING_KEY);
        if (q) localStorage.removeItem(PENDING_KEY);
        return q || null;
      } catch (e) {
        return null;
      }
    },
    timeAgo: function (at) {
      const s = Math.max(0, (Date.now() - at) / 1000);
      if (s < 60) return "just now";
      if (s < 3600) return Math.floor(s / 60) + "m ago";
      if (s < 86400) return Math.floor(s / 3600) + "h ago";
      if (s < 172800) return "yesterday";
      return new Date(at).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric"
      });
    }
  };
}();
const RecentSearchesPanel = ({
  app
}) => {
  const [entries, setEntries] = React.useState(() => window.SFUHistory ? window.SFUHistory.read() : []);
  React.useEffect(() => {
    const refresh = () => setEntries(window.SFUHistory ? window.SFUHistory.read() : []);
    window.addEventListener("sfu-history-changed", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("sfu-history-changed", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);
  const rerun = q => {
    if (app === "search") {
      window.dispatchEvent(new CustomEvent("sfu-history-rerun", {
        detail: {
          q
        }
      }));
    } else {
      if (window.SFUHistory) window.SFUHistory.setPending(q);
      if (window.parent !== window) window.parent.postMessage({
        suiteNav: "search"
      }, "*");else window.location.href = "search.html";
    }
  };
  if (!entries.length) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minHeight: 0,
        padding: "6px 12px",
        fontSize: 11,
        color: "oklch(55% 0.010 250)",
        lineHeight: 1.5
      }
    }, "No searches yet this session.", /*#__PURE__*/React.createElement("br", null), "Your recent queries will appear here.");
  }
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minHeight: 0,
      overflow: "auto",
      padding: "0 4px 4px"
    }
  }, entries.slice(0, 8).map(e => /*#__PURE__*/React.createElement("button", {
    key: e.at,
    onClick: () => rerun(e.q),
    title: 'Search again: ' + e.q,
    style: {
      display: "block",
      width: "100%",
      border: "none",
      background: "transparent",
      textAlign: "left",
      padding: "4px 8px",
      borderRadius: 4,
      cursor: "pointer"
    },
    onMouseEnter: ev => ev.currentTarget.style.background = "oklch(26% 0.014 250)",
    onMouseLeave: ev => ev.currentTarget.style.background = "transparent"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: 11,
      color: "var(--text-sidebar)",
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis",
      lineHeight: 1.35
    }
  }, e.q), /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: 9.5,
      color: "oklch(52% 0.010 250)",
      fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace"
    }
  }, window.SFUHistory.timeAgo(e.at), typeof e.results === "number" ? " · " + e.results + " results" : "", e.live === false ? " · sample" : ""))));
};
const QuickFiltersPanel = () => {
  const [active, setActive] = React.useState(new Set(["oa"]));
  const filters = [{
    id: "oa",
    label: "Open Access only",
    count: 12
  }, {
    id: "sfu",
    label: "Duck Library",
    count: 23
  }, {
    id: "peer",
    label: "Peer-reviewed",
    count: 41
  }, {
    id: "recent",
    label: "Last 5 years",
    count: 28
  }, {
    id: "review",
    label: "Review articles",
    count: 6
  }];
  const toggle = id => setActive(s => {
    const n = new Set(s);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minHeight: 0,
      overflow: "auto",
      padding: "2px 8px 8px",
      display: "flex",
      flexDirection: "column",
      gap: 2
    }
  }, filters.map(f => {
    const on = active.has(f.id);
    return /*#__PURE__*/React.createElement("button", {
      key: f.id,
      onClick: () => toggle(f.id),
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "5px 8px",
        borderRadius: 5,
        border: "none",
        background: on ? "oklch(28% 0.020 25)" : "transparent",
        color: on ? "var(--text-sidebar-active)" : "var(--text-sidebar)",
        fontSize: 11.5,
        fontFamily: "var(--font-ui)",
        textAlign: "left",
        cursor: "pointer",
        transition: "background 0.12s"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 12,
        height: 12,
        borderRadius: 3,
        border: `1.5px solid ${on ? "var(--accent-red-mid)" : "oklch(40% 0.010 250)"}`,
        background: on ? "var(--accent-red-mid)" : "transparent",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0
      }
    }, on && /*#__PURE__*/React.createElement(NIcon, {
      name: "check",
      size: 8,
      style: {
        color: "white"
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1
      }
    }, f.label), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 10,
        color: "oklch(55% 0.010 250)",
        fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace"
      }
    }, f.count));
  }));
};
const AiNotesPanel = () => /*#__PURE__*/React.createElement("div", {
  style: {
    flex: 1,
    minHeight: 0,
    overflow: "auto",
    padding: "2px 12px 8px"
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    fontSize: 11,
    color: "var(--text-sidebar)",
    lineHeight: 1.5,
    fontFamily: "var(--font-serif)",
    fontStyle: "italic",
    marginBottom: 8
  }
}, "\"Your last 3 searches converge on graph-based and transformer methods for molecular property prediction.\""), /*#__PURE__*/React.createElement("div", {
  style: {
    fontSize: 10,
    color: "oklch(60% 0.010 250)",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    marginBottom: 4,
    fontWeight: 500
  }
}, "Suggested next steps"), /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    flexDirection: "column",
    gap: 3
  }
}, ["→ Narrow to GNN architectures", "→ Add: \"reaction prediction\"", "→ Author cluster: Schwaller, Coley"].map(s => /*#__PURE__*/React.createElement("div", {
  key: s,
  style: {
    fontSize: 10.5,
    color: "var(--text-sidebar)",
    padding: "3px 6px",
    borderRadius: 4,
    cursor: "pointer",
    transition: "background 0.12s"
  },
  onMouseEnter: e => e.currentTarget.style.background = "oklch(26% 0.014 250)",
  onMouseLeave: e => e.currentTarget.style.background = "transparent"
}, s))));
const PANELS = {
  recent: {
    label: "Recent Searches",
    icon: "history",
    Comp: RecentSearchesPanel
  },
  filters: {
    label: "Quick Filters",
    icon: "filter",
    Comp: QuickFiltersPanel
  },
  notes: {
    label: "AI Notes",
    icon: "sparkle",
    Comp: AiNotesPanel
  }
};
const SidebarPanel = ({
  app
}) => {
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
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: open ? 1 : "0 0 auto",
      minHeight: 0,
      display: "flex",
      flexDirection: "column",
      borderTop: "1px solid oklch(26% 0.010 250)",
      marginTop: 4
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      padding: "8px 8px 6px",
      gap: 4
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: e => {
      e.stopPropagation();
      setMenuOpen(o => !o);
      if (!open) setOpen(true);
    },
    style: {
      display: "flex",
      alignItems: "center",
      gap: 5,
      padding: "3px 6px 3px 8px",
      border: "none",
      background: menuOpen ? "oklch(26% 0.014 250)" : "transparent",
      borderRadius: 4,
      cursor: "pointer",
      color: "oklch(70% 0.010 250)",
      fontSize: 10,
      letterSpacing: "0.06em",
      textTransform: "uppercase",
      fontWeight: 500,
      fontFamily: "var(--font-ui)"
    }
  }, /*#__PURE__*/React.createElement(NIcon, {
    name: cur.icon,
    size: 11,
    style: {
      color: "oklch(60% 0.010 250)"
    }
  }), cur.label, /*#__PURE__*/React.createElement(NIcon, {
    name: "chevronDown",
    size: 9,
    style: {
      color: "oklch(55% 0.010 250)",
      marginLeft: 1
    }
  })), /*#__PURE__*/React.createElement("button", {
    onClick: () => setOpen(o => !o),
    title: open ? "Hide panel" : "Show panel",
    style: {
      marginLeft: "auto",
      border: "none",
      background: "transparent",
      color: "oklch(55% 0.010 250)",
      cursor: "pointer",
      padding: 4,
      borderRadius: 4,
      display: "flex",
      alignItems: "center",
      transition: "color 0.12s, background 0.12s"
    },
    onMouseEnter: e => {
      e.currentTarget.style.color = "var(--text-sidebar-active)";
      e.currentTarget.style.background = "oklch(26% 0.014 250)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.color = "oklch(55% 0.010 250)";
      e.currentTarget.style.background = "transparent";
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "11",
    height: "11",
    viewBox: "0 0 11 11",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.6",
    strokeLinecap: "round"
  }, open ? /*#__PURE__*/React.createElement("path", {
    d: "M2 4l3.5 3.5L9 4"
  }) : /*#__PURE__*/React.createElement("path", {
    d: "M2 7l3.5-3.5L9 7"
  }), "      ")), menuOpen && /*#__PURE__*/React.createElement("div", {
    onClick: e => e.stopPropagation(),
    style: {
      position: "absolute",
      left: 8,
      marginTop: 28,
      width: 196,
      background: "oklch(22% 0.012 250)",
      border: "1px solid oklch(32% 0.012 250)",
      borderRadius: 7,
      padding: 4,
      boxShadow: "0 8px 24px oklch(0% 0 0 / 0.4)",
      zIndex: 100
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 9,
      color: "oklch(55% 0.010 250)",
      textTransform: "uppercase",
      letterSpacing: "0.08em",
      padding: "5px 8px 4px",
      fontWeight: 500
    }
  }, "Show in this slot"), Object.entries(PANELS).map(([key, p]) => /*#__PURE__*/React.createElement("button", {
    key: key,
    onClick: () => {
      setPanel(key);
      setMenuOpen(false);
      setOpen(true);
    },
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      width: "100%",
      padding: "6px 8px",
      border: "none",
      background: panel === key ? "oklch(28% 0.014 250)" : "transparent",
      color: panel === key ? "var(--text-sidebar-active)" : "var(--text-sidebar)",
      borderRadius: 4,
      fontSize: 11.5,
      cursor: "pointer",
      textAlign: "left",
      fontFamily: "var(--font-ui)"
    },
    onMouseEnter: e => {
      if (panel !== key) e.currentTarget.style.background = "oklch(26% 0.014 250)";
    },
    onMouseLeave: e => {
      if (panel !== key) e.currentTarget.style.background = "transparent";
    }
  }, /*#__PURE__*/React.createElement(NIcon, {
    name: p.icon,
    size: 12,
    style: {
      color: panel === key ? "var(--accent-red-mid)" : "oklch(60% 0.010 250)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1
    }
  }, p.label), panel === key && /*#__PURE__*/React.createElement(NIcon, {
    name: "check",
    size: 11,
    style: {
      color: "var(--accent-red-mid)"
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: "oklch(28% 0.012 250)",
      margin: "4px 4px"
    }
  }), /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      setOpen(false);
      setMenuOpen(false);
    },
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      width: "100%",
      padding: "6px 8px",
      border: "none",
      background: "transparent",
      color: "var(--text-sidebar)",
      borderRadius: 4,
      fontSize: 11.5,
      cursor: "pointer",
      textAlign: "left",
      fontFamily: "var(--font-ui)"
    },
    onMouseEnter: e => e.currentTarget.style.background = "oklch(26% 0.014 250)",
    onMouseLeave: e => e.currentTarget.style.background = "transparent"
  }, /*#__PURE__*/React.createElement(NIcon, {
    name: "close",
    size: 11,
    style: {
      color: "oklch(60% 0.010 250)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1
    }
  }, "Hide panel")))), open && /*#__PURE__*/React.createElement(Comp, {
    app: app
  }));
};
const SUITE_SEARCH_SCREENS = ["search", "saved", "history", "databases", "settings", "admin"];
const SuiteSidebar = ({
  app = "search",
  active,
  onScreen,
  hiddenScreens,
  interfacePrefs
}) => {
  const [online, setOnline] = React.useState(true);
  React.useEffect(() => {
    const onMsg = e => {
      if (e.data && typeof e.data.suiteDemo === "boolean") setOnline(!e.data.suiteDemo);
    };
    window.addEventListener("message", onMsg);
    if (window.parent === window && window.SFUApi) {
      window.SFUApi.health().then(r => setOnline(r.source === "live")).catch(() => {});
    }
    return () => window.removeEventListener("message", onMsg);
  }, []);
  const hid = hiddenScreens || {};
  const ip = interfacePrefs || {};
  const navItems = [{
    id: "search",
    icon: "search",
    label: "Search"
  }, {
    id: "saved",
    icon: "bookmark",
    label: "Saved",
    hide: hid.saved || !ip.savedHistoryNav
  }, {
    id: "history",
    icon: "history",
    label: "History",
    hide: hid.history || !ip.savedHistoryNav
  }, {
    id: "databases",
    icon: "database",
    label: "Databases",
    hide: hid.databases || !ip.databasesTab
  }, {
    id: "analytics",
    icon: "info",
    label: "About index",
    hide: !ip.analyticsApp && app === "search"
  }, {
    id: "index",
    icon: "server",
    label: "Index",
    hide: !ip.indexManagerApp && app === "search"
  }].filter(i => !i.hide);
  const bottomItems = [{
    id: "settings",
    icon: "settings",
    label: "Settings"
  }, {
    id: "admin",
    icon: "admin",
    label: "Admin",
    hide: hid.admin || !ip.adminPanels
  }].filter(i => !i.hide);
  const files = {
    search: "search.html",
    analytics: "analytics.html",
    index: "index_manager.html"
  };
  const go = id => {
    const isSearchScreen = SUITE_SEARCH_SCREENS.indexOf(id) !== -1;
    if (isSearchScreen && app === "search") {
      if (onScreen) onScreen(id);
      return;
    }
    if (id === app) return;
    if (window.parent !== window) window.parent.postMessage({
      suiteNav: id
    }, "*");else {
      const t = isSearchScreen ? "search.html" : files[id];
      if (t) window.location.href = t;
    }
  };
  const btn = item => /*#__PURE__*/React.createElement("button", {
    key: item.id,
    onClick: () => go(item.id),
    style: {
      display: "flex",
      alignItems: "center",
      gap: 12,
      padding: "11px 12px",
      borderRadius: 7,
      border: "none",
      background: active === item.id ? "var(--bg-sidebar-active)" : "transparent",
      color: active === item.id ? "var(--text-sidebar-active)" : "var(--text-sidebar)",
      fontSize: 14,
      fontWeight: active === item.id ? 500 : 400,
      textAlign: "left",
      width: "100%",
      transition: "background 0.15s, color 0.15s",
      cursor: "pointer"
    },
    onMouseEnter: e => {
      if (active !== item.id) e.currentTarget.style.background = "var(--bg-sidebar-hover)";
    },
    onMouseLeave: e => {
      if (active !== item.id) e.currentTarget.style.background = "transparent";
    }
  }, /*#__PURE__*/React.createElement(NIcon, {
    name: item.icon,
    size: 18
  }), item.label);
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      width: "var(--sidebar-width)",
      background: "var(--bg-sidebar)",
      display: "flex",
      flexDirection: "column",
      height: "100%",
      flexShrink: 0,
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px 18px 16px",
      borderBottom: "1px solid oklch(28% 0.010 250)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 9
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 6,
      background: "var(--accent-red, var(--c-red))",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(NIcon, {
    name: "search",
    size: 14,
    style: {
      color: "white"
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      color: "var(--text-sidebar-active)",
      fontSize: 13,
      fontWeight: 600,
      lineHeight: 1.2
    }
  }, "Duck Library"), /*#__PURE__*/React.createElement("div", {
    style: {
      color: "oklch(55% 0.010 250)",
      fontSize: 11,
      lineHeight: 1.2
    }
  }, "Academic Search")))), /*#__PURE__*/React.createElement("nav", {
    style: {
      padding: "10px 8px 6px",
      display: "flex",
      flexDirection: "column",
      gap: 2
    }
  }, navItems.map(btn)), /*#__PURE__*/React.createElement(SidebarPanel, {
    app: app
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      margin: "0 8px 10px",
      padding: "10px 12px",
      borderRadius: 7,
      background: online ? "oklch(28% 0.035 145)" : "oklch(28% 0.012 250)",
      border: `1px solid ${online ? "oklch(36% 0.055 145)" : "oklch(32% 0.010 250)"}`
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 7
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 7,
      height: 7,
      borderRadius: "50%",
      background: online ? "oklch(72% 0.17 145)" : "oklch(55% 0.010 250)",
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: online ? "oklch(72% 0.17 145)" : "oklch(55% 0.010 250)",
      fontWeight: 500
    }
  }, "Search engine ", online ? "Online" : "Offline"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: "oklch(50% 0.010 250)",
      marginTop: 1
    }
  }, online ? "Semantic index · 150M works" : "Sample data shown")))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "8px",
      borderTop: "1px solid oklch(28% 0.010 250)",
      display: "flex",
      flexDirection: "column",
      gap: 2
    }
  }, bottomItems.map(btn)));
};
const Icon = ({
  name,
  size = 16,
  style = {}
}) => {
  const I = {
    search: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "9",
      cy: "9",
      r: "6"
    }), /*#__PURE__*/React.createElement("path", {
      d: "m16 16-3.5-3.5"
    })),
    bookmark: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M5 3h10v14l-5-3-5 3V3Z"
    })),
    history: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "10",
      cy: "10",
      r: "7"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 6v4l2.5 2.5"
    })),
    database: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("ellipse", {
      cx: "10",
      cy: "5.5",
      rx: "7",
      ry: "2.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M3 5.5v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5v-4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M3 9.5v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5v-4"
    })),
    chart: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M3 17h14"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M6 14V9M10 14V5M14 14v-6"
    })),
    settings: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "10",
      cy: "10",
      r: "2.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42"
    })),
    admin: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 2L3 6v4c0 4.4 3.03 8.52 7 9.5 3.97-.98 7-5.1 7-9.5V6L10 2Z"
    })),
    server: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("rect", {
      x: "3",
      y: "3.5",
      width: "14",
      height: "5.5",
      rx: "1.2"
    }), /*#__PURE__*/React.createElement("rect", {
      x: "3",
      y: "11",
      width: "14",
      height: "5.5",
      rx: "1.2"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M6 6.25h.01M6 13.75h.01"
    })),
    globe: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "10",
      cy: "10",
      r: "7.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M2.5 10h15M10 2.5c2 2.2 3 4.8 3 7.5s-1 5.3-3 7.5c-2-2.2-3-4.8-3-7.5s1-5.3 3-7.5Z"
    })),
    route: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "5",
      cy: "15",
      r: "2"
    }), /*#__PURE__*/React.createElement("circle", {
      cx: "15",
      cy: "5",
      r: "2"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M7 15h5a3 3 0 0 0 3-3V7"
    })),
    clock: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "10",
      cy: "10",
      r: "7.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 5.5V10l3 2"
    })),
    scale: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 3v14M5 17h10M4 7l-2 5a3 3 0 0 0 6 0L6 7Zm10 0-2 5a3 3 0 0 0 6 0l-2-5ZM4 7l6-2 6 2"
    })),
    check: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "m4 10.5 4 4 8-9"
    })),
    chevronDown: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "m5 8 5 5 5-5"
    })),
    chevronRight: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "m8 5 5 5-5 5"
    })),
    arrowLeft: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "m10 5-5 5 5 5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M5 10h11"
    })),
    info: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("circle", {
      cx: "10",
      cy: "10",
      r: "7"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 9v5M10 6.5v.5"
    })),
    wrench: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M14 5.5a3.5 3.5 0 0 1-4.6 3.3l-4 4a1.7 1.7 0 0 1-2.4-2.4l4-4A3.5 3.5 0 0 1 14.5 2l-2 2 1.5 1.5 2-2c.3.6.5 1.2.5 2Z"
    }))
  };
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      ...style
    }
  }, I[name] || null);
};
const DISCLOSURES = [{
  id: 1,
  tone: "warn",
  icon: "database",
  title: "One source — and it has a shape",
  what: "Everything searchable comes from a single OpenAlex snapshot (June 2026). OpenAlex is strong on journal articles and conference papers, and noticeably thin on books, theses, grey literature, humanities monographs, and non-English venues.",
  matters: "If a work isn't in that snapshot, no search here can surface it — no matter how you phrase the query.",
  todo: "For books and humanities, also use the library catalogue and subject databases."
}, {
  id: 2,
  tone: "warn",
  icon: "globe",
  title: "Tuned for English",
  what: "The semantic model (a bert-base-uncased SPLADE encoder) and every section's vocabulary are English-only. Meaning-based matching effectively doesn't apply to other languages.",
  matters: "Scholarship in other languages — including Indigenous-language work and non-English-venue research — ranks lower or is missed entirely.",
  todo: "Search your key terms in the source language too, and lean on language-specific databases."
}, {
  id: 3,
  tone: "warn",
  icon: "route",
  title: "One discipline per query",
  what: "The router assigns each query to a single subject bucket, in priority order. Roughly 7 million documents sit in an unrouted \u201cother\u201d bucket the router rarely reaches.",
  matters: "A cross-disciplinary topic gets sent to just one discipline's section — the other side of the topic is never searched.",
  todo: "Re-run under a different subject profile, or use \u201cWiden search\u201d on the coverage card attached to your results."
}, {
  id: 4,
  tone: "warn",
  icon: "clock",
  title: "Recent by default",
  what: "The index is split at the year 2010. The default reader profile favours 2010-onward material, and the ranker adds a recency weight (0.15) on top.",
  matters: "Pre-2010 foundational and historical work ranks lower, and an active date filter can prune it from the search entirely.",
  todo: "Remove the date filter from the coverage card to bring older eras back into scope."
}, {
  id: 5,
  tone: "good",
  icon: "scale",
  title: "Ranked by text, not by prestige",
  what: "Results are ordered purely by how well their text matches your query. Citation counts, journal impact, and author reputation play no part in ranking.",
  matters: "This avoids a rich-get-richer bias — but it also means a highly-cited landmark paper gets no automatic lift. Judge quality yourself.",
  todo: null,
  positive: true
}];
const DisclosureCard = ({
  d,
  n
}) => {
  const tones = {
    warn: {
      bar: "var(--c-amber)",
      ic: "var(--c-amber-ink)",
      icbg: "var(--c-amber-soft)"
    },
    good: {
      bar: "var(--c-green)",
      ic: "oklch(42% 0.10 145)",
      icbg: "var(--c-green-soft)"
    }
  };
  const t = tones[d.tone];
  return /*#__PURE__*/React.createElement("section", {
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderLeft: `3px solid ${t.bar}`,
      borderRadius: "var(--radius-lg)",
      padding: "24px 28px",
      display: "flex",
      gap: 18,
      boxShadow: "var(--shadow-sm)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 8,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 38,
      height: 38,
      borderRadius: 10,
      background: t.icbg,
      color: t.ic,
      display: "flex",
      alignItems: "center",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: d.icon,
    size: 19
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11,
      color: "var(--text-faint)"
    }
  }, String(n).padStart(2, "0"))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 18,
      fontWeight: 500,
      color: "var(--text)",
      marginBottom: 8,
      display: "flex",
      alignItems: "center",
      gap: 10,
      flexWrap: "wrap"
    }
  }, d.title, d.positive && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10.5,
      fontWeight: 500,
      letterSpacing: "0.06em",
      textTransform: "uppercase",
      padding: "2px 8px",
      borderRadius: 4,
      background: "var(--c-green-soft)",
      color: "oklch(42% 0.10 145)"
    }
  }, "By design")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 13.5,
      color: "var(--text-secondary)",
      lineHeight: 1.6,
      marginBottom: 12,
      maxWidth: "70ch"
    }
  }, d.what), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 14
    },
    className: "disc-grid"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "11px 14px",
      background: "var(--bg-soft)",
      borderRadius: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10.5,
      fontWeight: 600,
      letterSpacing: "0.07em",
      textTransform: "uppercase",
      color: "var(--text-muted)",
      marginBottom: 4
    }
  }, "Why it matters"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)",
      lineHeight: 1.55
    }
  }, d.matters)), d.todo && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "11px 14px",
      background: "var(--c-teal-soft)",
      borderRadius: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10.5,
      fontWeight: 600,
      letterSpacing: "0.07em",
      textTransform: "uppercase",
      color: "oklch(40% 0.10 200)",
      marginBottom: 4
    }
  }, "What to do"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "oklch(34% 0.07 200)",
      lineHeight: 1.55
    }
  }, d.todo)))));
};
const TOTAL_DOCS = 150413098;
const fmtM = n => (n / 1e6).toFixed(1) + "M";
const DISCIPLINES = [{
  name: "Health & Medicine",
  v: 41.2,
  color: "var(--c-red)"
}, {
  name: "Natural Sciences",
  v: 38.0,
  color: "var(--c-teal)"
}, {
  name: "Engineering & CS",
  v: 24.8,
  color: "var(--c-indigo)"
}, {
  name: "Social Sciences",
  v: 22.4,
  color: "var(--c-amber)"
}, {
  name: "Arts & Humanities",
  v: 17.0,
  color: "var(--c-violet)"
}, {
  name: "Other / unrouted",
  v: 7.0,
  color: "oklch(72% 0.012 250)"
}];
const ERAS = [{
  name: "2010 – present",
  pct: 63,
  color: "var(--c-teal)"
}, {
  name: "pre-2010",
  pct: 37,
  color: "oklch(72% 0.012 250)"
}];
const LANGS = [{
  name: "English",
  pct: 76
}, {
  name: "Chinese",
  pct: 6
}, {
  name: "Spanish",
  pct: 4
}, {
  name: "German",
  pct: 3
}, {
  name: "French",
  pct: 3
}, {
  name: "Other (40+ languages)",
  pct: 8
}];
const Panel = ({
  icon,
  title,
  sub,
  children
}) => /*#__PURE__*/React.createElement("section", {
  style: {
    background: "var(--bg-panel)",
    border: "1px solid var(--border-light)",
    borderRadius: "var(--radius-lg)",
    padding: "24px 26px",
    display: "flex",
    flexDirection: "column",
    gap: 18,
    boxShadow: "var(--shadow-sm)"
  }
}, /*#__PURE__*/React.createElement("header", {
  style: {
    display: "flex",
    gap: 11,
    alignItems: "flex-start"
  }
}, /*#__PURE__*/React.createElement("span", {
  style: {
    width: 30,
    height: 30,
    borderRadius: 8,
    background: "var(--bg-soft)",
    color: "var(--text-secondary)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0
  }
}, /*#__PURE__*/React.createElement(Icon, {
  name: icon,
  size: 16
})), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
  style: {
    fontFamily: "var(--font-serif)",
    fontSize: 16.5,
    fontWeight: 500,
    color: "var(--text)",
    lineHeight: 1.2
  }
}, title), /*#__PURE__*/React.createElement("p", {
  style: {
    fontSize: 12,
    color: "var(--text-muted)",
    marginTop: 2
  }
}, sub))), children);
const DisciplineBars = () => {
  const max = Math.max(...DISCIPLINES.map(d => d.v));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 11
    }
  }, DISCIPLINES.map(d => /*#__PURE__*/React.createElement("div", {
    key: d.name,
    style: {
      display: "grid",
      gridTemplateColumns: "132px 1fr 52px",
      alignItems: "center",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      color: "var(--text)",
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis"
    }
  }, d.name), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 14,
      background: "var(--bg-soft)",
      borderRadius: 4,
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: `${d.v / max * 100}%`,
      height: "100%",
      background: d.color,
      borderRadius: 4
    }
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11.5,
      color: "var(--text-secondary)",
      textAlign: "right"
    }
  }, d.v, "M"))));
};
const StackBar = ({
  rows
}) => /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    flexDirection: "column",
    gap: 14
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    height: 38,
    borderRadius: 8,
    overflow: "hidden",
    border: "1px solid var(--border-light)"
  }
}, rows.map(r => /*#__PURE__*/React.createElement("div", {
  key: r.name,
  title: `${r.name}: ${r.pct}%`,
  style: {
    width: `${r.pct}%`,
    background: r.color || "var(--c-teal)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center"
  }
}, r.pct >= 12 && /*#__PURE__*/React.createElement("span", {
  style: {
    fontFamily: "var(--font-mono)",
    fontSize: 12,
    fontWeight: 500,
    color: "white"
  }
}, r.pct, "%")))), /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    flexDirection: "column",
    gap: 7
  }
}, rows.map(r => /*#__PURE__*/React.createElement("div", {
  key: r.name,
  style: {
    display: "flex",
    alignItems: "center",
    gap: 9,
    fontSize: 12.5
  }
}, /*#__PURE__*/React.createElement("span", {
  style: {
    width: 10,
    height: 10,
    borderRadius: 3,
    background: r.color || "var(--c-teal)",
    flexShrink: 0
  }
}), /*#__PURE__*/React.createElement("span", {
  style: {
    color: "var(--text)",
    flex: 1
  }
}, r.name), /*#__PURE__*/React.createElement("span", {
  style: {
    fontFamily: "var(--font-mono)",
    fontSize: 11.5,
    color: "var(--text-secondary)"
  }
}, r.pct, "%")))));
const LangBars = () => {
  const palette = ["var(--c-teal)", "var(--c-indigo)", "var(--c-amber)", "var(--c-violet)", "var(--c-green)", "oklch(72% 0.012 250)"];
  return /*#__PURE__*/React.createElement(StackBar, {
    rows: LANGS.map((l, i) => ({
      ...l,
      color: palette[i]
    }))
  });
};
const OP_METRICS = [{
  label: "NDCG@10",
  value: "0.561",
  note: "mean over the eval set"
}, {
  label: "Recall@50",
  value: "0.967",
  note: "vs 0.966 un-quantized"
}, {
  label: "RRF k",
  value: "60",
  note: "rank-fusion constant"
}, {
  label: "Dense seed",
  value: "600k",
  note: "+ warm-cache delta"
}];
const LEG_LATENCY = [{
  leg: "Keyword (tantivy)",
  ms: 34,
  color: "var(--c-teal)"
}, {
  leg: "Semantic-sparse (SPLADE)",
  ms: 88,
  color: "var(--c-indigo)"
}, {
  leg: "Semantic-dense",
  ms: 61,
  color: "var(--c-violet)"
}, {
  leg: "Rerank + fuse",
  ms: 47,
  color: "var(--c-amber)"
}];
const OperatorSection = ({
  metrics = OP_METRICS,
  latency = LEG_LATENCY
}) => {
  const [open, setOpen] = React.useState(false);
  const maxMs = Math.max(...latency.map(l => l.ms));
  return /*#__PURE__*/React.createElement("section", {
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: "var(--radius-lg)",
      boxShadow: "var(--shadow-sm)",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setOpen(o => !o),
    style: {
      width: "100%",
      display: "flex",
      alignItems: "center",
      gap: 13,
      padding: "18px 26px",
      border: "none",
      background: "transparent",
      textAlign: "left"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 32,
      height: 32,
      borderRadius: 8,
      background: "var(--bg-soft)",
      color: "var(--text-secondary)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "wrench",
    size: 16
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 14,
      fontWeight: 600,
      color: "var(--text)"
    }
  }, "Operator & methodology"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginTop: 1
    }
  }, "Measured-quality metrics and per-engine timing \u2014 for people maintaining or auditing the system.")), /*#__PURE__*/React.createElement(Icon, {
    name: open ? "chevronDown" : "chevronRight",
    size: 16,
    style: {
      color: "var(--text-muted)"
    }
  })), open && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "4px 26px 26px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 10,
      padding: "11px 14px",
      background: "var(--c-amber-soft)",
      borderRadius: 8,
      marginBottom: 20
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "info",
    size: 15,
    style: {
      color: "var(--c-amber-ink)",
      flexShrink: 0,
      marginTop: 1
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)",
      lineHeight: 1.55
    }
  }, "These are engineering measurements, not a quality guarantee. A single NDCG figure says how well the ranker reproduced a labelled test set \u2014 it does ", /*#__PURE__*/React.createElement("strong", null, "not"), " certify that any given search was complete or unbiased. The disclosures above are the honest answer to that question.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: 12,
      marginBottom: 22
    },
    className: "op-grid"
  }, metrics.map(m => /*#__PURE__*/React.createElement("div", {
    key: m.label,
    style: {
      padding: "14px 16px",
      background: "var(--bg-soft)",
      borderRadius: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10.5,
      fontWeight: 600,
      letterSpacing: "0.07em",
      textTransform: "uppercase",
      color: "var(--text-muted)",
      marginBottom: 6
    }
  }, m.label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 26,
      fontWeight: 500,
      color: "var(--text)",
      lineHeight: 1
    }
  }, m.value), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)",
      marginTop: 5
    }
  }, m.note)))), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: "0.07em",
      textTransform: "uppercase",
      color: "var(--text-muted)",
      marginBottom: 12
    }
  }, "Per-engine latency \xB7 median ms"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 10
    }
  }, latency.map(l => /*#__PURE__*/React.createElement("div", {
    key: l.leg,
    style: {
      display: "grid",
      gridTemplateColumns: "190px 1fr 44px",
      alignItems: "center",
      gap: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      color: "var(--text)"
    }
  }, l.leg), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 12,
      background: "var(--bg-soft)",
      borderRadius: 4,
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: `${l.ms / maxMs * 100}%`,
      height: "100%",
      background: l.color,
      borderRadius: 4
    }
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: 11.5,
      color: "var(--text-secondary)",
      textAlign: "right"
    }
  }, l.ms)))), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      lineHeight: 1.6,
      marginTop: 20,
      maxWidth: "78ch"
    }
  }, "Three retrieval legs run in parallel and are combined with Reciprocal Rank Fusion (k = 60). The dense leg is a 600k-vector seed plus a warm-cache delta against the full ", TOTAL_DOCS.toLocaleString(), "-document corpus, so semantic coverage is query-driven, not exhaustive. SPLADE keeps the top 64 query terms; impact weights are 8-bit quantized. Index split at era boundary 2010, 5 subjects \xD7 2 eras = 10 sections.")));
};
const FACTS = [{
  label: "Documents",
  value: TOTAL_DOCS.toLocaleString()
}, {
  label: "Source",
  value: "OpenAlex",
  sub: "June 2026 snapshot"
}, {
  label: "Sections",
  value: "10",
  sub: "5 subjects × 2 eras"
}, {
  label: "Era boundary",
  value: "2010",
  sub: "recent vs historical"
}];
function deriveLive(bundle) {
  const panels = bundle && bundle.panels || {};
  const kpis = panels.kpis || {};
  const ndcg = panels.ndcg_by_subject || {};
  const facts = FACTS.map(f => {
    if (f.label === "Documents" && kpis.documents) return {
      ...f,
      value: Number(kpis.documents).toLocaleString()
    };
    if (f.label === "Source" && kpis.snapshot) return {
      ...f,
      sub: kpis.snapshot
    };
    return f;
  });
  let metrics = OP_METRICS;
  if (ndcg.status === "ok" && Array.isArray(ndcg.subjects) && ndcg.subjects.length) {
    const mean = ndcg.subjects.reduce((a, s) => a + (s.ndcg || 0), 0) / ndcg.subjects.length;
    metrics = OP_METRICS.map(m => m.label === "NDCG@10" ? {
      ...m,
      value: mean.toFixed(3)
    } : m);
  }
  return {
    facts,
    metrics
  };
}
const App = () => {
  const [{
    facts,
    metrics
  }, setLive] = React.useState({
    facts: FACTS,
    metrics: OP_METRICS
  });
  React.useEffect(() => {
    let cancelled = false;
    if (window.SFUApi) {
      window.SFUApi.analytics().then(res => {
        if (cancelled) return;
        if (res.source === "live") setLive(deriveLive(res.data));
      });
    }
    return () => {
      cancelled = true;
    };
  }, []);
  const goSearch = () => {
    if (window.parent !== window) window.parent.postMessage({
      suiteNav: "search"
    }, "*");else window.location.href = "search.html";
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      height: "100%",
      minHeight: "100vh"
    },
    "data-screen-label": "About this index"
  }, /*#__PURE__*/React.createElement(SuiteSidebar, {
    app: "analytics",
    active: "analytics"
  }), /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      overflow: "auto",
      display: "flex",
      flexDirection: "column"
    }
  }, /*#__PURE__*/React.createElement("header", {
    style: {
      padding: "32px 48px 28px",
      borderBottom: "1px solid var(--border-light)",
      background: "var(--bg-panel)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11.5,
      fontWeight: 500,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      color: "var(--text-muted)",
      marginBottom: 8
    }
  }, "About this index"), /*#__PURE__*/React.createElement("h1", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 31,
      fontWeight: 500,
      color: "var(--text)",
      lineHeight: 1.15,
      marginBottom: 8,
      textWrap: "balance"
    }
  }, "What the search reads from \u2014 and where it's thin"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 14.5,
      color: "var(--text-secondary)",
      maxWidth: "72ch",
      lineHeight: 1.6
    }
  }, "Read this before treating a search as a complete picture of the literature. It describes the whole collection behind the search box \u2014 its single source, its language and discipline skew, and how it's split by era. The coverage card on each result set tells you which of these limits hit ", /*#__PURE__*/React.createElement("em", null, "your"), " specific search."), /*#__PURE__*/React.createElement("button", {
    onClick: goSearch,
    style: {
      marginTop: 18,
      display: "inline-flex",
      alignItems: "center",
      gap: 7,
      padding: "8px 14px",
      border: "1px solid var(--border)",
      borderRadius: 8,
      background: "var(--bg-panel)",
      fontSize: 13,
      color: "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "arrowLeft",
    size: 14
  }), " Back to search")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "28px 48px 56px",
      display: "flex",
      flexDirection: "column",
      gap: 28,
      maxWidth: 1180
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 14,
      flexWrap: "wrap"
    }
  }, facts.map(f => /*#__PURE__*/React.createElement("div", {
    key: f.label,
    style: {
      flex: "1 1 200px",
      minWidth: 180,
      padding: "18px 22px",
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: "var(--radius)",
      boxShadow: "var(--shadow-sm)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 500,
      letterSpacing: "0.07em",
      textTransform: "uppercase",
      color: "var(--text-muted)",
      marginBottom: 7
    }
  }, f.label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 25,
      fontWeight: 500,
      color: "var(--text)",
      lineHeight: 1
    }
  }, f.value), f.sub && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginTop: 5
    }
  }, f.sub)))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      justifyContent: "space-between",
      gap: 16,
      marginBottom: 16,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 21,
      fontWeight: 500,
      color: "var(--text)"
    }
  }, "Five things the collection won't tell you on its own"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)"
    }
  }, "Ordered by how easily they distort a literature review")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, DISCLOSURES.map((d, i) => /*#__PURE__*/React.createElement(DisclosureCard, {
    key: d.id,
    d: d,
    n: i + 1
  })))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      justifyContent: "space-between",
      gap: 16,
      marginBottom: 16,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 21,
      fontWeight: 500,
      color: "var(--text)"
    }
  }, "The shape of the index"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)"
    }
  }, "Approximate \xB7 section manifests, June 2026")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1.3fr 1fr",
      gap: 18
    },
    className: "dist-grid"
  }, /*#__PURE__*/React.createElement(Panel, {
    icon: "route",
    title: "By discipline",
    sub: "How the router's buckets divide the corpus"
  }, /*#__PURE__*/React.createElement(DisciplineBars, null)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 18
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    icon: "clock",
    title: "By era",
    sub: "Split at the 2010 boundary"
  }, /*#__PURE__*/React.createElement(StackBar, {
    rows: ERAS
  })), /*#__PURE__*/React.createElement(Panel, {
    icon: "globe",
    title: "By language",
    sub: "Semantic matching applies to English only"
  }, /*#__PURE__*/React.createElement(LangBars, null))))), /*#__PURE__*/React.createElement(OperatorSection, {
    metrics: metrics
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      textAlign: "center",
      lineHeight: 1.6
    }
  }, "This page is linked from the ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text-secondary)"
    }
  }, "coverage card"), " shown at the top of every result set."))), /*#__PURE__*/React.createElement("style", null, `
        @media (max-width: 1024px) {
          .dist-grid { grid-template-columns: 1fr !important; }
          .op-grid { grid-template-columns: repeat(2, 1fr) !important; }
          .disc-grid { grid-template-columns: 1fr !important; }
        }
      `));
};
ReactDOM.createRoot(document.getElementById("root")).render(/*#__PURE__*/React.createElement(App, null));