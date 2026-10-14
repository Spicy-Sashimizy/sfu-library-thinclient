/* AUTO-GENERATED from source/index_manager.jsx by scripts/build_web.mjs — do not edit. */
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
    flame: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 3c2.2 2.9 4.5 4.6 4.5 7.5a4.5 4.5 0 1 1-9 0C5.5 7.6 7.8 5.9 10 3Z"
    })),
    snow: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 3v14M4 6.5l12 7M16 6.5l-12 7"
    })),
    box: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 2.5 17 6v8l-7 3.5L3 14V6l7-3.5Z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M3 6l7 3.5L17 6M10 9.5v8"
    })),
    zap: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M11 2 4 11h5l-1 7 7-9h-5l1-7Z"
    })),
    refresh: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M16.5 10a6.5 6.5 0 1 1-1.9-4.6"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M16.5 2.5v3h-3"
    })),
    layers: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 2.5 18 6.5l-8 4-8-4 8-4Z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M2 10.5l8 4 8-4M2 14.5l8 4 8-4"
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
      x: "5.5",
      y: "5.5",
      width: "9",
      height: "9",
      rx: "1.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M8 2v3.5M12 2v3.5M8 14.5V18M12 14.5V18M2 8h3.5M2 12h3.5M14.5 8H18M14.5 12H18"
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
      d: "M2 10.5h3l2-5.5 4.5 11 2-5.5H18"
    })),
    check: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "m4 10.5 4 4 8-9"
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
      d: "M10 3 2.5 16h15L10 3Z"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 8.5v3.5M10 14.5v.5"
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
    upload: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M10 13V3m-4 4 4-4 4 4"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M4 16h12"
    })),
    drive: /*#__PURE__*/React.createElement("svg", {
      width: size,
      height: size,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }, /*#__PURE__*/React.createElement("rect", {
      x: "2.5",
      y: "7",
      width: "15",
      height: "6.5",
      rx: "1.5"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M2.5 10.25h15M14.5 11.6h.01"
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
const Badge = ({
  tone = "muted",
  children,
  style = {}
}) => {
  const tones = {
    hot: {
      bg: "var(--c-red-soft)",
      color: "oklch(44% 0.13 25)"
    },
    cold: {
      bg: "var(--c-teal-soft)",
      color: "oklch(38% 0.10 200)"
    },
    ok: {
      bg: "var(--c-green-soft)",
      color: "oklch(40% 0.11 145)"
    },
    warn: {
      bg: "var(--c-amber-soft)",
      color: "oklch(46% 0.10 70)"
    },
    violet: {
      bg: "var(--c-violet-soft)",
      color: "oklch(42% 0.10 295)"
    },
    muted: {
      bg: "var(--bg-soft)",
      color: "var(--text-muted)"
    }
  };
  const t = tones[tone] || tones.muted;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10.5,
      fontWeight: 500,
      letterSpacing: "0.06em",
      textTransform: "uppercase",
      padding: "2.5px 8px",
      borderRadius: 4,
      background: t.bg,
      color: t.color,
      whiteSpace: "nowrap",
      ...style
    }
  }, children);
};
const StatCard = ({
  label,
  value,
  sub,
  icon,
  color = "var(--c-teal)"
}) => /*#__PURE__*/React.createElement("div", {
  style: {
    background: "var(--bg-panel)",
    border: "1px solid var(--border-light)",
    borderRadius: 8,
    padding: "12px 14px"
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8
  }
}, /*#__PURE__*/React.createElement("span", {
  style: {
    fontSize: 11,
    color: "var(--text-muted)",
    textTransform: "uppercase",
    letterSpacing: "0.05em"
  }
}, label), icon && /*#__PURE__*/React.createElement(Icon, {
  name: icon,
  size: 14,
  style: {
    color
  }
})), /*#__PURE__*/React.createElement("div", {
  style: {
    fontSize: 20,
    fontWeight: 600,
    color: "var(--text)",
    fontVariantNumeric: "tabular-nums",
    lineHeight: 1.2
  }
}, value), sub && /*#__PURE__*/React.createElement("div", {
  style: {
    fontSize: 11.5,
    color: "var(--text-muted)",
    marginTop: 3
  }
}, sub));
const ResultCacheCard = () => {
  const [rc, setRc] = React.useState(null);
  const [src, setSrc] = React.useState("loading");
  React.useEffect(() => {
    let alive = true;
    const tick = () => {
      if (!window.SFUApi) return;
      window.SFUApi.health().then(r => {
        if (!alive) return;
        setSrc(r.source);
        setRc(r.data && r.data.result_cache || null);
      }).catch(() => {
        if (alive) {
          setSrc("mock");
          setRc(null);
        }
      });
    };
    tick();
    const h = setInterval(tick, 10000);
    return () => {
      alive = false;
      clearInterval(h);
    };
  }, []);
  const live = src === "live";
  const enabled = rc && rc.enabled;
  const ratio = rc && typeof rc.hit_ratio === "number" ? `${Math.round(rc.hit_ratio * 100)}%` : "—";
  const resident = rc && typeof rc.resident === "number" ? String(rc.resident) : "—";
  const tone = !live ? "muted" : enabled ? "ok" : "warn";
  const label = !live ? "Result cache · demo" : enabled ? "Result cache · live" : "Result cache · OFF";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 8,
      padding: "12px 14px",
      gridColumn: "span 2"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, label, " ", /*#__PURE__*/React.createElement(Badge, {
    tone: tone
  }, !live ? "demo" : enabled ? "on" : "off (env gate)")), /*#__PURE__*/React.createElement(Icon, {
    name: "zap",
    size: 14,
    style: {
      color: "var(--c-amber)"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 18,
      alignItems: "baseline"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 20,
      fontWeight: 600,
      color: "var(--text)",
      fontVariantNumeric: "tabular-nums",
      lineHeight: 1.2
    }
  }, ratio), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      marginTop: 3
    }
  }, "hit ratio (hits / hits+miss)")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 20,
      fontWeight: 600,
      color: "var(--text)",
      fontVariantNumeric: "tabular-nums",
      lineHeight: 1.2
    }
  }, resident), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      marginTop: 3
    }
  }, "resident entries (cap 256)"))));
};
const Panel = ({
  title,
  action,
  children,
  style = {},
  pad = "14px 16px"
}) => /*#__PURE__*/React.createElement("section", {
  style: {
    background: "var(--bg-panel)",
    border: "1px solid var(--border-light)",
    borderRadius: 8,
    padding: pad,
    boxShadow: "var(--shadow-sm)",
    ...style
  }
}, (title || action) && /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    marginBottom: 12,
    padding: pad === "0" ? "12px 16px 0" : 0
  }
}, title && /*#__PURE__*/React.createElement("div", {
  style: {
    fontSize: 11,
    fontWeight: 600,
    color: "var(--text-muted)",
    textTransform: "uppercase",
    letterSpacing: "0.05em"
  }
}, title), action || null), children);
const MiniBar = ({
  value,
  max,
  color = "var(--c-teal)",
  height = 6
}) => /*#__PURE__*/React.createElement("div", {
  style: {
    height,
    borderRadius: height / 2,
    background: "var(--bg-soft)",
    overflow: "hidden",
    width: "100%"
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    width: `${Math.min(100, value / max * 100)}%`,
    height: "100%",
    borderRadius: height / 2,
    background: color,
    transition: "width 0.4s ease"
  }
}));
const GhostBtn = ({
  children,
  onClick,
  accent = false,
  disabled = false,
  small = false,
  title
}) => /*#__PURE__*/React.createElement("button", {
  onClick: onClick,
  disabled: disabled,
  title: title,
  style: {
    fontSize: small ? 11 : 12,
    padding: small ? "3px 9px" : "6px 12px",
    background: accent ? "var(--c-red)" : "var(--bg)",
    color: accent ? "white" : disabled ? "var(--text-faint)" : "var(--text-secondary)",
    border: accent ? "none" : "1px solid var(--border)",
    borderRadius: 5,
    cursor: disabled ? "default" : "pointer",
    fontFamily: "var(--font-ui)",
    fontWeight: accent ? 500 : 400,
    opacity: disabled ? 0.6 : 1,
    whiteSpace: "nowrap",
    display: "inline-flex",
    alignItems: "center",
    gap: 5
  }
}, children);
const Mono = ({
  children,
  style = {}
}) => /*#__PURE__*/React.createElement("span", {
  style: {
    fontFamily: "var(--font-mono)",
    fontSize: "0.92em",
    ...style
  }
}, children);
const Toggle = ({
  on,
  setOn,
  label
}) => /*#__PURE__*/React.createElement("button", {
  onClick: () => setOn(!on),
  style: {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    background: "transparent",
    border: "none",
    padding: 0
  }
}, /*#__PURE__*/React.createElement("span", {
  style: {
    width: 34,
    height: 19,
    borderRadius: 10,
    background: on ? "var(--c-green)" : "var(--border)",
    position: "relative",
    transition: "background 0.2s",
    flexShrink: 0,
    display: "inline-block"
  }
}, /*#__PURE__*/React.createElement("span", {
  style: {
    position: "absolute",
    top: 2,
    left: on ? 17 : 2,
    width: 15,
    height: 15,
    borderRadius: "50%",
    background: "white",
    boxShadow: "0 1px 2px oklch(0% 0 0 / 0.2)",
    transition: "left 0.2s",
    display: "inline-block"
  }
})), label && /*#__PURE__*/React.createElement(Mono, {
  style: {
    fontSize: 11.5,
    color: "var(--text-secondary)"
  }
}, label));
const IM_SECTIONS = [{
  id: "social_sciences__recent",
  base: "social_sciences",
  era: "recent",
  docsM: 27.4,
  live: 20.5,
  packed: 9.8,
  ratio: "2.1×"
}, {
  id: "social_sciences__archive",
  base: "social_sciences",
  era: "archive",
  docsM: 7.8,
  live: 7.9,
  packed: 3.8,
  ratio: "2.1×"
}, {
  id: "med_bio__recent",
  base: "med_bio",
  era: "recent",
  docsM: 12.6,
  live: 10.4,
  packed: 5.0,
  ratio: "2.1×"
}, {
  id: "med_bio__archive",
  base: "med_bio",
  era: "archive",
  docsM: 4.5,
  live: 3.5,
  packed: 1.7,
  ratio: "2.1×"
}, {
  id: "phys_eng__recent",
  base: "phys_eng",
  era: "recent",
  docsM: 6.1,
  live: 5.0,
  packed: 2.4,
  ratio: "2.1×"
}, {
  id: "phys_eng__archive",
  base: "phys_eng",
  era: "archive",
  docsM: 2.2,
  live: 1.7,
  packed: 0.8,
  ratio: "2.1×"
}, {
  id: "cs_math__recent",
  base: "cs_math",
  era: "recent",
  docsM: 11.4,
  live: 9.4,
  packed: 4.5,
  ratio: "2.1×"
}, {
  id: "cs_math__archive",
  base: "cs_math",
  era: "archive",
  docsM: 4.1,
  live: 3.1,
  packed: 1.5,
  ratio: "2.1×"
}, {
  id: "other__recent",
  base: "other",
  era: "recent",
  docsM: 54.6,
  live: 44.1,
  packed: 21.0,
  ratio: "2.1×"
}, {
  id: "other__archive",
  base: "other",
  era: "archive",
  docsM: 19.7,
  live: 15.9,
  packed: 7.6,
  ratio: "2.1×"
}];
const IM_PERSONAS = [{
  id: "political_science",
  hot: ["social_sciences__recent"],
  kind: "Subject · recent era"
}, {
  id: "political_science_historical",
  hot: ["social_sciences__archive"],
  kind: "Subject · archive era"
}, {
  id: "computer_science",
  hot: ["cs_math__recent"],
  kind: "Subject · recent era"
}, {
  id: "health_science",
  hot: ["med_bio__recent"],
  kind: "Subject · recent era"
}, {
  id: "interdisciplinary",
  hot: ["social_sciences__recent", "med_bio__recent", "cs_math__recent"],
  kind: "3 hot sections"
}, {
  id: "contemporary",
  hot: IM_SECTIONS.filter(s => s.era === "recent").map(s => s.id),
  kind: "Era-wide · ≥ 2010"
}, {
  id: "historical",
  hot: IM_SECTIONS.filter(s => s.era === "archive").map(s => s.id),
  kind: "Era-wide · < 2010"
}, {
  id: "all_hot",
  hot: IM_SECTIONS.map(s => s.id),
  kind: "Testbed · everything live",
  testbed: true
}];
const META_GB = 10.2;
const DENSE_GB = 7.2;
const sidecarGB = docsM => docsM * 0.352;
const PersonasScreen = () => {
  const [personaId, setPersonaId] = React.useState("political_science");
  const [unpacked, setUnpacked] = React.useState({});
  const [unpacking, setUnpacking] = React.useState({});
  const persona = IM_PERSONAS.find(p => p.id === personaId);
  const stateOf = s => persona.hot.includes(s.id) ? "hot" : unpacking[s.id] != null ? "unpacking" : unpacked[s.id] ? "unpacked" : "cold";
  const startUnpack = id => {
    if (unpacking[id] != null) return;
    if (window.SFUApi) window.SFUApi.unpack(id);
    setUnpacking(u => ({
      ...u,
      [id]: 0
    }));
    const t = setInterval(() => {
      setUnpacking(u => {
        if (u[id] == null) {
          clearInterval(t);
          return u;
        }
        const v = u[id] + 0.07 + Math.random() * 0.05;
        if (v >= 1) {
          clearInterval(t);
          setUnpacked(d => ({
            ...d,
            [id]: true
          }));
          const {
            [id]: _,
            ...rest
          } = u;
          return rest;
        }
        return {
          ...u,
          [id]: v
        };
      });
    }, 320);
  };
  const repack = id => setUnpacked(d => {
    const {
      [id]: _,
      ...rest
    } = d;
    return rest;
  });
  const hotSecs = IM_SECTIONS.filter(s => stateOf(s) === "hot");
  const tempSecs = IM_SECTIONS.filter(s => stateOf(s) === "unpacked");
  const coldSecs = IM_SECTIONS.filter(s => ["cold", "unpacking"].includes(stateOf(s)));
  const hotLive = hotSecs.reduce((a, s) => a + s.live, 0);
  const sidecars = hotSecs.reduce((a, s) => a + sidecarGB(s.docsM), 0);
  const tempLive = tempSecs.reduce((a, s) => a + s.live, 0);
  const coldPacked = coldSecs.reduce((a, s) => a + s.packed, 0) + tempSecs.reduce((a, s) => a + s.packed, 0);
  const total = hotLive + sidecars + tempLive + coldPacked + META_GB + DENSE_GB;
  const segs = [{
    label: "Hot live",
    gb: hotLive,
    color: "var(--c-red)"
  }, {
    label: "Abstract sidecars (v3)",
    gb: sidecars,
    color: "var(--c-amber)"
  }, ...(tempLive > 0 ? [{
    label: "Temp unpacked",
    gb: tempLive,
    color: "var(--c-violet)"
  }] : []), {
    label: "Cold packed (zstd-19)",
    gb: coldPacked,
    color: "var(--c-teal)"
  }, {
    label: "meta.sqlite v2",
    gb: META_GB,
    color: "var(--c-green)"
  }, {
    label: "Dense seed (b1)",
    gb: DENSE_GB,
    color: "var(--c-indigo)"
  }];
  const eraLabel = era => era === "recent" ? "≥ 2010" : "< 2010";
  const cols = "minmax(200px,1.4fr) 64px 64px 1fr 86px 86px 120px";
  return /*#__PURE__*/React.createElement("div", {
    className: "im-personas-grid",
    "data-screen-label": "Personas & Sections",
    style: {
      display: "grid",
      gridTemplateColumns: "292px 1fr",
      gap: 14,
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "Persona",
    pad: "12px 12px"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 4
    }
  }, IM_PERSONAS.map(p => {
    const active = p.id === personaId;
    return /*#__PURE__*/React.createElement("button", {
      key: p.id,
      onClick: () => setPersonaId(p.id),
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        padding: "8px 10px",
        borderRadius: 6,
        textAlign: "left",
        width: "100%",
        border: `1px solid ${active ? "var(--c-red)" : "var(--border-light)"}`,
        background: active ? "var(--c-red-soft)" : "var(--bg-panel)",
        transition: "border-color 0.15s, background 0.15s"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "block",
        fontSize: 12,
        fontWeight: active ? 600 : 500,
        color: "var(--text)",
        fontFamily: "var(--font-mono)",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      }
    }, p.id), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "block",
        fontSize: 11,
        color: "var(--text-muted)"
      }
    }, p.kind)), p.testbed ? /*#__PURE__*/React.createElement(Badge, {
      tone: "violet"
    }, "testbed") : active ? /*#__PURE__*/React.createElement(Badge, {
      tone: "hot"
    }, "active") : null);
  })), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)",
      lineHeight: 1.5,
      marginTop: 10,
      paddingTop: 10,
      borderTop: "1px dashed var(--border-light)"
    }
  }, "Subject personas default to the recent era; ", /*#__PURE__*/React.createElement(Mono, null, "*_historical"), " variants pin the archive. Year-filtered queries prune the contradicting era at query time (", /*#__PURE__*/React.createElement(Mono, null, "retriever._era_skip"), ").")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: `Disk footprint — ${persona.id}`,
    action: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: 6
      }
    }, /*#__PURE__*/React.createElement(GhostBtn, {
      small: true,
      title: "MCP tool"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "info",
      size: 12
    }), " get_index_status"), /*#__PURE__*/React.createElement(GhostBtn, {
      small: true,
      title: "MCP tool"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "refresh",
      size: 12
    }), " reload_index"))
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: 10,
      marginBottom: 10,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 26,
      fontWeight: 600,
      color: "var(--text)",
      fontVariantNumeric: "tabular-nums"
    }
  }, total.toFixed(1), " GB"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)"
    }
  }, "steady state on disk \xB7 all-hot all-live \u2248 192 GB (188.8 GB budget + dense seed, meta v2 measured)")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      height: 18,
      borderRadius: 5,
      overflow: "hidden",
      border: "1px solid var(--border-light)"
    }
  }, segs.map(s => s.gb > 0 && /*#__PURE__*/React.createElement("div", {
    key: s.label,
    title: `${s.label}: ${s.gb.toFixed(1)} GB`,
    style: {
      width: `${s.gb / total * 100}%`,
      background: s.color,
      minWidth: 2
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 14,
      flexWrap: "wrap",
      marginTop: 10
    }
  }, segs.map(s => s.gb > 0 && /*#__PURE__*/React.createElement("span", {
    key: s.label,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 6,
      fontSize: 11.5,
      color: "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 9,
      height: 9,
      borderRadius: 2.5,
      background: s.color,
      display: "inline-block"
    }
  }), s.label, " ", /*#__PURE__*/React.createElement("strong", {
    style: {
      fontVariantNumeric: "tabular-nums"
    }
  }, s.gb.toFixed(1), " GB"))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "Hot policy"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      marginBottom: 6
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "flame",
    size: 15,
    style: {
      color: "var(--c-red)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 500,
      color: "var(--text)"
    }
  }, "Live + local abstract sidecar")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      color: "var(--text-secondary)",
      lineHeight: 1.55
    }
  }, "Sidecar v3: script-bucketed 32 KB blocks, zstd-19 with per-script trained dicts (\u22480.35 KB/doc, 52.9 GB at 150M). Everyday queries stay fully offline at full rerank quality.")), /*#__PURE__*/React.createElement(Panel, {
    title: "Cold policy"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      marginBottom: 6
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "snow",
    size: 15,
    style: {
      color: "var(--c-teal)"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 500,
      color: "var(--text)"
    }
  }, "Packed (tar + zstd-19 LDM)")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      color: "var(--text-secondary)",
      lineHeight: 1.55
    }
  }, "No local abstracts \u2014 OpenAlex mget of ~100 docs (\u2248150 KB, +100\u2013300 ms) before rerank. Unpack is pure decompression at disk speed with SHA-256 parity. Never title-only rerank."))), /*#__PURE__*/React.createElement(Panel, {
    title: "Era sub-sections (10)",
    pad: "0",
    action: /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: "var(--text-muted)"
      }
    }, "era boundary: publication_year 2010")
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: cols,
      padding: "8px 16px",
      background: "var(--bg)",
      borderBottom: "1px solid var(--border)",
      gap: 8,
      marginTop: 0
    }
  }, ["Section", "Era", "Docs", "State", "Live", "Packed", "Actions"].map(h => /*#__PURE__*/React.createElement("span", {
    key: h,
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, h))), IM_SECTIONS.map((s, i) => {
    const st = stateOf(s);
    return /*#__PURE__*/React.createElement("div", {
      key: s.id,
      style: {
        display: "grid",
        gridTemplateColumns: cols,
        padding: "9px 16px",
        gap: 8,
        alignItems: "center",
        borderBottom: i < IM_SECTIONS.length - 1 ? "1px solid var(--border-light)" : "none",
        background: st === "hot" ? "oklch(98.5% 0.008 25)" : st === "unpacked" ? "oklch(98.5% 0.006 295)" : "transparent"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 7,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: st === "hot" ? "flame" : st === "unpacked" ? "box" : "snow",
      size: 13,
      style: {
        color: st === "hot" ? "var(--c-red)" : st === "unpacked" ? "var(--c-violet)" : "var(--c-teal)",
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement(Mono, {
      style: {
        fontSize: 11.5,
        color: "var(--text)",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      }
    }, s.id)), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11.5,
        color: "var(--text-muted)",
        fontVariantNumeric: "tabular-nums"
      }
    }, eraLabel(s.era)), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: "var(--text-secondary)",
        fontVariantNumeric: "tabular-nums"
      }
    }, s.docsM, "M"), /*#__PURE__*/React.createElement("span", null, st === "hot" && /*#__PURE__*/React.createElement(Badge, {
      tone: "hot"
    }, "hot \xB7 live + sidecar"), st === "cold" && /*#__PURE__*/React.createElement(Badge, {
      tone: "cold"
    }, "cold \xB7 packed ", s.ratio), st === "unpacked" && /*#__PURE__*/React.createElement(Badge, {
      tone: "violet"
    }, "live \xB7 temp unpack"), st === "unpacking" && /*#__PURE__*/React.createElement("span", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: 8
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        maxWidth: 110,
        display: "inline-block"
      }
    }, /*#__PURE__*/React.createElement(MiniBar, {
      value: unpacking[s.id],
      max: 1,
      color: "var(--c-violet)"
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: "var(--text-muted)",
        fontVariantNumeric: "tabular-nums"
      }
    }, Math.round(unpacking[s.id] * 100), "%"))), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: st === "cold" ? "var(--text-faint)" : "var(--text)",
        fontVariantNumeric: "tabular-nums"
      }
    }, s.live.toFixed(1), " GB"), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: "var(--text-secondary)",
        fontVariantNumeric: "tabular-nums"
      }
    }, s.packed.toFixed(1), " GB"), /*#__PURE__*/React.createElement("span", {
      style: {
        display: "flex",
        gap: 4
      }
    }, st === "cold" && /*#__PURE__*/React.createElement(GhostBtn, {
      small: true,
      onClick: () => startUnpack(s.id),
      title: "MCP: request_section_unpack"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "upload",
      size: 11
    }), " Unpack"), st === "unpacked" && /*#__PURE__*/React.createElement(GhostBtn, {
      small: true,
      onClick: () => repack(s.id),
      title: "Archive kept after unpack \u2014 repack just deletes the live dir"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "download",
      size: 11
    }), " Repack"), st === "unpacking" && /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: "var(--text-muted)"
      }
    }, "decompressing\u2026"), st === "hot" && /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: "var(--text-faint)"
      }
    }, "persona home")));
  })), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      lineHeight: 1.55,
      display: "flex",
      gap: 6,
      alignItems: "flex-start"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "info",
    size: 13,
    style: {
      marginTop: 1,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("span", null, "Unpack requests surface through the ", /*#__PURE__*/React.createElement(Mono, null, "request_section_unpack"), " MCP tool; archives are kept after unpack, so repacking an unwritten section just deletes the live directory. Peak disk = steady + largest cold section temporarily live."))));
};
const HIT_SERIES = [0, 2, 5, 9, 14, 21, 26, 33, 38, 44, 48, 51, 55, 57, 58, 60, 61, 61, 62, 63];
const WarmCacheScreen = () => {
  const [enabled, setEnabled] = React.useState(true);
  const dim = enabled ? 1 : 0.45;
  const ingestLog = [{
    t: "14:41:05",
    id: "W4391882041",
    leg: "SPLADE",
    action: "encoded",
    batch: "32/32 · 367 ms"
  }, {
    t: "14:41:05",
    id: "W4382011957",
    leg: "BM25F",
    action: "encoded",
    batch: "32/32 · 367 ms"
  }, {
    t: "14:41:04",
    id: "W2971912755",
    leg: "dense",
    action: "dedup skip",
    batch: "seed id"
  }, {
    t: "14:41:04",
    id: "W4377209114",
    leg: "SPLADE",
    action: "encoded",
    batch: "32/32 · 371 ms"
  }, {
    t: "14:38:52",
    id: "W3214559808",
    leg: "BM25F",
    action: "dedup skip",
    batch: "delta id"
  }, {
    t: "14:38:51",
    id: "W4365998120",
    leg: "dense",
    action: "encoded",
    batch: "27/32 · 344 ms"
  }, {
    t: "14:38:51",
    id: "W4221056733",
    leg: "SPLADE",
    action: "encoded",
    batch: "27/32 · 344 ms"
  }];
  const W = 520,
    H = 150,
    PAD = 28;
  const pts = HIT_SERIES.map((v, i) => {
    const x = PAD + i / (HIT_SERIES.length - 1) * (W - PAD - 10);
    const y = H - PAD - v / 80 * (H - PAD - 14);
    return [x, y];
  });
  const yOf = v => H - PAD - v / 80 * (H - PAD - 14);
  return /*#__PURE__*/React.createElement("div", {
    "data-screen-label": "Warm Cache"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      marginBottom: 14,
      gap: 12,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)",
      maxWidth: "70ch",
      lineHeight: 1.55
    }
  }, "Query-driven dense delta over the static seed \u2014 every hydrated local result is enqueued fire-and-forget, CPU-encoded in the background, and becomes retrievable for ", /*#__PURE__*/React.createElement("em", null, "future"), " queries. The cache converges to the user's active domain."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(Toggle, {
    on: enabled,
    setOn: setEnabled,
    label: "Dense warm cache"
  }), enabled ? /*#__PURE__*/React.createElement(Badge, {
    tone: "ok"
  }, "on \xB7 default") : /*#__PURE__*/React.createElement(Badge, {
    tone: "muted"
  }, "disabled"))), /*#__PURE__*/React.createElement("div", {
    style: {
      opacity: dim,
      transition: "opacity 0.25s",
      pointerEvents: enabled ? "auto" : "none"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(6, 1fr)",
      gap: 10,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(StatCard, {
    label: "Cached docs",
    value: "38,412",
    sub: "cap 500,000",
    icon: "layers",
    color: "var(--c-violet)"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "Delta on disk",
    value: "412 MB",
    sub: "dense/delta.sqlite",
    icon: "drive",
    color: "var(--c-teal)"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "RAM (b1 codes)",
    value: "19.6 MB",
    sub: "brute-force Hamming",
    icon: "cpu",
    color: "var(--c-indigo)"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "Hit rate \xB7 dense leg",
    value: "61%",
    sub: "last 100 queries",
    icon: "zap",
    color: "var(--c-amber)"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "Encode rate",
    value: "87 docs/s",
    sub: "CPU \xB7 batch 32",
    icon: "activity",
    color: "var(--c-green)"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "p95 search_rrf",
    value: "+0 ms",
    sub: "cache on vs off",
    icon: "check",
    color: "var(--c-green)"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(6, 1fr)",
      gap: 10,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(ResultCacheCard, null)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1.2fr 1fr",
      gap: 14,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "Cache-hit fraction vs queries served"
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${W} ${H}`,
    style: {
      width: "100%",
      height: "auto",
      display: "block"
    }
  }, [0, 25, 50, 75].map(v => /*#__PURE__*/React.createElement("g", {
    key: v
  }, /*#__PURE__*/React.createElement("line", {
    x1: PAD,
    x2: W - 10,
    y1: yOf(v),
    y2: yOf(v),
    stroke: "var(--border-light)",
    strokeWidth: "1",
    strokeDasharray: v === 75 ? "4 3" : "0"
  }), /*#__PURE__*/React.createElement("text", {
    x: PAD - 6,
    y: yOf(v) + 3.5,
    textAnchor: "end",
    fontSize: "9.5",
    fill: "var(--text-faint)",
    fontFamily: "var(--font-mono)"
  }, v, "%"))), /*#__PURE__*/React.createElement("text", {
    x: W - 12,
    y: yOf(75) - 5,
    textAnchor: "end",
    fontSize: "9.5",
    fill: "var(--text-muted)",
    fontFamily: "var(--font-ui)"
  }, "75% \u2014 Frieder et al. ceiling (temporal locality)"), /*#__PURE__*/React.createElement("polyline", {
    points: pts.map(p => p.join(",")).join(" "),
    fill: "none",
    stroke: "var(--c-violet)",
    strokeWidth: "2",
    strokeLinejoin: "round",
    strokeLinecap: "round"
  }), pts.filter((_, i) => i % 3 === 0).map((p, i) => /*#__PURE__*/React.createElement("circle", {
    key: i,
    cx: p[0],
    cy: p[1],
    r: "2.4",
    fill: "var(--c-violet)"
  })), /*#__PURE__*/React.createElement("text", {
    x: PAD,
    y: H - 8,
    fontSize: "9.5",
    fill: "var(--text-faint)",
    fontFamily: "var(--font-mono)"
  }, "0"), /*#__PURE__*/React.createElement("text", {
    x: W - 10,
    y: H - 8,
    textAnchor: "end",
    fontSize: "9.5",
    fill: "var(--text-faint)",
    fontFamily: "var(--font-mono)"
  }, "1,900 queries")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      marginTop: 6,
      lineHeight: 1.5
    }
  }, "In-domain payoff expected after ~10\u201350 queries (LOCALIZED \xA75 model). Background cost \u2248 0.6\u20131.7 s CPU per query, ~0.5 GB RAM per 1M cached docs.")), /*#__PURE__*/React.createElement(Panel, {
    title: "Two-tier delta \xB7 FreshDiskANN-style"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      border: "1px solid var(--border-light)",
      borderRadius: 6,
      padding: "9px 12px",
      background: "var(--bg)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      marginBottom: 2
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      fontWeight: 600,
      color: "var(--text)"
    }
  }, "Seed"), /*#__PURE__*/React.createElement(Badge, {
    tone: "muted"
  }, "immutable \xB7 mmap view")), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11.5,
      color: "var(--text-secondary)"
    }
  }, "Static ", /*#__PURE__*/React.createElement(Mono, null, "dense/"), " artifacts \u2014 b1.usearch + int8 memmap. Untouched by the cache.")), /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "center",
      color: "var(--text-faint)",
      lineHeight: 1
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "upload",
    size: 13
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      border: "1px solid var(--c-violet)",
      borderRadius: 6,
      padding: "9px 12px",
      background: "var(--c-violet-soft)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      marginBottom: 2
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      fontWeight: 600,
      color: "var(--text)"
    }
  }, "Delta"), /*#__PURE__*/React.createElement(Badge, {
    tone: "violet"
  }, "mutable \xB7 exact")), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11.5,
      color: "var(--text-secondary)"
    }
  }, "SQLite durability \u2192 in-RAM packed b1 codes, brute-force Hamming (popcount LUT) + int8 rescore. Sub-ms below ~200k docs; sidesteps HNSW insert-order degradation.")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      lineHeight: 1.5
    }
  }, "Scores are corpus-independent dot products \u2192 seed and delta merge exactly by score. Delta rows carry their own metadata, so warm docs hydrate even when absent from ", /*#__PURE__*/React.createElement(Mono, null, "meta.sqlite"), ".")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1.2fr 1fr",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "Ingest worker \xB7 fire-and-forget",
    pad: "0",
    action: /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 11,
        color: "var(--text-muted)"
      }
    }, "queue 18 / 2,048 \xB7 drop-newest on overflow")
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "70px 120px 70px 1fr 120px",
      padding: "8px 16px",
      background: "var(--bg)",
      borderBottom: "1px solid var(--border)",
      gap: 8
    }
  }, ["Time", "Doc", "Leg", "Action", "Batch"].map(h => /*#__PURE__*/React.createElement("span", {
    key: h,
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, h))), ingestLog.map((r, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "grid",
      gridTemplateColumns: "70px 120px 70px 1fr 120px",
      padding: "7px 16px",
      gap: 8,
      alignItems: "center",
      borderBottom: i < ingestLog.length - 1 ? "1px solid var(--border-light)" : "none"
    }
  }, /*#__PURE__*/React.createElement(Mono, {
    style: {
      fontSize: 11,
      color: "var(--text-faint)"
    }
  }, r.t), /*#__PURE__*/React.createElement(Mono, {
    style: {
      fontSize: 11.5,
      color: "var(--text)"
    }
  }, r.id), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11.5,
      color: "var(--text-secondary)"
    }
  }, r.leg), /*#__PURE__*/React.createElement("span", null, r.action === "encoded" ? /*#__PURE__*/React.createElement(Badge, {
    tone: "ok"
  }, "encoded") : /*#__PURE__*/React.createElement(Badge, {
    tone: "muted"
  }, "dedup skip")), /*#__PURE__*/React.createElement(Mono, {
    style: {
      fontSize: 11,
      color: "var(--text-muted)"
    }
  }, r.batch)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "Success metrics (v1)"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 7
    }
  }, [{
    ok: true,
    text: "Delta-vs-exact recall ≥ 0.97 — trivially exact (brute force)"
  }, {
    ok: true,
    text: "p95 search_rrf unchanged with cache on"
  }, {
    ok: null,
    text: "Cross-query recall growth on replayed query log — tracking"
  }, {
    ok: null,
    text: "Cache-hit fraction of dense leg vs query count — tracking"
  }].map((m, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      gap: 8,
      alignItems: "flex-start"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: m.ok ? "check" : "clock",
    size: 13,
    style: {
      color: m.ok ? "var(--c-green)" : "var(--c-amber)",
      marginTop: 2,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-secondary)",
      lineHeight: 1.45
    }
  }, m.text))))), /*#__PURE__*/React.createElement(Panel, {
    title: "Deferred to v2",
    action: /*#__PURE__*/React.createElement(GhostBtn, {
      small: true,
      disabled: true,
      title: "v2"
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "download",
      size: 11
    }), " merge_dense_delta")
  }, /*#__PURE__*/React.createElement("ul", {
    style: {
      listStyle: "none",
      display: "flex",
      flexDirection: "column",
      gap: 6
    }
  }, ["usearch mutable delta index above the brute-force threshold", "Fold delta into seed artifacts (bulk rebuild erases graph debt), truncate delta", "OpenAlex live-API ingest hook — v1 captures the local legs only", "ONNX-int8 export of the v5 encoder (2–3× CPU encode)"].map((t, i) => /*#__PURE__*/React.createElement("li", {
    key: i,
    style: {
      display: "flex",
      gap: 8,
      alignItems: "flex-start",
      fontSize: 12,
      color: "var(--text-secondary)",
      lineHeight: 1.45
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 4,
      height: 4,
      borderRadius: 2,
      background: "var(--text-faint)",
      marginTop: 7,
      flexShrink: 0
    }
  }), t))))))));
};
const StorageScreen = () => {
  const levers = [{
    comp: "BMP SPLADE shards",
    before: 167.6,
    after: 76.7,
    lever: "bsize 256 + clustered (section, top-SPLADE-term) insertion",
    note: "−54.2% · recall@50 0.967 vs 0.966 · −61% latency",
    status: {
      tone: "ok",
      label: "shipped af09836"
    }
  }, {
    comp: "Abstract sidecar",
    before: 64.7,
    after: 52.9,
    lever: "clustered 32 KB blocks + per-(script) zstd-19 dicts (3.42×)",
    note: "bit-exact · 100-doc rerank fetch ≪ 300 ms budget",
    status: {
      tone: "ok",
      label: "shipped d978ba3"
    }
  }, {
    comp: "meta.sqlite",
    before: 24.1,
    after: 10.2,
    lever: "v2: W-id INTEGER PK + TEXT overflow + dict-zstd titles/DOIs",
    note: "measured ~10 GB at 150M — beats the 14.4 GB lever estimate",
    status: {
      tone: "ok",
      label: "shipped 9a6d195"
    }
  }, {
    comp: "tantivy BM25F",
    before: 44.5,
    after: 44.8,
    lever: "clustered ordering tested",
    note: "+0.7% — null result; tantivy already delta/bit-packs postings",
    status: {
      tone: "muted",
      label: "not adopted"
    }
  }];
  const bmpMatrix = [{
    v: "b32 corpus (paper config)",
    b: "1404.8",
    d: "—",
    ms: "27.2",
    r: "0.966",
    adopted: false
  }, {
    v: "b32 clustered",
    b: "1160.1",
    d: "−17.4%",
    ms: "13.3",
    r: "0.960",
    adopted: false
  }, {
    v: "b64 clustered",
    b: "961.9",
    d: "−31.5%",
    ms: "14.1",
    r: "0.962",
    adopted: false
  }, {
    v: "b128 clustered",
    b: "789.5",
    d: "−43.8%",
    ms: "13.6",
    r: "0.966",
    adopted: false
  }, {
    v: "b256 clustered",
    b: "642.9",
    d: "−54.2%",
    ms: "10.7",
    r: "0.967",
    adopted: true
  }];
  const mainline = [{
    label: "Original live index",
    gb: 274,
    color: "var(--text-faint)"
  }, {
    label: "Lossless config (combined2)",
    gb: 141.3,
    color: "var(--c-teal)"
  }, {
    label: "+ abstracts → sidecar",
    gb: 112,
    color: "var(--c-green)",
    approx: true
  }, {
    label: "+ BP doc-ID reordering",
    gb: 108,
    color: "var(--c-green)",
    approx: true,
    est: true
  }];
  const maxBefore = 170;
  return /*#__PURE__*/React.createElement("div", {
    "data-screen-label": "Storage Budget"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: 10,
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement(StatCard, {
    label: "As built \xB7 all hot",
    value: "300.9 GB",
    sub: "150.4M docs, all sections live",
    icon: "drive",
    color: "var(--text-muted)"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "All levers applied",
    value: "188.8 GB",
    sub: "\u2212112.1 GB \xB7 \u221237.3% \xB7 all lossless",
    icon: "download",
    color: "var(--c-green)"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "Persona steady state",
    value: "\u224895 GB",
    sub: "political_science \xB7 hot live + cold packed",
    icon: "flame",
    color: "var(--c-red)"
  }), /*#__PURE__*/React.createElement(StatCard, {
    label: "15M laptop tier",
    value: "\u224819 GB",
    sub: "all-live \xB7 ~10 GB persona steady",
    icon: "zap",
    color: "var(--c-violet)"
  })), /*#__PURE__*/React.createElement(Panel, {
    title: "Measured levers \u2014 thin-client DB @150M",
    pad: "0",
    style: {
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "150px 1fr 280px 110px 130px",
      padding: "8px 16px",
      background: "var(--bg)",
      borderBottom: "1px solid var(--border)",
      gap: 10
    }
  }, ["Component", "As built → after", "Lever", "Sizes", "Status"].map(h => /*#__PURE__*/React.createElement("span", {
    key: h,
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, h))), levers.map((l, i) => /*#__PURE__*/React.createElement("div", {
    key: l.comp,
    style: {
      display: "grid",
      gridTemplateColumns: "150px 1fr 280px 110px 130px",
      padding: "11px 16px",
      gap: 10,
      alignItems: "center",
      borderBottom: i < levers.length - 1 ? "1px solid var(--border-light)" : "none"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      fontWeight: 500,
      color: "var(--text)"
    }
  }, l.comp), /*#__PURE__*/React.createElement("span", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 4
    }
  }, /*#__PURE__*/React.createElement(MiniBar, {
    value: l.before,
    max: maxBefore,
    color: "var(--border)",
    height: 5
  }), /*#__PURE__*/React.createElement(MiniBar, {
    value: l.after,
    max: maxBefore,
    color: l.after < l.before ? "var(--c-green)" : "var(--c-amber)",
    height: 5
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11.5,
      color: "var(--text-secondary)",
      lineHeight: 1.4
    }
  }, l.lever, /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)"
    }
  }, l.note)), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontVariantNumeric: "tabular-nums",
      color: "var(--text-secondary)"
    }
  }, l.before, " \u2192 ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: l.after < l.before ? "oklch(40% 0.11 145)" : "var(--text)"
    }
  }, l.after, " GB")), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement(Badge, {
    tone: l.status.tone
  }, l.status.label)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      padding: "10px 16px",
      borderTop: "1px solid var(--border)",
      background: "var(--bg)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontWeight: 600,
      color: "var(--text)"
    }
  }, "Total (all live, all hot)"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      fontVariantNumeric: "tabular-nums",
      color: "var(--text)"
    }
  }, "300.9 \u2192 ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "oklch(40% 0.11 145)"
    }
  }, "188.8 GB"), " ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)"
    }
  }, "(\u221237.3%, all lossless)")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1.2fr 1fr",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "BMP matrix \u2014 100k real docs, production SPLADE, alpha 0.8",
    pad: "0"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1.5fr 80px 80px 70px 100px",
      padding: "8px 16px",
      background: "var(--bg)",
      borderBottom: "1px solid var(--border)",
      gap: 8
    }
  }, ["Variant", "B/doc", "Δ size", "ms/q", "recall@50"].map(h => /*#__PURE__*/React.createElement("span", {
    key: h,
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, h))), bmpMatrix.map((r, i) => /*#__PURE__*/React.createElement("div", {
    key: r.v,
    style: {
      display: "grid",
      gridTemplateColumns: "1.5fr 80px 80px 70px 100px",
      padding: "8px 16px",
      gap: 8,
      alignItems: "center",
      borderBottom: i < bmpMatrix.length - 1 ? "1px solid var(--border-light)" : "none",
      background: r.adopted ? "oklch(98% 0.008 145)" : "transparent"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text)",
      fontWeight: r.adopted ? 600 : 400,
      display: "flex",
      alignItems: "center",
      gap: 7
    }
  }, r.v, r.adopted && /*#__PURE__*/React.createElement(Badge, {
    tone: "ok"
  }, "adopted")), /*#__PURE__*/React.createElement(Mono, {
    style: {
      fontSize: 11.5,
      color: "var(--text-secondary)"
    }
  }, r.b), /*#__PURE__*/React.createElement(Mono, {
    style: {
      fontSize: 11.5,
      color: r.d === "—" ? "var(--text-faint)" : "oklch(40% 0.11 145)"
    }
  }, r.d), /*#__PURE__*/React.createElement(Mono, {
    style: {
      fontSize: 11.5,
      color: "var(--text-secondary)"
    }
  }, r.ms), /*#__PURE__*/React.createElement(Mono, {
    style: {
      fontSize: 11.5,
      color: "var(--text-secondary)"
    }
  }, r.r))), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      lineHeight: 1.5,
      padding: "10px 16px",
      borderTop: "1px dashed var(--border-light)"
    }
  }, "Quantization scale 70 (saturation-free for SPLADE log1p \u2264 3.64); tail shards < 5,000 docs absorbed into the previous shard; per-shard ", /*#__PURE__*/React.createElement(Mono, null, "vocab.zst"), " sidecars guard all-terms-absent panics.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "Same tech on the mainline Lucene DB (hypothetical)"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 9
    }
  }, mainline.map(m => /*#__PURE__*/React.createElement("div", {
    key: m.label
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      marginBottom: 3
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-secondary)"
    }
  }, m.label, m.est && /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-faint)"
    }
  }, " \xB7 est.")), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontVariantNumeric: "tabular-nums",
      color: "var(--text)"
    }
  }, m.approx ? "≈" : "", m.gb, " GB")), /*#__PURE__*/React.createElement(MiniBar, {
    value: m.gb,
    max: 274,
    color: m.color,
    height: 7
  })))), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      lineHeight: 1.5,
      marginTop: 10
    }
  }, "274 \u2192 ~112 GB (\u221259%), fully lossless. The thin-client pays ~77 GB more disk than optimized mainline at 150M for BMP's block-max speed structures \u2014 in exchange for the no-JVM laptop properties.")), /*#__PURE__*/React.createElement(Panel, {
    title: "Rejected lossy options (for the record)"
  }, /*#__PURE__*/React.createElement("ul", {
    style: {
      listStyle: "none",
      display: "flex",
      flexDirection: "column",
      gap: 6
    }
  }, [["truncate-128tok", "4.34× but cosine 0.955 — fails the 0.98 embedding-cosine gate"], ["stopword-drop", "2.25× but cosine 0.968 — fails the same gate"], ["SLM rank-decode (gpt2)", "misses the 300 ms rerank budget by 1,411× and same-machine bit-exactness"]].map(([k, v]) => /*#__PURE__*/React.createElement("li", {
    key: k,
    style: {
      display: "flex",
      gap: 8,
      alignItems: "flex-start",
      fontSize: 12,
      lineHeight: 1.45
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "warning",
    size: 12,
    style: {
      color: "var(--c-amber)",
      marginTop: 2.5,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(Mono, {
    style: {
      color: "var(--text)"
    }
  }, k), " \u2014 ", v))))))));
};
const TABS = [{
  id: "personas",
  label: "Personas & Sections"
}, {
  id: "warmcache",
  label: "Warm Cache"
}, {
  id: "storage",
  label: "Storage Budget"
}];
const App = () => {
  const [tab, setTab] = React.useState(() => localStorage.getItem("im-tab") || "personas");
  const [live, setLive] = React.useState(null);
  const pick = t => {
    setTab(t);
    localStorage.setItem("im-tab", t);
  };
  React.useEffect(() => {
    const onMsg = e => {
      if (e.data && typeof e.data.suiteDemo === "boolean") setLive(!e.data.suiteDemo);
    };
    window.addEventListener("message", onMsg);
    if (window.parent === window && window.SFUApi) {
      window.SFUApi.health().then(r => setLive(r.source === "live")).catch(() => {});
    }
    return () => window.removeEventListener("message", onMsg);
  }, []);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      height: "100%"
    }
  }, /*#__PURE__*/React.createElement(SuiteSidebar, {
    app: "index",
    active: "index"
  }), /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      minWidth: 0,
      overflow: "auto",
      padding: "20px 24px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 12,
      marginBottom: 16,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 6,
      background: "var(--c-red)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "server",
    size: 14,
    style: {
      color: "white"
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 17,
      fontWeight: 500,
      color: "var(--text)",
      lineHeight: 1.2
    }
  }, "Index Manager"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)"
    }
  }, "Thin-client testbed \xB7 150.4M docs \xB7 tantivy + BMP + usearch"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 6,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    tone: live === false ? "warn" : "ok"
  }, live === false ? "backend: demo data" : "backend: thinclient"), /*#__PURE__*/React.createElement(Badge, {
    tone: "muted"
  }, "SPLADE fallback armed"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 0,
      borderBottom: "1px solid var(--border-light)",
      marginBottom: 20
    }
  }, TABS.map(t => /*#__PURE__*/React.createElement("button", {
    key: t.id,
    onClick: () => pick(t.id),
    style: {
      padding: "8px 16px",
      border: "none",
      background: "transparent",
      fontSize: 13,
      fontWeight: tab === t.id ? 500 : 400,
      color: tab === t.id ? "var(--c-red)" : "var(--text-secondary)",
      borderBottom: `2px solid ${tab === t.id ? "var(--c-red)" : "transparent"}`,
      transition: "color 0.15s"
    }
  }, t.label))), tab === "personas" && /*#__PURE__*/React.createElement(PersonasScreen, null), tab === "warmcache" && /*#__PURE__*/React.createElement(WarmCacheScreen, null), tab === "storage" && /*#__PURE__*/React.createElement(StorageScreen, null)), /*#__PURE__*/React.createElement("style", null, `
        @media (max-width: 1400px) {
          .im-personas-grid { grid-template-columns: 1fr !important; }
        }
        main { scrollbar-gutter: stable; }
      `));
};
ReactDOM.createRoot(document.getElementById("root")).render(/*#__PURE__*/React.createElement(App, null));