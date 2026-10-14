/* AUTO-GENERATED from source/search.jsx by scripts/build_web.mjs — do not edit. */
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
const Icon = NIcon;
const AccessBadge = ({
  access,
  compact = false
}) => {
  const configs = {
    open_access: {
      bg: "var(--accent-teal-light)",
      color: "var(--accent-teal)",
      label: compact ? "OA" : "Open Access"
    },
    unpaywall_oa: {
      bg: "oklch(93% 0.05 145)",
      color: "oklch(42% 0.14 145)",
      label: compact ? "Free Copy" : "Free via Unpaywall"
    },
    sfu_proxy: {
      bg: "var(--accent-red-light)",
      color: "var(--accent-red)",
      label: compact ? "Duck" : "Duck Library"
    },
    sfu_direct: {
      bg: "var(--accent-red-light)",
      color: "var(--accent-red)",
      label: compact ? "Duck" : "Duck Library"
    },
    doi_fallback: {
      bg: "oklch(93% 0.01 250)",
      color: "var(--text-muted)",
      label: compact ? "DOI" : "Check Access"
    }
  };
  const cfg = configs[access?.type] || configs.doi_fallback;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 4,
      padding: compact ? "2px 6px" : "3px 8px",
      borderRadius: 4,
      background: cfg.bg,
      color: cfg.color,
      fontSize: compact ? 11 : 12,
      fontWeight: 500,
      letterSpacing: "0.02em",
      whiteSpace: "nowrap"
    }
  }, cfg.label);
};
const CitationCount = ({
  n
}) => /*#__PURE__*/React.createElement("span", {
  style: {
    color: "var(--text-muted)",
    fontSize: 12,
    display: "inline-flex",
    alignItems: "center",
    gap: 3
  }
}, /*#__PURE__*/React.createElement(Icon, {
  name: "link",
  size: 11
}), n.toLocaleString(), " citations");
const SearchBar = ({
  query,
  setQuery,
  onSearch,
  loading,
  filters,
  setFilters,
  compact = false
}) => {
  const [focused, setFocused] = React.useState(false);
  const specCtrl = React.useRef(null);
  if (specCtrl.current === null && typeof window !== "undefined" && window.SFUApi && typeof window.SFUApi.createSpeculationController === "function") {
    specCtrl.current = window.SFUApi.createSpeculationController(window.SFUApi.speculate.bind(window.SFUApi), filters);
  }
  const handleKey = e => {
    if (e.key === "Enter") {
      if (specCtrl.current) specCtrl.current.cancel();
      onSearch();
    }
  };
  const handleChange = val => {
    setQuery(val);
    if (specCtrl.current) specCtrl.current.onType(val);
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: "100%"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0,
      display: "flex",
      alignItems: "center",
      gap: 0,
      background: "var(--bg-panel)",
      border: `1.5px solid ${focused ? "var(--accent-red)" : "var(--border)"}`,
      borderRadius: compact ? 8 : 10,
      padding: compact ? "0 12px" : "0 14px",
      boxShadow: focused ? "0 0 0 3px var(--accent-red-light)" : "none",
      transition: "border-color 0.15s, box-shadow 0.15s"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "search",
    size: 16,
    style: {
      color: focused ? "var(--accent-red)" : "var(--text-muted)",
      flexShrink: 0,
      transition: "color 0.15s"
    }
  }), /*#__PURE__*/React.createElement("input", {
    value: query,
    onChange: e => handleChange(e.target.value),
    onKeyDown: handleKey,
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
    placeholder: "Search the library \u2014 try natural language\u2026",
    style: {
      flex: 1,
      minWidth: 0,
      width: "100%",
      border: "none",
      background: "transparent",
      outline: "none",
      padding: compact ? "9px 10px" : "12px 10px",
      fontSize: compact ? 13 : 15,
      color: "var(--text)",
      fontFamily: "var(--font-ui)"
    }
  }), query && /*#__PURE__*/React.createElement("button", {
    onClick: () => handleChange(""),
    style: {
      border: "none",
      background: "transparent",
      padding: 4,
      color: "var(--text-muted)",
      cursor: "pointer",
      borderRadius: 4,
      display: "flex",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "close",
    size: 14
  }))), /*#__PURE__*/React.createElement("button", {
    onClick: onSearch,
    disabled: loading,
    style: {
      padding: compact ? "9px 16px" : "12px 20px",
      background: "var(--accent-red)",
      color: "white",
      border: "none",
      borderRadius: compact ? 8 : 10,
      fontSize: 13,
      fontWeight: 500,
      cursor: loading ? "not-allowed" : "pointer",
      opacity: loading ? 0.7 : 1,
      display: "flex",
      alignItems: "center",
      gap: 6,
      whiteSpace: "nowrap",
      flexShrink: 0
    }
  }, loading ? /*#__PURE__*/React.createElement("div", {
    style: {
      width: 14,
      height: 14,
      border: "2px solid rgba(255,255,255,0.4)",
      borderTopColor: "white",
      borderRadius: "50%",
      animation: "spin 0.7s linear infinite"
    }
  }) : /*#__PURE__*/React.createElement(Icon, {
    name: "search",
    size: 14
  }), compact ? "Search" : "Search")), !compact && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginTop: 8,
      flexWrap: "wrap"
    }
  }, [{
    key: "type",
    label: "Type",
    options: ["All", "Article", "Book", "Thesis", "Conference"]
  }, {
    key: "date",
    label: "Date",
    options: ["Any time", "Last year", "Last 5 years", "Last 10 years"]
  }, {
    key: "access",
    label: "Access",
    options: ["Any", "Open Access", "Duck Library", "Unpaywall"]
  }, {
    key: "sort",
    label: "Sort",
    options: ["Relevance", "Most Recent", "Most Cited", "Title A–Z"]
  }].map(f => /*#__PURE__*/React.createElement("div", {
    key: f.key,
    style: {
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("select", {
    value: filters[f.key] || f.options[0],
    onChange: e => setFilters({
      ...filters,
      [f.key]: e.target.value
    }),
    style: {
      appearance: "none",
      background: "var(--bg-panel)",
      border: "1px solid var(--border)",
      borderRadius: 6,
      padding: "5px 24px 5px 10px",
      fontSize: 12,
      color: "var(--text)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)"
    }
  }, f.options.map(o => /*#__PURE__*/React.createElement("option", {
    key: o
  }, o))), /*#__PURE__*/React.createElement(Icon, {
    name: "chevronDown",
    size: 12,
    style: {
      position: "absolute",
      right: 6,
      top: "50%",
      transform: "translateY(-50%)",
      color: "var(--text-muted)",
      pointerEvents: "none"
    }
  })))));
};
const SOURCE_COVERS = {
  "Molecular Informatics": {
    tone: "oklch(38% 0.12 265)",
    fg: "oklch(96% 0.02 80)",
    pub: "Wiley",
    motif: "grid"
  },
  "Drug Discovery Today": {
    tone: "oklch(34% 0.10 25)",
    fg: "oklch(96% 0.02 80)",
    pub: "Elsevier",
    motif: "bar"
  },
  "Nature Machine Intelligence": {
    tone: "oklch(22% 0.018 250)",
    fg: "oklch(96% 0.02 80)",
    pub: "Springer Nature",
    motif: "rule"
  },
  "Journal of Chemical Information and Modeling": {
    tone: "oklch(40% 0.08 145)",
    fg: "oklch(96% 0.02 80)",
    pub: "ACS",
    motif: "diag"
  },
  "Science": {
    tone: "oklch(34% 0.13 30)",
    fg: "oklch(96% 0.02 80)",
    pub: "AAAS",
    motif: "rule"
  },
  "ACS Central Science": {
    tone: "oklch(45% 0.13 200)",
    fg: "oklch(96% 0.02 80)",
    pub: "ACS",
    motif: "grid"
  },
  "Nature Communications": {
    tone: "oklch(28% 0.06 60)",
    fg: "oklch(96% 0.02 80)",
    pub: "Springer Nature",
    motif: "bar"
  }
};
const SourceThumbnail = ({
  result
}) => {
  const cfg = SOURCE_COVERS[result.source] || {
    tone: "oklch(36% 0.04 250)",
    fg: "oklch(96% 0.02 80)",
    pub: "—",
    motif: "rule"
  };
  const titleAbbr = result.source.replace(/Journal of /i, "J. ").replace(/and /gi, "& ");
  return /*#__PURE__*/React.createElement("div", {
    "aria-hidden": "true",
    style: {
      width: 64,
      height: 86,
      flexShrink: 0,
      borderRadius: 3,
      background: cfg.tone,
      color: cfg.fg,
      boxShadow: "0 1px 2px oklch(0% 0 0 / 0.20), 0 4px 10px oklch(0% 0 0 / 0.10), inset -1px 0 0 oklch(0% 0 0 / 0.15), inset 1px 0 0 oklch(100% 0 0 / 0.06)",
      position: "relative",
      overflow: "hidden",
      fontFamily: "var(--font-serif)",
      display: "flex",
      flexDirection: "column",
      padding: "6px 5px 5px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      top: 0,
      bottom: 0,
      width: 3,
      background: "linear-gradient(to right, oklch(0% 0 0 / 0.18), transparent)"
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 5.5,
      fontFamily: "var(--font-ui)",
      letterSpacing: "0.12em",
      textTransform: "uppercase",
      opacity: 0.7,
      fontWeight: 500
    }
  }, cfg.pub), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: titleAbbr.length > 18 ? 8 : 9.5,
      fontWeight: 500,
      lineHeight: 1.05,
      marginTop: 3,
      textWrap: "balance"
    }
  }, titleAbbr), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      marginTop: 4,
      position: "relative",
      opacity: 0.55
    }
  }, cfg.motif === "grid" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr 1fr",
      gap: 1.5,
      height: "100%"
    }
  }, Array.from({
    length: 9
  }).map((_, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      background: cfg.fg,
      opacity: 0.10 + i % 3 * 0.08,
      borderRadius: 1
    }
  }))), cfg.motif === "bar" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-end",
      gap: 1.5,
      height: "100%"
    }
  }, [0.4, 0.7, 0.55, 0.85, 0.3, 0.6, 0.45].map((h, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      flex: 1,
      height: `${h * 100}%`,
      background: cfg.fg,
      opacity: 0.45,
      borderRadius: 0.5
    }
  }))), cfg.motif === "rule" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 2,
      marginTop: 2
    }
  }, [100, 80, 60, 90, 70].map((w, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      height: 1,
      width: `${w}%`,
      background: cfg.fg,
      opacity: 0.35
    }
  }))), cfg.motif === "diag" && /*#__PURE__*/React.createElement("div", {
    style: {
      height: "100%",
      background: `repeating-linear-gradient(45deg, transparent 0 4px, ${cfg.fg.replace(")", " / 0.18)")} 4px 5px)`
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "flex-end",
      fontSize: 6,
      fontFamily: "var(--font-ui)",
      letterSpacing: "0.06em",
      opacity: 0.85,
      fontWeight: 500,
      marginTop: 3
    }
  }, /*#__PURE__*/React.createElement("span", null, "VOL ", result.volume), /*#__PURE__*/React.createElement("span", null, result.year)));
};
window.__sfuResults = window.__sfuResults || {};
const engage = (fn, ...args) => {
  try {
    const e = window.SFUApi && window.SFUApi.engagement;
    if (e && typeof e[fn] === "function") return e[fn](...args);
  } catch (err) {}
  return false;
};
const ResultCard = ({
  result,
  index,
  onClick,
  saved,
  onSave,
  preliminary,
  onHover
}) => {
  const [copied, setCopied] = React.useState(null);
  React.useEffect(() => {
    window.__sfuResults[result.id] = result;
  }, [result]);
  const handleCopy = (format, e) => {
    e.stopPropagation();
    engage("action", result, "citation");
    const citations = {
      APA: `${result.authors.join(", ")} (${result.year}). ${result.title}. *${result.source}*, *${result.volume}*(${result.issue}). https://doi.org/${result.doi}`,
      MLA: `${result.authors[0]} et al. "${result.title}." *${result.source}* ${result.volume}.${result.issue} (${result.year}).`,
      BibTeX: `@article{${result.id},\n  title={${result.title}},\n  author={${result.authors.join(" and ")}},\n  journal={${result.source}},\n  year={${result.year}}\n}`
    };
    setCopied(format);
    setTimeout(() => setCopied(null), 2000);
  };
  return /*#__PURE__*/React.createElement("div", {
    onClick: () => onClick(result),
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 10,
      padding: "16px 18px",
      marginBottom: 8,
      cursor: "pointer",
      transition: "border-color 0.15s, box-shadow 0.15s"
    },
    "data-result-id": result.id,
    onMouseEnter: e => {
      e.currentTarget.style.borderColor = "var(--border)";
      e.currentTarget.style.boxShadow = "var(--shadow-sm)";
      if (onHover) onHover(result.id);
    },
    onMouseLeave: e => {
      e.currentTarget.style.borderColor = "var(--border-light)";
      e.currentTarget.style.boxShadow = "none";
      if (onHover) onHover(null);
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 22,
      flexShrink: 0,
      color: "var(--text-muted)",
      fontSize: 12,
      paddingTop: 3,
      textAlign: "right"
    }
  }, index, "."), /*#__PURE__*/React.createElement(SourceThumbnail, {
    result: result
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      gap: 12,
      marginBottom: 4
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 15,
      fontWeight: 500,
      color: "var(--text)",
      lineHeight: 1.4,
      margin: 0,
      flex: 1,
      textWrap: "pretty"
    }
  }, preliminary && /*#__PURE__*/React.createElement("span", {
    "data-testid": "sfu-preliminary-badge",
    style: {
      fontFamily: "var(--font-ui)",
      fontSize: 10.5,
      fontWeight: 600,
      letterSpacing: 0.2,
      textTransform: "uppercase",
      padding: "1px 6px",
      marginRight: 7,
      borderRadius: 4,
      background: "var(--accent-amber-light)",
      color: "var(--text-secondary)",
      border: "1px solid var(--border)",
      verticalAlign: "2px"
    }
  }, "Preliminary"), result.title), /*#__PURE__*/React.createElement("button", {
    onClick: e => {
      e.stopPropagation();
      if (!saved) engage("action", result, "save");
      onSave(result.id);
    },
    "data-testid": "sfu-card-save",
    style: {
      border: "none",
      background: "transparent",
      color: saved ? "var(--accent-red)" : "var(--text-muted)",
      cursor: "pointer",
      padding: 4,
      flexShrink: 0,
      display: "flex",
      borderRadius: 4,
      transition: "color 0.15s"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "bookmark",
    size: 14,
    style: {
      fill: saved ? "var(--accent-red)" : "none"
    }
  }))), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      color: "var(--text-secondary)",
      marginBottom: 6,
      lineHeight: 1.4
    }
  }, result.authors.slice(0, 3).join(", "), result.authors.length > 3 ? " et al." : "", " \xB7 ", result.source, " \xB7 ", result.year, result.volume ? ` · Vol. ${result.volume}` : ""), result.tldr && /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)",
      marginBottom: 8,
      lineHeight: 1.55,
      display: "-webkit-box",
      WebkitLineClamp: 2,
      WebkitBoxOrient: "vertical",
      overflow: "hidden"
    }
  }, result.tldr), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 8,
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement(AccessBadge, {
    access: result.access,
    compact: true
  }), /*#__PURE__*/React.createElement(CitationCount, {
    n: result.cited_by
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      gap: 4,
      flexShrink: 0
    },
    onClick: e => e.stopPropagation()
  }, ["APA", "MLA", "BibTeX"].map(fmt => /*#__PURE__*/React.createElement("button", {
    key: fmt,
    onClick: e => handleCopy(fmt, e),
    style: {
      fontSize: 11,
      padding: "3px 7px",
      border: "1px solid var(--border)",
      borderRadius: 4,
      background: copied === fmt ? "var(--accent-teal-light)" : "var(--bg)",
      color: copied === fmt ? "var(--accent-teal)" : "var(--text-secondary)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      gap: 3,
      transition: "all 0.15s"
    }
  }, copied === fmt ? /*#__PURE__*/React.createElement(Icon, {
    name: "check",
    size: 10
  }) : /*#__PURE__*/React.createElement(Icon, {
    name: "copy",
    size: 10
  }), fmt)), /*#__PURE__*/React.createElement("button", {
    onClick: e => e.stopPropagation(),
    style: {
      fontSize: 11,
      padding: "3px 7px",
      border: "1px solid var(--border)",
      borderRadius: 4,
      background: "var(--bg)",
      color: "var(--text-secondary)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      gap: 3
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "zotero",
    size: 10
  }), "Zotero"), /*#__PURE__*/React.createElement("a", {
    href: result.doi ? `https://doi.org/${result.doi}` : "#",
    target: "_blank",
    rel: "noopener noreferrer",
    onClick: e => {
      e.stopPropagation();
      engage("action", result, "pdf");
    },
    "data-testid": "sfu-card-access",
    style: {
      fontSize: 11,
      padding: "3px 7px",
      border: "1px solid var(--border)",
      borderRadius: 4,
      background: "var(--bg)",
      color: "var(--text-secondary)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      gap: 3,
      textDecoration: "none"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "externalLink",
    size: 10
  }), result.access?.type === "open_access" ? "PDF" : "Access"))))));
};
const SkeletonResultCard = ({
  index
}) => /*#__PURE__*/React.createElement("div", {
  style: {
    background: "var(--bg-panel)",
    border: "1px solid var(--border-light)",
    borderRadius: 10,
    padding: "16px 18px",
    marginBottom: 8,
    height: 110
  },
  "data-skeleton-card": true
}, /*#__PURE__*/React.createElement("div", {
  style: {
    display: "flex",
    gap: 14
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    width: 22,
    flexShrink: 0,
    paddingTop: 3
  }
}), /*#__PURE__*/React.createElement("div", {
  style: {
    width: 64,
    height: 86,
    flexShrink: 0,
    borderRadius: 3,
    background: "var(--border)",
    animation: "sfu-skimmer 1.4s ease infinite"
  }
}), /*#__PURE__*/React.createElement("div", {
  style: {
    flex: 1,
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: 7,
    paddingTop: 2
  }
}, /*#__PURE__*/React.createElement("div", {
  style: {
    height: 14,
    background: "var(--border)",
    borderRadius: 3,
    width: "75%",
    animation: "sfu-skimmer 1.4s ease infinite"
  }
}), /*#__PURE__*/React.createElement("div", {
  style: {
    height: 10,
    background: "var(--border)",
    borderRadius: 3,
    width: "50%",
    animation: "sfu-skimmer 1.4s ease infinite"
  }
}), /*#__PURE__*/React.createElement("div", {
  style: {
    height: 10,
    background: "var(--border)",
    borderRadius: 3,
    width: "90%",
    animation: "sfu-skimmer 1.4s ease infinite"
  }
}))));
const FiltersExpander = ({
  filters,
  setFilters,
  alwaysOpen
}) => {
  const [open, setOpen] = React.useState(!!alwaysOpen);
  React.useEffect(() => {
    setOpen(!!alwaysOpen);
  }, [alwaysOpen]);
  const filterDefs = [{
    key: "type",
    label: "Type",
    options: ["All", "Article", "Book", "Thesis", "Conference"]
  }, {
    key: "date",
    label: "Date",
    options: ["Any time", "Last year", "Last 5 years", "Last 10 years"]
  }, {
    key: "access",
    label: "Access",
    options: ["Any", "Open Access", "Duck Library", "Unpaywall"]
  }, {
    key: "sort",
    label: "Sort",
    options: ["Relevance", "Most Recent", "Most Cited", "Title A–Z"]
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setOpen(o => !o),
    "aria-expanded": open,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 6,
      padding: "4px 2px",
      border: "none",
      background: "transparent",
      color: "var(--text-secondary)",
      fontSize: 12,
      fontWeight: 500,
      cursor: "pointer",
      fontFamily: "var(--font-ui)"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "filter",
    size: 13
  }), open ? "Hide filters" : "Filters", /*#__PURE__*/React.createElement(Icon, {
    name: open ? "chevronDown" : "chevronRight",
    size: 12
  })), open && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      marginTop: 8,
      flexWrap: "wrap"
    }
  }, filterDefs.map(f => /*#__PURE__*/React.createElement("div", {
    key: f.key,
    style: {
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("select", {
    value: filters[f.key] || f.options[0],
    onChange: e => setFilters({
      ...filters,
      [f.key]: e.target.value
    }),
    style: {
      appearance: "none",
      background: "var(--bg-panel)",
      border: "1px solid var(--border)",
      borderRadius: 6,
      padding: "5px 24px 5px 10px",
      fontSize: 12,
      color: "var(--text)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)"
    }
  }, f.options.map(o => /*#__PURE__*/React.createElement("option", {
    key: o
  }, o))), /*#__PURE__*/React.createElement(Icon, {
    name: "chevronDown",
    size: 12,
    style: {
      position: "absolute",
      right: 6,
      top: "50%",
      transform: "translateY(-50%)",
      color: "var(--text-muted)",
      pointerEvents: "none"
    }
  })))));
};
const ResultDetail = ({
  result,
  onClose,
  saved,
  onSave
}) => {
  const [activeTab, setActiveTab] = React.useState("abstract");
  const [copied, setCopied] = React.useState(null);
  if (!result) return null;
  const citationFormats = {
    APA: `${result.authors.join(", ")} (${result.year}). ${result.title}. *${result.source}*, *${result.volume}*(${result.issue}). https://doi.org/${result.doi}`,
    MLA: `${result.authors[0]} et al. "${result.title}." *${result.source}* ${result.volume}.${result.issue} (${result.year}).`,
    Chicago: `${result.authors.join(", ")}. "${result.title}." *${result.source}* ${result.volume}, no. ${result.issue} (${result.year}).`,
    BibTeX: `@article{${result.id},\n  title     = {${result.title}},\n  author    = {${result.authors.join(" and ")}},\n  journal   = {${result.source}},\n  volume    = {${result.volume}},\n  number    = {${result.issue}},\n  year      = {${result.year}},\n  doi       = {${result.doi}}\n}`
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: 400,
      borderLeft: "1px solid var(--border)",
      background: "var(--bg-panel)",
      display: "flex",
      flexDirection: "column",
      height: "100%",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "14px 16px",
      borderBottom: "1px solid var(--border-light)",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontWeight: 500,
      color: "var(--text-secondary)"
    }
  }, "Paper Details"), /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      border: "none",
      background: "transparent",
      cursor: "pointer",
      color: "var(--text-muted)",
      padding: 4,
      borderRadius: 4,
      display: "flex"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "close",
    size: 14
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: "auto",
      padding: "16px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 16,
      fontWeight: 500,
      lineHeight: 1.45,
      color: "var(--text)",
      marginBottom: 10,
      textWrap: "pretty"
    }
  }, result.title), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)",
      marginBottom: 10,
      lineHeight: 1.5
    }
  }, result.authors.join(", ")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "8px 16px",
      marginBottom: 14,
      padding: "10px 12px",
      background: "var(--bg)",
      borderRadius: 7
    }
  }, [{
    label: "Journal",
    value: result.source
  }, {
    label: "Year",
    value: result.year
  }, {
    label: "Volume",
    value: `${result.volume} (${result.issue})`
  }, {
    label: "Citations",
    value: result.cited_by.toLocaleString()
  }, {
    label: "Type",
    value: result.type
  }, {
    label: "DOI",
    value: result.doi.slice(0, 24) + "…"
  }].map(({
    label,
    value
  }) => /*#__PURE__*/React.createElement("div", {
    key: label
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.06em",
      marginBottom: 2
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text)",
      fontWeight: 500
    }
  }, value)))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "10px 12px",
      borderRadius: 7,
      background: result.access?.type === "open_access" ? "var(--accent-teal-light)" : result.access?.type.startsWith("sfu") ? "var(--accent-red-light)" : "var(--bg)",
      marginBottom: 14,
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: result.access?.type === "open_access" ? "var(--accent-teal)" : result.access?.type.startsWith("sfu") ? "var(--accent-red)" : "var(--text-muted)",
      marginBottom: 2
    }
  }, result.access?.type === "open_access" ? "Open Access" : result.access?.type === "unpaywall_oa" ? "Free Copy Available" : result.access?.type.startsWith("sfu") ? "Duck Library Access" : "Limited Access"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: "var(--text-secondary)"
    }
  }, result.access?.label)), /*#__PURE__*/React.createElement("a", {
    href: result.doi ? `https://doi.org/${result.doi}` : "#",
    target: "_blank",
    rel: "noopener noreferrer",
    onClick: () => engage("action", result, "pdf"),
    style: {
      fontSize: 11,
      padding: "5px 10px",
      background: "white",
      border: "none",
      borderRadius: 5,
      color: "var(--accent-red)",
      fontWeight: 600,
      cursor: "pointer",
      textDecoration: "none",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      gap: 4
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "externalLink",
    size: 11
  }), "Open")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 5,
      marginBottom: 14
    }
  }, result.topics?.map(t => /*#__PURE__*/React.createElement("span", {
    key: t,
    style: {
      fontSize: 11,
      padding: "3px 8px",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 4,
      color: "var(--text-secondary)"
    }
  }, t))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      borderBottom: "1px solid var(--border-light)",
      marginBottom: 12
    }
  }, ["abstract", "citations", "export"].map(tab => /*#__PURE__*/React.createElement("button", {
    key: tab,
    onClick: () => setActiveTab(tab),
    style: {
      flex: 1,
      padding: "7px 0",
      border: "none",
      background: "transparent",
      fontSize: 12,
      fontWeight: activeTab === tab ? 500 : 400,
      color: activeTab === tab ? "var(--accent-red)" : "var(--text-muted)",
      cursor: "pointer",
      borderBottom: `2px solid ${activeTab === tab ? "var(--accent-red)" : "transparent"}`,
      transition: "color 0.15s",
      fontFamily: "var(--font-ui)",
      textTransform: "capitalize"
    }
  }, tab))), activeTab === "abstract" && /*#__PURE__*/React.createElement("div", null, result.tldr && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "8px 10px",
      background: "var(--accent-red-light)",
      borderRadius: 6,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      fontWeight: 600,
      color: "var(--accent-red)",
      textTransform: "uppercase",
      letterSpacing: "0.06em",
      marginBottom: 4
    }
  }, "AI Summary (TLDR)"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text)",
      lineHeight: 1.5
    }
  }, result.tldr)), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)",
      lineHeight: 1.65
    }
  }, result.abstract)), activeTab === "citations" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginBottom: 10
    }
  }, "Cited by ", result.cited_by.toLocaleString(), " works via Semantic Scholar"), [1, 2, 3].map(i => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      padding: "10px 0",
      borderBottom: "1px solid var(--border-light)"
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      fontFamily: "var(--font-serif)",
      color: "var(--text)",
      lineHeight: 1.4,
      marginBottom: 4
    }
  }, "Related paper title ", i, " citing this work in the context of drug discovery"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)"
    }
  }, "Author et al. \xB7 Journal \xB7 202", i + 2))), /*#__PURE__*/React.createElement("button", {
    style: {
      marginTop: 10,
      fontSize: 12,
      color: "var(--accent-red)",
      background: "transparent",
      border: "none",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      gap: 4
    }
  }, "View all on Semantic Scholar ", /*#__PURE__*/React.createElement(Icon, {
    name: "externalLink",
    size: 12
  }))), activeTab === "export" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 8
    }
  }, Object.entries(citationFormats).map(([fmt, text]) => /*#__PURE__*/React.createElement("div", {
    key: fmt,
    style: {
      border: "1px solid var(--border)",
      borderRadius: 7,
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "7px 10px",
      background: "var(--bg)",
      borderBottom: "1px solid var(--border)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: "var(--text-secondary)",
      letterSpacing: "0.04em"
    }
  }, fmt), /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      engage("action", result, "citation");
      setCopied(fmt);
    },
    style: {
      fontSize: 10,
      padding: "2px 8px",
      background: copied === fmt ? "var(--accent-teal-light)" : "white",
      color: copied === fmt ? "var(--accent-teal)" : "var(--text-secondary)",
      border: "1px solid var(--border)",
      borderRadius: 4,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      gap: 3
    }
  }, copied === fmt ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Icon, {
    name: "check",
    size: 10
  }), " Copied") : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Icon, {
    name: "copy",
    size: 10
  }), " Copy"))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "8px 10px",
      fontSize: 11,
      color: "var(--text-secondary)",
      lineHeight: 1.6,
      fontFamily: fmt === "BibTeX" ? "monospace" : "var(--font-ui)",
      whiteSpace: "pre-wrap",
      maxHeight: 80,
      overflow: "auto"
    }
  }, text))), /*#__PURE__*/React.createElement("button", {
    style: {
      marginTop: 4,
      padding: "8px 0",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 7,
      fontSize: 12,
      color: "var(--text-secondary)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 6,
      width: "100%"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "zotero",
    size: 13
  }), "Save all to Zotero\u2026"))), /*#__PURE__*/React.createElement("div", {
    style: {
      borderTop: "1px solid var(--border-light)",
      padding: "12px 16px",
      display: "flex",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => {
      if (!saved) engage("action", result, "save");
      onSave(result.id);
    },
    style: {
      flex: 1,
      padding: "7px 0",
      background: saved ? "var(--accent-red-light)" : "var(--bg)",
      border: `1px solid ${saved ? "var(--accent-red-mid)" : "var(--border)"}`,
      borderRadius: 6,
      fontSize: 12,
      color: saved ? "var(--accent-red)" : "var(--text-secondary)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 5
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "bookmark",
    size: 13,
    style: {
      fill: saved ? "var(--accent-red)" : "none"
    }
  }), saved ? "Saved" : "Save"), /*#__PURE__*/React.createElement("button", {
    style: {
      flex: 1,
      padding: "7px 0",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 6,
      fontSize: 12,
      color: "var(--text-secondary)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 5
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "zotero",
    size: 13
  }), "Zotero"), /*#__PURE__*/React.createElement("a", {
    href: result.doi ? `https://doi.org/${result.doi}` : "#",
    target: "_blank",
    rel: "noopener noreferrer",
    onClick: () => engage("action", result, "pdf"),
    style: {
      flex: 1,
      padding: "7px 0",
      background: "var(--accent-red)",
      border: "none",
      borderRadius: 6,
      fontSize: 12,
      color: "white",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 5,
      textDecoration: "none",
      fontWeight: 500
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "externalLink",
    size: 13
  }), "Access")));
};
const PROV_SUBJECTS = ["Natural Sciences", "Health & Medicine", "Social Sciences", "Engineering & CS", "Arts & Humanities"];
const PROV_ERAS = ["pre-2010", "2010–present"];
const provKey = (s, e) => s + "|" + e;
const EnginePill = ({
  label,
  ok
}) => /*#__PURE__*/React.createElement("span", {
  style: {
    display: "inline-flex",
    alignItems: "center",
    gap: 5,
    padding: "3px 9px",
    borderRadius: 5,
    fontSize: 11.5,
    fontWeight: 500,
    whiteSpace: "nowrap",
    background: ok ? "var(--accent-teal-light)" : "var(--accent-red-light)",
    color: ok ? "var(--accent-teal)" : "var(--accent-red)",
    border: "1px solid " + (ok ? "transparent" : "var(--accent-red)")
  }
}, /*#__PURE__*/React.createElement(Icon, {
  name: ok ? "check" : "close",
  size: 11
}), label);
const ProvRow = ({
  tone = "neutral",
  icon,
  title,
  children,
  muted = false
}) => {
  const tones = {
    warn: {
      bg: "var(--accent-amber-light)",
      ic: "oklch(52% 0.13 75)"
    },
    alert: {
      bg: "var(--accent-red-light)",
      ic: "var(--accent-red)"
    },
    ok: {
      bg: "var(--accent-teal-light)",
      ic: "var(--accent-teal)"
    },
    neutral: {
      bg: "var(--bg)",
      ic: "var(--text-muted)"
    }
  };
  const t = tones[tone];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 12,
      padding: muted ? "11px 0 2px" : "14px 0",
      borderTop: "1px solid var(--border-light)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 26,
      height: 26,
      borderRadius: 7,
      background: t.bg,
      color: t.ic,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexShrink: 0,
      marginTop: 1
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: icon,
    size: muted ? 13 : 15
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: muted ? 12 : 13.5,
      fontWeight: 600,
      color: muted ? "var(--text-secondary)" : "var(--text)",
      marginBottom: 3
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: muted ? 11.5 : 12.5,
      color: muted ? "var(--text-muted)" : "var(--text-secondary)",
      lineHeight: 1.55
    }
  }, children)));
};
const ProvAction = ({
  icon,
  children,
  onClick,
  busy
}) => /*#__PURE__*/React.createElement("button", {
  onClick: onClick,
  disabled: busy,
  style: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 11px",
    borderRadius: 6,
    border: "1px solid var(--accent-red)",
    background: "var(--bg-panel)",
    color: "var(--accent-red)",
    fontSize: 12,
    fontWeight: 500,
    cursor: busy ? "default" : "pointer",
    opacity: busy ? 0.6 : 1
  },
  onMouseEnter: e => {
    if (!busy) e.currentTarget.style.background = "var(--accent-red-light)";
  },
  onMouseLeave: e => {
    e.currentTarget.style.background = "var(--bg-panel)";
  }
}, /*#__PURE__*/React.createElement(Icon, {
  name: icon,
  size: 13
}), children);
const SearchProvenanceCard = ({
  degraded
}) => {
  const [open, setOpen] = React.useState(true);
  const [searched, setSearched] = React.useState(() => new Set([provKey("Social Sciences", "2010–present")]));
  const [unpacking, setUnpacking] = React.useState(false);
  const [profileOpen, setProfileOpen] = React.useState(false);
  const total = PROV_SUBJECTS.length * PROV_ERAS.length;
  const count = searched.size;
  const full = count === total;
  const isOn = (s, e) => searched.has(provKey(s, e));
  const eraPruned = PROV_SUBJECTS.some(s => isOn(s, "2010–present") && !isOn(s, "pre-2010"));
  const missingSubjects = PROV_SUBJECTS.filter(s => !isOn(s, "2010–present") && !isOn(s, "pre-2010"));
  const widen = () => {
    setUnpacking(true);
    setProfileOpen(false);
    setTimeout(() => {
      const all = new Set();
      PROV_SUBJECTS.forEach(s => PROV_ERAS.forEach(e => all.add(provKey(s, e))));
      setSearched(all);
      setUnpacking(false);
    }, 750);
  };
  const removeDate = () => setSearched(prev => {
    const n = new Set(prev);
    PROV_SUBJECTS.forEach(s => {
      if (n.has(provKey(s, "2010–present"))) n.add(provKey(s, "pre-2010"));
    });
    return n;
  });
  const addSubject = s => {
    setSearched(prev => new Set(prev).add(provKey(s, "2010–present")));
    setProfileOpen(false);
  };
  const goAbout = () => {
    if (window.parent !== window) window.parent.postMessage({
      suiteNav: "analytics"
    }, "*");else window.location.href = "Research Analytics.html";
  };
  const sev = degraded ? {
    color: "var(--accent-red)",
    bg: "var(--accent-red-light)"
  } : full ? {
    color: "var(--accent-teal)",
    bg: "var(--accent-teal-light)"
  } : {
    color: "oklch(52% 0.13 75)",
    bg: "var(--accent-amber-light)"
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 10,
      marginBottom: 16,
      boxShadow: "var(--shadow-sm)",
      overflow: "hidden"
    },
    "data-comment-anchor": "search-provenance"
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => setOpen(!open),
    style: {
      width: "100%",
      display: "flex",
      alignItems: "center",
      gap: 11,
      padding: "12px 16px",
      border: "none",
      background: "transparent",
      textAlign: "left"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 8,
      background: sev.bg,
      color: sev.color,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: degraded ? "warning" : full ? "check" : "info",
    size: 16
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: "var(--text)",
      fontWeight: 600
    }
  }, "What this search covered"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginTop: 1
    }
  }, "Read ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: sev.color
    }
  }, count, " of ", total), " index sections", degraded ? " · 1 engine unavailable" : full ? " · full index" : " · partial coverage")), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)",
      display: "flex",
      alignItems: "center",
      gap: 6,
      flexShrink: 0
    }
  }, open ? "Hide" : "Details", /*#__PURE__*/React.createElement(Icon, {
    name: open ? "chevronDown" : "chevronRight",
    size: 14
  }))), open && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "0 16px 16px"
    }
  }, degraded && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 10,
      padding: "11px 13px",
      background: "var(--accent-red-light)",
      borderRadius: 8,
      borderLeft: "3px solid var(--accent-red)",
      marginBottom: 4
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "warning",
    size: 15,
    style: {
      color: "var(--accent-red)",
      flexShrink: 0,
      marginTop: 1
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12.5,
      color: "var(--text)",
      lineHeight: 1.5
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      fontWeight: 600
    }
  }, "The semantic-sparse engine (SPLADE) was unavailable for this query."), " Results came from keyword and dense matching only \u2014 a paper that matches your topic in meaning but not in exact wording may be missing. Re-run later for the full mix.")), degraded && /*#__PURE__*/React.createElement(ProvRow, {
    tone: "alert",
    icon: "cpu",
    title: "Which engines ran"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 6,
      marginTop: 6,
      marginBottom: 6
    }
  }, /*#__PURE__*/React.createElement(EnginePill, {
    label: "Keyword",
    ok: true
  }), /*#__PURE__*/React.createElement(EnginePill, {
    label: "Semantic-sparse (SPLADE)",
    ok: false
  }), /*#__PURE__*/React.createElement(EnginePill, {
    label: "Semantic-dense",
    ok: true
  })), "Results were fused from 2 of 3 engines with Reciprocal Rank Fusion (k = 60), which weights each engine equally."), /*#__PURE__*/React.createElement(ProvRow, {
    tone: full ? "ok" : "warn",
    icon: "server",
    title: full ? "Full index searched" : "Most of the index was not searched"
  }, full ? "Every section was unpacked and searched, across all five disciplines and both eras. This is now a complete view of the index." : /*#__PURE__*/React.createElement(React.Fragment, null, "Your query was routed to a single section \u2014 ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text)"
    }
  }, "Social Sciences \xB7 2010\u2013present"), ". The other ", total - count, " sections stayed in cold storage or were pruned by your date filter, including ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text)"
    }
  }, "Arts & Humanities"), ", where much of this literature sits, and everything published before 2010."), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 12,
      display: "grid",
      gridTemplateColumns: "118px 1fr 1fr",
      gap: 5,
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("span", null), PROV_ERAS.map(e => /*#__PURE__*/React.createElement("span", {
    key: e,
    style: {
      fontSize: 10.5,
      color: "var(--text-muted)",
      textAlign: "center",
      letterSpacing: "0.03em"
    }
  }, e)), PROV_SUBJECTS.map(s => /*#__PURE__*/React.createElement(React.Fragment, {
    key: s
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11.5,
      color: "var(--text-secondary)",
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis"
    }
  }, s), PROV_ERAS.map(e => {
    const on = isOn(s, e);
    return /*#__PURE__*/React.createElement("div", {
      key: e,
      style: {
        height: 28,
        borderRadius: 5,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 4,
        fontSize: 10.5,
        fontWeight: 500,
        background: on ? "var(--accent-teal-light)" : "var(--bg)",
        border: on ? "1px solid var(--accent-teal)" : "1px dashed var(--border)",
        color: on ? "var(--accent-teal)" : "var(--text-muted)"
      }
    }, on ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Icon, {
      name: "check",
      size: 11
    }), " searched") : "cold");
  })))), !full && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 8,
      marginTop: 13,
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement(ProvAction, {
    icon: "server",
    onClick: widen,
    busy: unpacking
  }, unpacking ? "Unpacking sections…" : "Widen search — unpack cold sections"), eraPruned && /*#__PURE__*/React.createElement(ProvAction, {
    icon: "history",
    onClick: removeDate
  }, "Remove date filter (pre-2010)"), missingSubjects.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement(ProvAction, {
    icon: "filter",
    onClick: () => setProfileOpen(o => !o)
  }, "Switch subject profile"), profileOpen && /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      top: "calc(100% + 4px)",
      left: 0,
      zIndex: 5,
      background: "var(--bg-panel)",
      border: "1px solid var(--border)",
      borderRadius: 8,
      boxShadow: "var(--shadow-md)",
      padding: 4,
      minWidth: 180
    }
  }, missingSubjects.map(s => /*#__PURE__*/React.createElement("button", {
    key: s,
    onClick: () => addSubject(s),
    style: {
      display: "block",
      width: "100%",
      textAlign: "left",
      padding: "7px 10px",
      border: "none",
      background: "transparent",
      borderRadius: 5,
      fontSize: 12.5,
      color: "var(--text)"
    },
    onMouseEnter: e => e.currentTarget.style.background = "var(--bg)",
    onMouseLeave: e => e.currentTarget.style.background = "transparent"
  }, "Add ", s)))))), /*#__PURE__*/React.createElement(ProvRow, {
    tone: "warn",
    icon: "info",
    title: "Tuned for English"
  }, "Matching favours English. Scholarship written in other languages \u2014 including Indigenous-language and non-English-venue work \u2014 ranks lower or is missed entirely, because the semantic model and the section vocabularies are English-only."), /*#__PURE__*/React.createElement(ProvRow, {
    tone: "warn",
    icon: "history",
    title: "Recent work is favoured by default"
  }, "Your profile defaults to recent material (2010 onward) and the ranker adds a small recency boost. Foundational and historical work is under-represented unless you remove the date filter above."), !degraded && /*#__PURE__*/React.createElement(ProvRow, {
    tone: "ok",
    icon: "cpu",
    title: "Which engines ran"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 6,
      marginTop: 6,
      marginBottom: 6
    }
  }, /*#__PURE__*/React.createElement(EnginePill, {
    label: "Keyword",
    ok: true
  }), /*#__PURE__*/React.createElement(EnginePill, {
    label: "Semantic-sparse (SPLADE)",
    ok: true
  }), /*#__PURE__*/React.createElement(EnginePill, {
    label: "Semantic-dense",
    ok: true
  })), "All three engines ran and were fused with Reciprocal Rank Fusion (k = 60), which weights each engine equally \u2014 a result strong in only one method can be pushed down by the others."), /*#__PURE__*/React.createElement(ProvRow, {
    tone: "neutral",
    icon: "book",
    title: "Open access & missing abstracts"
  }, "About ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text)"
    }
  }, "38%"), " of these results are open access. A handful were missing abstracts (the source metadata failed to load) and may rank lower, since the ranker rewards records with complete text to judge."), /*#__PURE__*/React.createElement(ProvRow, {
    tone: "neutral",
    icon: "search",
    title: "Keyword matching is literal"
  }, "The keyword engine does not match word variants or spellings on its own \u2014 \"labour\" \u2260 \"labor\", \"fisheries\" \u2260 \"fishing\". If results look thin, try alternate forms and spellings."), /*#__PURE__*/React.createElement(ProvRow, {
    tone: "neutral",
    icon: "cpu",
    title: "Speed trade-offs",
    muted: true
  }, "For speed, very long queries are compressed to their most important terms and a small number of borderline matches may be dropped. Measured impact on recall is minor."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 12,
      flexWrap: "wrap",
      marginTop: 14,
      paddingTop: 12,
      borderTop: "1px solid var(--border-light)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)",
      fontFamily: "var(--font-ui)"
    }
  }, "Fields from ", /*#__PURE__*/React.createElement("code", {
    style: {
      fontFamily: "ui-monospace, monospace",
      fontSize: 10.5,
      background: "var(--bg)",
      padding: "1px 5px",
      borderRadius: 3,
      border: "1px solid var(--border-light)"
    }
  }, "get_search_provenance"), " \xB7 index of 150,413,098 documents"), /*#__PURE__*/React.createElement("button", {
    onClick: goAbout,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 5,
      border: "none",
      background: "transparent",
      color: "var(--accent-red)",
      fontSize: 12,
      fontWeight: 600,
      cursor: "pointer"
    }
  }, "About this index ", /*#__PURE__*/React.createElement(Icon, {
    name: "chevronRight",
    size: 13
  })))));
};
const SequentialBanner = () => /*#__PURE__*/React.createElement("div", {
  style: {
    padding: "10px 13px",
    background: "var(--accent-teal-light)",
    borderRadius: 8,
    borderLeft: "3px solid var(--accent-teal)",
    marginBottom: 12,
    fontSize: 12.5,
    color: "var(--text)",
    lineHeight: 1.5,
    display: "flex",
    gap: 8,
    alignItems: "flex-start"
  },
  role: "status"
}, /*#__PURE__*/React.createElement(Icon, {
  name: "info",
  size: 14,
  style: {
    color: "var(--accent-teal)",
    flexShrink: 0,
    marginTop: 1
  }
}), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("strong", {
  style: {
    fontWeight: 600
  }
}, "Running from USB \u2014"), " searches run one at a time and line up below. For instant results, install to this PC (run SETUP.bat on the drive)."));
const QueueStatusChip = ({
  item,
  ahead
}) => {
  const map = {
    queued: {
      bg: "var(--border-light)",
      fg: "var(--text-secondary)",
      text: ahead > 0 ? `Queued · ${ahead} ahead` : "Queued · next"
    },
    running: {
      bg: "var(--accent-amber-light)",
      fg: "var(--accent-amber)",
      text: "Searching…"
    },
    done: {
      bg: "var(--accent-teal-light)",
      fg: "var(--accent-teal)",
      text: `${item.count} result${item.count === 1 ? "" : "s"}`
    },
    error: {
      bg: "var(--accent-red-light)",
      fg: "var(--accent-red)",
      text: "Failed"
    }
  };
  const s = map[item.status] || map.queued;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: s.fg,
      background: s.bg,
      borderRadius: 999,
      padding: "2px 9px",
      whiteSpace: "nowrap",
      flexShrink: 0
    }
  }, s.text);
};
const SearchQueuePanel = ({
  queue,
  viewedId,
  onView,
  onRemove,
  onClear
}) => {
  const doneCount = queue.filter(q => q.status === "done" || q.status === "error").length;
  let queuedSeen = 0;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      border: "1px solid var(--border-light)",
      borderRadius: 10,
      background: "var(--bg-panel)",
      marginBottom: 14,
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "9px 12px",
      borderBottom: "1px solid var(--border-light)",
      background: "var(--bg)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      fontWeight: 600,
      color: "var(--text)",
      display: "flex",
      alignItems: "center",
      gap: 7
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "history",
    size: 14,
    style: {
      color: "var(--text-muted)"
    }
  }), "Search queue ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-muted)",
      fontWeight: 400
    }
  }, "\xB7 ", queue.length)), doneCount > 0 && /*#__PURE__*/React.createElement("button", {
    onClick: onClear,
    style: {
      fontSize: 11.5,
      color: "var(--text-secondary)",
      background: "none",
      border: "none",
      cursor: "pointer",
      fontFamily: "var(--font-ui)"
    }
  }, "Clear completed")), /*#__PURE__*/React.createElement("div", {
    style: {
      maxHeight: 176,
      overflowY: "auto"
    }
  }, queue.map(item => {
    const ahead = item.status === "queued" ? queuedSeen++ : 0;
    const clickable = item.status === "done";
    return /*#__PURE__*/React.createElement("div", {
      key: item.id,
      onClick: clickable ? () => onView(item) : undefined,
      style: {
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 12px",
        borderTop: "1px solid var(--border-light)",
        cursor: clickable ? "pointer" : "default",
        background: item.id === viewedId ? "var(--accent-red-light)" : "transparent"
      }
    }, /*#__PURE__*/React.createElement(QueueStatusChip, {
      item: item,
      ahead: ahead
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1,
        minWidth: 0,
        fontSize: 12.5,
        color: "var(--text)",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      },
      title: item.query
    }, item.query), item.status === "running" ? /*#__PURE__*/React.createElement("span", {
      style: {
        width: 44,
        height: 4,
        borderRadius: 2,
        background: "var(--border)",
        overflow: "hidden",
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "block",
        height: "100%",
        width: "45%",
        background: "var(--accent-amber)",
        borderRadius: 2,
        animation: "sfu-skimmer 1.1s ease-in-out infinite"
      }
    })) : /*#__PURE__*/React.createElement("button", {
      onClick: e => {
        e.stopPropagation();
        onRemove(item.id);
      },
      "aria-label": "Remove from queue",
      title: "Remove",
      style: {
        background: "none",
        border: "none",
        cursor: "pointer",
        color: "var(--text-muted)",
        flexShrink: 0,
        fontSize: 15,
        lineHeight: 1,
        padding: "0 2px"
      }
    }, "\xD7"));
  })));
};
const SearchScreen = ({
  savedIds,
  toggleSave,
  degraded,
  setAiStatus,
  interfacePrefs,
  sequential,
  draftStream,
  rerunReq,
  onRerunConsumed
}) => {
  const [query, setQuery] = React.useState("");
  const [filters, setFilters] = React.useState({
    type: "All",
    date: "Any time",
    access: "Any",
    sort: "Relevance"
  });
  const [results, setResults] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [searched, setSearched] = React.useState(false);
  const [selected, setSelected] = React.useState(null);
  const [usingMock, setUsingMock] = React.useState(false);
  const [filtersOpen, setFiltersOpen] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const [hasMore, setHasMore] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [pageError, setPageError] = React.useState(null);
  const pageCtxRef = React.useRef(null);
  const scrollRef = React.useRef(null);
  const sentinelRef = React.useRef(null);
  const resultsRef = React.useRef(results);
  resultsRef.current = results;
  const [preliminary, setPreliminary] = React.useState(false);
  const swapRef = React.useRef(null);
  const searchSeqRef = React.useRef(0);
  const pendingMetaRef = React.useRef(null);
  const engageQueryRef = React.useRef("");
  React.useEffect(() => {
    const note = () => {
      if (swapRef.current) swapRef.current.noteActivity();
    };
    const evs = ["mousemove", "keydown", "pointerdown", "wheel", "selectionchange", "touchstart"];
    evs.forEach(ev => document.addEventListener(ev, note, {
      passive: true
    }));
    const sc = scrollRef.current;
    if (sc) sc.addEventListener("scroll", note, {
      passive: true
    });
    return () => {
      evs.forEach(ev => document.removeEventListener(ev, note));
      if (sc) sc.removeEventListener("scroll", note);
      if (swapRef.current) swapRef.current.cancel();
    };
  }, []);
  const onCardHover = React.useCallback(id => {
    if (swapRef.current) swapRef.current.setHovered(id);
  }, []);
  const [elapsed, setElapsed] = React.useState(0);
  const [healthWarm, setHealthWarm] = React.useState(true);
  const [retryState, setRetryState] = React.useState(null);
  const showSkeleton = loading && elapsed >= 300 && !retryState;
  const showWarming = loading && elapsed >= 10000 && healthWarm === false && !retryState;
  React.useEffect(() => {
    if (!loading || retryState) return;
    setElapsed(0);
    const start = Date.now();
    const iv = setInterval(() => setElapsed(Date.now() - start), 100);
    return () => clearInterval(iv);
  }, [loading, retryState]);
  React.useEffect(() => {
    if (!retryState) return;
    if (retryState.remaining <= 0) {
      setRetryState(null);
      doSearch();
      return;
    }
    const iv = setTimeout(() => setRetryState(s => s && {
      remaining: s.remaining - 1
    }), 700);
    return () => clearTimeout(iv);
  }, [retryState]);
  const queryRef = React.useRef(query);
  queryRef.current = query;
  const filtersRef = React.useRef(filters);
  filtersRef.current = filters;
  const queueAuto = !interfacePrefs || interfacePrefs.searchQueueAuto !== false;
  const queueOn = queueAuto ? !!sequential : !!(interfacePrefs && interfacePrefs.searchQueue);
  const [queue, setQueue] = React.useState([]);
  const [viewed, setViewed] = React.useState(null);
  const runningRef = React.useRef(false);
  const notifyDone = (q, ok, count) => {
    try {
      if (typeof window.Notification !== "function" || window.Notification.permission !== "granted") return;
      new window.Notification(ok ? "Search done: " + q : "Search failed: " + q, {
        body: ok ? count + " result" + (count === 1 ? "" : "s") : "Open the queue to retry."
      });
    } catch (e) {}
  };
  const enqueue = raw => {
    const q = (raw || "").trim();
    if (!q) return;
    try {
      if (typeof window.Notification === "function" && window.Notification.permission === "default") window.Notification.requestPermission();
    } catch (e) {}
    const id = "q" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    setQueue(prev => [...prev, {
      id,
      query: q,
      filters: filtersRef.current,
      status: "queued",
      count: 0,
      results: [],
      mock: false,
      error: null
    }]);
    setSearched(true);
    setQuery("");
  };
  React.useEffect(() => {
    if (!queueOn || runningRef.current) return;
    const next = queue.find(it => it.status === "queued");
    if (!next) return;
    runningRef.current = true;
    setQueue(qs => qs.map(it => it.id === next.id ? {
      ...it,
      status: "running"
    } : it));
    (async () => {
      try {
        const res = await window.SFUApi.search(next.query, next.filters, window.SFUApi.MAX_PAGES);
        if (res.source === "retry") {
          const backoff = Math.max(1, res.retryAfter || 3) * 1000;
          setTimeout(() => {
            setQueue(qs => qs.map(it => it.id === next.id ? {
              ...it,
              status: "queued"
            } : it));
            runningRef.current = false;
          }, backoff);
          return;
        }
        const live = res.source === "live" && res.results && res.results.length > 0;
        const list = live ? res.results : window.SFUMock && window.SFUMock.results || [];
        if (res.source === "live") {
          engageQueryRef.current = next.query;
          engage("query", next.query);
        }
        const count = list.length;
        setQueue(qs => qs.map(it => it.id === next.id ? {
          ...it,
          status: "done",
          count,
          results: list,
          mock: !live
        } : it));
        if (window.SFUHistory) window.SFUHistory.record({
          q: next.query,
          at: Date.now(),
          results: count,
          live
        });
        setResults(list);
        setUsingMock(!live);
        setViewed({
          id: next.id,
          query: next.query
        });
        setSelected(null);
        setPage(window.SFUApi.MAX_PAGES);
        setHasMore(false);
        setPageError(null);
        notifyDone(next.query, true, count);
      } catch (e) {
        setQueue(qs => qs.map(it => it.id === next.id ? {
          ...it,
          status: "error",
          error: String(e && e.message || e)
        } : it));
        notifyDone(next.query, false, 0);
      }
      runningRef.current = false;
    })();
  }, [queue, queueOn]);
  const viewQueued = item => {
    if (item.status !== "done") return;
    engageQueryRef.current = item.query;
    setResults(item.results || []);
    setUsingMock(!!item.mock);
    setViewed({
      id: item.id,
      query: item.query
    });
    setSelected(null);
    setPage(window.SFUApi.MAX_PAGES);
    setHasMore(false);
    setPageError(null);
  };
  const removeQueued = id => setQueue(prev => prev.filter(it => it.id !== id));
  const clearCompleted = () => setQueue(prev => prev.filter(it => it.status === "queued" || it.status === "running"));
  const handleSearch = () => {
    if (queueOn) enqueue(queryRef.current);else doSearch();
  };
  const doSearch = async () => {
    if (!queryRef.current.trim()) return;
    const seq = ++searchSeqRef.current;
    if (swapRef.current) swapRef.current.cancel();
    swapRef.current = null;
    pendingMetaRef.current = null;
    setPreliminary(false);
    const useStream = !!draftStream && !sequential && !queueOn && typeof window.SFUApi.searchStream === "function" && typeof window.SFUApi.createDraftSwapController === "function";
    let ctrl = null;
    if (useStream) {
      ctrl = window.SFUApi.createDraftSwapController({
        isSelecting: () => {
          try {
            const sel = window.getSelection && window.getSelection();
            return !!(sel && String(sel).length > 0);
          } catch (e) {
            return false;
          }
        },
        apply: (list, info) => {
          if (seq !== searchSeqRef.current) return;
          setResults(list);
          setPreliminary(info.state === "draft");
          if (info.state !== "draft" && pendingMetaRef.current) {
            setPage(pendingMetaRef.current.page);
            setHasMore(pendingMetaRef.current.more);
          }
        }
      });
      swapRef.current = ctrl;
    }
    setLoading(true);
    setRetryState(null);
    setSelected(null);
    setPage(1);
    setHasMore(false);
    setLoadingMore(false);
    setPageError(null);
    pageCtxRef.current = {
      query: queryRef.current,
      filters: filtersRef.current
    };
    try {
      if (window.SFUApi) window.SFUApi.health().then(r => setHealthWarm(r.warm !== false));
    } catch (e) {}
    try {
      const res = ctrl ? await window.SFUApi.searchStream(queryRef.current, filtersRef.current, 1, draft => {
        if (seq !== searchSeqRef.current || !draft.results || !draft.results.length) return;
        setHasMore(false);
        setUsingMock(false);
        setLoading(false);
        setSearched(true);
        ctrl.showDraft(draft.results);
      }) : await window.SFUApi.search(queryRef.current, filtersRef.current, 1);
      if (ctrl && seq !== searchSeqRef.current) return;
      if (res.source === "retry") {
        setRetryState({
          remaining: res.retryAfter
        });
        return;
      }
      const liveHasResults = res.source === "live" && res.results && res.results.length > 0;
      if (res.source === "live") {
        engageQueryRef.current = queryRef.current;
        engage("query", queryRef.current);
      }
      const showingMock = !liveHasResults;
      const sample = window.SFUMock.results || [];
      const list = liveHasResults || res.source === "mock" ? res.results : sample.slice(0, window.SFUApi.pageLimit(res.page || 1));
      const more = liveHasResults || res.source === "mock" ? !!res.hasMore : (res.page || 1) < window.SFUApi.MAX_PAGES && sample.length > list.length;
      if (window.SFUHistory) window.SFUHistory.record({
        q: queryRef.current,
        at: Date.now(),
        results: liveHasResults ? list.length : res.meta && res.meta.count || 0,
        live: liveHasResults
      });
      if (ctrl) {
        pendingMetaRef.current = {
          page: res.page || 1,
          more: more
        };
        if (ctrl.state === "idle") {
          setPage(res.page || 1);
          setHasMore(more);
        }
        ctrl.offerFinal(list);
      } else {
        setResults(list);
        setPage(res.page || 1);
        setHasMore(more);
      }
      setUsingMock(showingMock);
      setDegradedNotice(res.degraded ? res.degradedShards ? `Degraded — ${res.degradedShards} shard(s) unavailable, partial results shown.` : "Degraded — an engine was unavailable for this query, partial results shown." : null);
      if (setAiStatus) setAiStatus(res.source === "live" ? "online" : "offline");
    } catch (e) {
      if (ctrl) {
        if (seq !== searchSeqRef.current) return;
        ctrl.cancel();
        setPreliminary(false);
      }
      const sample = window.SFUMock.results || [];
      const first = sample.slice(0, window.SFUApi.pageLimit(1));
      setResults(first);
      setPage(1);
      setHasMore(sample.length > first.length);
      setUsingMock(true);
      if (setAiStatus) setAiStatus("offline");
    } finally {
      setLoading(false);
      setSearched(true);
    }
  };
  const [degradedNotice, setDegradedNotice] = React.useState(null);
  React.useEffect(() => {
    if (!searched || loading || preliminary || usingMock || !results.length) return;
    engage("impressions", engageQueryRef.current, results);
  }, [results, searched, loading, preliminary, usingMock]);
  const openResult = React.useCallback(r => {
    engage("click", r);
    engage("action", r, "abstract");
    setSelected(r);
  }, []);
  const loadingMoreRef = React.useRef(false);
  const loadMore = React.useCallback(async () => {
    const ctx = pageCtxRef.current;
    if (!ctx || queueOn || loadingMoreRef.current) return;
    if (!hasMore || loading || retryState || preliminary) return;
    const next = page + 1;
    if (next > window.SFUApi.MAX_PAGES) {
      setHasMore(false);
      return;
    }
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setPageError(null);
    try {
      const res = await window.SFUApi.search(ctx.query, ctx.filters, next);
      if (res.source === "retry") {
        setPageError("Server busy — scroll again to retry.");
        return;
      }
      const incoming = res.results || [];
      const prev = resultsRef.current || [];
      const merged = window.SFUApi.mergePages(prev, incoming);
      setResults(merged);
      setHasMore(!!res.hasMore && merged.length > prev.length);
      setPage(next);
      if (res.source !== "live") setUsingMock(true);
    } catch (e) {
      setPageError("Could not load more results.");
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [page, hasMore, loading, retryState, queueOn, preliminary]);
  React.useEffect(() => {
    if (!hasMore || queueOn || loading || retryState) return;
    const node = sentinelRef.current;
    if (!node || typeof window.IntersectionObserver !== "function") return;
    const io = new window.IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) loadMore();
    }, {
      root: scrollRef.current || null,
      rootMargin: "300px 0px"
    });
    io.observe(node);
    return () => io.disconnect();
  }, [hasMore, queueOn, loading, retryState, loadMore, results.length]);
  React.useEffect(() => {
    if (!rerunReq || !rerunReq.q) return;
    setQuery(rerunReq.q);
    queryRef.current = rerunReq.q;
    doSearch();
    if (onRerunConsumed) onRerunConsumed();
  }, [rerunReq && rerunReq.n]);
  if (!searched && !loading && !retryState) {
    return /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 var(--landing-pad, 60px) 60px"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        marginBottom: 32,
        textAlign: "center"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 52,
        height: 52,
        borderRadius: 14,
        background: "var(--accent-red)",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        marginBottom: 16
      }
    }, /*#__PURE__*/React.createElement(Icon, {
      name: "search",
      size: 22,
      style: {
        color: "white"
      }
    })), /*#__PURE__*/React.createElement("h1", {
      style: {
        fontSize: 26,
        fontFamily: "var(--font-serif)",
        fontWeight: 500,
        color: "var(--text)",
        marginBottom: 8
      }
    }, "Research begins here."), /*#__PURE__*/React.createElement("p", {
      style: {
        fontSize: 14,
        color: "var(--text-muted)",
        maxWidth: 400,
        lineHeight: 1.6
      }
    }, "Search 250M+ scholarly works with AI-powered query understanding and Duck Library access resolution.")), /*#__PURE__*/React.createElement("div", {
      style: {
        width: "100%",
        maxWidth: 600
      }
    }, /*#__PURE__*/React.createElement(SearchBar, {
      query: query,
      setQuery: setQuery,
      onSearch: handleSearch,
      loading: loading,
      filters: filters,
      setFilters: setFilters,
      compact: true
    }), /*#__PURE__*/React.createElement(FiltersExpander, {
      filters: filters,
      setFilters: setFilters,
      alwaysOpen: interfacePrefs && interfacePrefs.advancedFiltersOpen
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 24,
        display: "flex",
        flexWrap: "wrap",
        gap: 8,
        justifyContent: "center",
        maxWidth: 580
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: 12,
        color: "var(--text-muted)",
        width: "100%",
        textAlign: "center",
        marginBottom: 4
      }
    }, "Try:"), ["indigenous knowledge systems in climate adaptation", "recent ML papers for drug discovery", "CRISPR gene editing in salmon, open access", "climate change BC fisheries 2020–2025"].map(ex => /*#__PURE__*/React.createElement("button", {
      key: ex,
      onClick: () => {
        setQuery(ex);
      },
      style: {
        fontSize: 12,
        padding: "6px 12px",
        background: "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: 16,
        color: "var(--text-secondary)",
        cursor: "pointer",
        fontFamily: "var(--font-ui)",
        transition: "border-color 0.15s, color 0.15s"
      },
      onMouseEnter: e => {
        e.currentTarget.style.borderColor = "var(--accent-red)";
        e.currentTarget.style.color = "var(--accent-red)";
      },
      onMouseLeave: e => {
        e.currentTarget.style.borderColor = "var(--border)";
        e.currentTarget.style.color = "var(--text-secondary)";
      }
    }, ex))));
  }
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: "flex",
      flexDirection: "column",
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "14px 20px 12px",
      borderBottom: "1px solid var(--border-light)",
      background: "var(--bg-panel)"
    }
  }, /*#__PURE__*/React.createElement(SearchBar, {
    query: query,
    setQuery: setQuery,
    onSearch: handleSearch,
    loading: loading,
    filters: filters,
    setFilters: setFilters,
    compact: true
  }), /*#__PURE__*/React.createElement(FiltersExpander, {
    filters: filters,
    setFilters: setFilters,
    alwaysOpen: interfacePrefs && interfacePrefs.advancedFiltersOpen
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: "flex",
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    ref: scrollRef,
    style: {
      flex: 1,
      overflow: "auto",
      padding: "16px 20px"
    }
  }, retryState ? /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "24px 0",
      textAlign: "center"
    },
    role: "status",
    "aria-live": "polite"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      color: "var(--text)",
      marginBottom: 6
    }
  }, "Server busy \u2014 retrying in ", retryState.remaining, "s\u2026"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12.5,
      color: "var(--text-muted)"
    }
  }, "Too many searches at once. Auto-retrying automatically (you don't need to do anything)."), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 200,
      height: 4,
      background: "var(--border)",
      borderRadius: 2,
      margin: "14px auto 0",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      height: "100%",
      width: `${Math.max(0, 100 - retryState.remaining / Math.max(1, retryState.remaining) * 100)}%`,
      background: "var(--accent-red)",
      borderRadius: 2,
      transition: "width 0.7s linear"
    }
  }))) : showWarming ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "11px 13px",
      background: "var(--accent-amber-light)",
      borderRadius: 8,
      borderLeft: "3px solid var(--accent-amber)",
      fontSize: 12.5,
      color: "var(--text)",
      lineHeight: 1.5,
      display: "flex",
      gap: 10,
      alignItems: "flex-start"
    },
    role: "status"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "history",
    size: 15,
    style: {
      color: "var(--accent-amber)",
      flexShrink: 0,
      marginTop: 1
    }
  }), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("strong", {
    style: {
      fontWeight: 600
    }
  }, "Index warming \u2014"), " the first search after a restart takes longer while the index pages in. Results are on the way.")), [1, 2, 3].map(i => /*#__PURE__*/React.createElement(SkeletonResultCard, {
    key: i
  }))) : loading ? showSkeleton ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      color: "var(--text-muted)",
      marginBottom: 8,
      display: "flex",
      alignItems: "center",
      gap: 8,
      fontVariantNumeric: "tabular-nums"
    }
  }, "Searching ", /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: "normal",
      color: "var(--text-secondary)"
    }
  }, "\"", query, "\""), " \xB7 ", (elapsed / 1000).toFixed(1), "s"), [1, 2, 3].map(i => /*#__PURE__*/React.createElement(SkeletonResultCard, {
    key: i
  }))) : null : /*#__PURE__*/React.createElement(React.Fragment, null, (degradedNotice || degraded) && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "10px 13px",
      background: "var(--accent-amber-light)",
      borderRadius: 8,
      borderLeft: "3px solid var(--accent-amber)",
      marginBottom: 12,
      fontSize: 12.5,
      color: "var(--text)",
      lineHeight: 1.5,
      display: "flex",
      gap: 8,
      alignItems: "flex-start"
    },
    role: "status"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "warning",
    size: 14,
    style: {
      color: "var(--accent-amber)",
      flexShrink: 0,
      marginTop: 1
    }
  }), /*#__PURE__*/React.createElement("span", null, degradedNotice || "Degraded — partial results shown.")), queueOn && /*#__PURE__*/React.createElement(SequentialBanner, null), queueOn && queue.length > 0 && /*#__PURE__*/React.createElement(SearchQueuePanel, {
    queue: queue,
    viewedId: viewed && viewed.id,
    onView: viewQueued,
    onRemove: removeQueued,
    onClear: clearCompleted
  }), !queueOn || results.length > 0 ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(SearchProvenanceCard, {
    degraded: degraded
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      marginBottom: 12
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      color: "var(--text-muted)"
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text)",
      fontWeight: 600
    }
  }, results.length), " ", hasMore ? "results loaded" : "results", " for ", /*#__PURE__*/React.createElement("em", null, "\"", queueOn ? viewed && viewed.query || "" : query, "\""))), preliminary && /*#__PURE__*/React.createElement("div", {
    "data-testid": "sfu-preliminary-note",
    role: "status",
    "aria-live": "polite",
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginBottom: 10,
      lineHeight: 1.5
    }
  }, "Preliminary keyword matches \u2014 the ranked list replaces them when you pause."), results.map((r, i) => /*#__PURE__*/React.createElement(ResultCard, {
    key: r.id,
    result: r,
    index: i + 1,
    onClick: openResult,
    saved: savedIds.has(r.id),
    onSave: toggleSave,
    preliminary: preliminary,
    onHover: swapRef.current ? onCardHover : undefined
  })), !queueOn && /*#__PURE__*/React.createElement("div", {
    ref: sentinelRef,
    "data-testid": "sfu-scroll-sentinel",
    style: {
      padding: "14px 0 4px",
      textAlign: "center",
      minHeight: 8
    }
  }, loadingMore ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 8
    },
    "aria-live": "polite"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      color: "var(--text-muted)"
    }
  }, "Loading more results\u2026"), /*#__PURE__*/React.createElement(SkeletonResultCard, null)) : pageError ? /*#__PURE__*/React.createElement("button", {
    onClick: loadMore,
    style: {
      fontSize: 12.5,
      padding: "7px 14px",
      background: "var(--bg-panel)",
      border: "1px solid var(--border)",
      borderRadius: 7,
      color: "var(--accent-red)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)"
    }
  }, pageError, " Try again") : hasMore ? /*#__PURE__*/React.createElement("button", {
    onClick: loadMore,
    "data-testid": "sfu-load-more",
    style: {
      fontSize: 12.5,
      padding: "7px 14px",
      background: "var(--bg-panel)",
      border: "1px solid var(--border)",
      borderRadius: 7,
      color: "var(--text-secondary)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)"
    }
  }, "Load more results") : results.length > 0 ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)"
    }
  }, "End of results", page >= window.SFUApi.MAX_PAGES ? " — refine your query for more" : "") : null)) : /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "28px 4px",
      textAlign: "center",
      color: "var(--text-muted)",
      fontSize: 13
    }
  }, "Your searches will appear here as they finish."))), selected && /*#__PURE__*/React.createElement(ResultDetail, {
    result: selected,
    onClose: () => setSelected(null),
    saved: savedIds.has(selected.id),
    onSave: toggleSave
  })));
};
const SavedScreen = ({
  savedIds,
  toggleSave
}) => {
  const pool = {};
  (window.SFUMock && window.SFUMock.results || []).forEach(r => {
    pool[r.id] = r;
  });
  Object.assign(pool, window.__sfuResults || {});
  const saved = Array.from(savedIds).map(id => pool[id]).filter(Boolean);
  const [selected, setSelected] = React.useState(null);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: "flex",
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: "auto",
      padding: "20px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 18,
      fontWeight: 500,
      marginBottom: 4,
      color: "var(--text)"
    }
  }, "Saved Papers"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-muted)",
      marginBottom: 16
    }
  }, saved.length, " papers saved"), saved.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "center",
      padding: "60px 0",
      color: "var(--text-muted)"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "bookmark",
    size: 32,
    style: {
      marginBottom: 12,
      opacity: 0.3
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 14
    }
  }, "No saved papers yet.", /*#__PURE__*/React.createElement("br", null), "Bookmark results from your searches.")) : saved.map((r, i) => /*#__PURE__*/React.createElement(ResultCard, {
    key: r.id,
    result: r,
    index: i + 1,
    onClick: setSelected,
    saved: true,
    onSave: toggleSave
  }))), selected && /*#__PURE__*/React.createElement(ResultDetail, {
    result: selected,
    onClose: () => setSelected(null),
    saved: savedIds.has(selected.id),
    onSave: toggleSave
  }));
};
const HistoryScreen = ({
  onRerun
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
  const fmtTime = at => {
    const d = new Date(at);
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric"
    }) + " · " + d.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit"
    });
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: "auto",
      padding: "20px 24px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 720
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 18,
      fontWeight: 500,
      marginBottom: 3,
      color: "var(--text)"
    }
  }, "Search History"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginBottom: 16
    }
  }, entries.length, " ", entries.length === 1 ? "search" : "searches", " \xB7 stored locally on this device", entries.length > 0 && /*#__PURE__*/React.createElement(React.Fragment, null, " \xB7 ", /*#__PURE__*/React.createElement("button", {
    onClick: () => window.SFUHistory && window.SFUHistory.clear(),
    style: {
      border: "none",
      background: "none",
      color: "var(--accent-red)",
      fontSize: 12,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      padding: 0
    }
  }, "Clear all"))), entries.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: "center",
      padding: "60px 0",
      color: "var(--text-muted)"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "history",
    size: 32,
    style: {
      marginBottom: 12,
      opacity: 0.3
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 14
    }
  }, "No searches yet.", /*#__PURE__*/React.createElement("br", null), "Queries you run will appear here so you can revisit them.")) : /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 6
    }
  }, entries.map(e => /*#__PURE__*/React.createElement("div", {
    key: e.at,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10,
      padding: "11px 14px",
      borderRadius: 9,
      border: "1px solid var(--border-light)",
      background: "var(--bg-panel)"
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: () => onRerun && onRerun(e.q),
    title: 'Search again: ' + e.q,
    style: {
      flex: 1,
      minWidth: 0,
      border: "none",
      background: "none",
      textAlign: "left",
      cursor: "pointer",
      padding: 0,
      fontFamily: "var(--font-ui)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: 13.5,
      color: "var(--text)",
      fontWeight: 500,
      lineHeight: 1.35,
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap"
    }
  }, e.q), /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: 11,
      color: "var(--text-muted)",
      marginTop: 3
    }
  }, fmtTime(e.at), typeof e.results === "number" ? ` · ${e.results} results` : "", e.live === false ? " · sample data" : "")), /*#__PURE__*/React.createElement("button", {
    onClick: () => onRerun && onRerun(e.q),
    title: "Run this search again",
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: 5,
      padding: "5px 10px",
      border: "1px solid var(--border)",
      borderRadius: 6,
      background: "var(--bg)",
      fontSize: 11.5,
      color: "var(--text-secondary)",
      cursor: "pointer",
      flexShrink: 0,
      fontFamily: "var(--font-ui)"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "search",
    size: 11
  }), " Rerun"), /*#__PURE__*/React.createElement("button", {
    onClick: () => window.SFUHistory && window.SFUHistory.remove(e.at),
    title: "Remove from history",
    "aria-label": 'Remove "' + e.q + '" from history',
    style: {
      border: "none",
      background: "none",
      color: "var(--text-muted)",
      cursor: "pointer",
      padding: 4,
      borderRadius: 4,
      display: "flex",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "close",
    size: 13
  })))))));
};
const DatabasesScreen = () => {
  const [search, setSearch] = React.useState("");
  const filtered = (window.SFUMock && window.SFUMock.databases || []).filter(d => d.name.toLowerCase().includes(search.toLowerCase()) || d.subjects.some(s => s.toLowerCase().includes(search.toLowerCase())));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: "auto",
      padding: "20px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 18,
      fontWeight: 500,
      marginBottom: 4,
      color: "var(--text)"
    }
  }, "Duck Library Databases"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-muted)",
      marginBottom: 14
    }
  }, "764 subscription databases \xB7 Registry synced daily"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 0,
      background: "var(--bg-panel)",
      border: "1px solid var(--border)",
      borderRadius: 7,
      padding: "0 10px",
      marginBottom: 14,
      maxWidth: 400
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "search",
    size: 14,
    style: {
      color: "var(--text-muted)"
    }
  }), /*#__PURE__*/React.createElement("input", {
    value: search,
    onChange: e => setSearch(e.target.value),
    placeholder: "Filter databases\u2026",
    style: {
      flex: 1,
      border: "none",
      background: "transparent",
      outline: "none",
      padding: "8px 8px",
      fontSize: 13,
      color: "var(--text)",
      fontFamily: "var(--font-ui)"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
      gap: 8
    }
  }, filtered.map(db => /*#__PURE__*/React.createElement("div", {
    key: db.id,
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 8,
      padding: "12px 14px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      marginBottom: 4
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 500,
      color: "var(--text)"
    }
  }, db.name), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      padding: "2px 6px",
      borderRadius: 3,
      background: db.free ? "var(--accent-teal-light)" : "var(--accent-red-light)",
      color: db.free ? "var(--accent-teal)" : "var(--accent-red)",
      fontWeight: 500,
      whiteSpace: "nowrap",
      marginLeft: 6,
      flexShrink: 0
    }
  }, db.free ? "Free" : "Duck Sub.")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)",
      marginBottom: 5
    }
  }, db.provider), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 3
    }
  }, db.subjects.map(s => /*#__PURE__*/React.createElement("span", {
    key: s,
    style: {
      fontSize: 10,
      padding: "1px 6px",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 3,
      color: "var(--text-secondary)"
    }
  }, s)), db.proxy && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 10,
      padding: "1px 6px",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 3,
      color: "var(--text-secondary)"
    }
  }, "EZProxy"))))));
};
const PrivacyToggle = ({
  label,
  desc,
  defaultOn
}) => {
  const [on, setOn] = React.useState(defaultOn);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      gap: 12,
      padding: "10px 12px",
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 8
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 500,
      color: "var(--text)"
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      marginTop: 2
    }
  }, desc)), /*#__PURE__*/React.createElement("button", {
    onClick: () => setOn(!on),
    style: {
      width: 38,
      height: 22,
      borderRadius: 11,
      background: on ? "var(--accent-red)" : "var(--border)",
      border: "none",
      cursor: "pointer",
      position: "relative",
      flexShrink: 0,
      transition: "background 0.2s"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 16,
      height: 16,
      borderRadius: "50%",
      background: "white",
      position: "absolute",
      top: 3,
      left: on ? 19 : 3,
      transition: "left 0.2s",
      boxShadow: "0 1px 3px rgba(0,0,0,0.2)"
    }
  })));
};
const SettingsScreen = ({
  interfacePrefs,
  setInterfacePref,
  sequential
}) => {
  const [tab, setTab] = React.useState("interface");
  const [zoteroKey, setZoteroKey] = React.useState("••••••••••••••••");
  const [dictTab, setDictTab] = React.useState("abbreviations");
  const [dictEntries, setDictEntries] = React.useState([{
    abbr: "REM",
    full: "Resource & Environmental Management"
  }, {
    abbr: "FASS",
    full: "Faculty of Arts & Social Sciences"
  }, {
    abbr: "ILL",
    full: "Interlibrary Loan"
  }, {
    abbr: "LCSH",
    full: "Library of Congress Subject Headings"
  }]);
  const settingsTabs = [{
    id: "zotero",
    label: "Zotero"
  }, {
    id: "dictionary",
    label: "Dictionary"
  }, {
    id: "interface",
    label: "Interface"
  }, {
    id: "privacy",
    label: "Privacy"
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: "auto",
      padding: "20px 24px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "var(--font-serif)",
      fontSize: 18,
      fontWeight: 500,
      marginBottom: 16,
      color: "var(--text)"
    }
  }, "Settings"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 0,
      borderBottom: "1px solid var(--border-light)",
      marginBottom: 20
    }
  }, settingsTabs.map(t => /*#__PURE__*/React.createElement("button", {
    key: t.id,
    onClick: () => setTab(t.id),
    style: {
      padding: "8px 16px",
      border: "none",
      background: "transparent",
      fontSize: 13,
      fontWeight: tab === t.id ? 500 : 400,
      color: tab === t.id ? "var(--accent-red)" : "var(--text-secondary)",
      cursor: "pointer",
      borderBottom: `2px solid ${tab === t.id ? "var(--accent-red)" : "transparent"}`,
      fontFamily: "var(--font-ui)",
      transition: "color 0.15s"
    }
  }, t.label))), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 560
    }
  }, tab === "zotero" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "12px 14px",
      background: "oklch(93% 0.04 200)",
      border: "1px solid oklch(82% 0.07 200)",
      borderRadius: 8,
      display: "flex",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "info",
    size: 14,
    style: {
      color: "var(--accent-teal)",
      flexShrink: 0,
      marginTop: 1
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)",
      lineHeight: 1.55
    }
  }, "Get your API key from ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--accent-teal)"
    }
  }, "zotero.org/settings/keys"), ". Zotero integration lets you save papers directly to your library with one click.")), [{
    label: "API Key",
    value: zoteroKey,
    setter: setZoteroKey,
    type: "password"
  }, {
    label: "User ID",
    value: "1234567",
    setter: () => {},
    type: "text"
  }].map(({
    label,
    value,
    setter,
    type
  }) => /*#__PURE__*/React.createElement("div", {
    key: label
  }, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 12,
      fontWeight: 500,
      color: "var(--text-secondary)",
      display: "block",
      marginBottom: 6,
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, label), /*#__PURE__*/React.createElement("input", {
    type: type,
    value: value,
    onChange: e => setter(e.target.value),
    style: {
      width: "100%",
      padding: "8px 10px",
      border: "1px solid var(--border)",
      borderRadius: 6,
      fontSize: 12.5,
      color: "var(--text)",
      background: "var(--bg-panel)",
      fontFamily: "monospace",
      outline: "none"
    }
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: {
      fontSize: 12,
      fontWeight: 500,
      color: "var(--text-secondary)",
      display: "block",
      marginBottom: 6,
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, "Default Collection"), /*#__PURE__*/React.createElement("select", {
    style: {
      width: "100%",
      padding: "8px 10px",
      border: "1px solid var(--border)",
      borderRadius: 6,
      fontSize: 12.5,
      color: "var(--text)",
      background: "var(--bg-panel)",
      fontFamily: "var(--font-ui)",
      appearance: "none",
      outline: "none"
    }
  }, /*#__PURE__*/React.createElement("option", null, "My Library (root)"), /*#__PURE__*/React.createElement("option", null, "Research / Drug Discovery"), /*#__PURE__*/React.createElement("option", null, "Research / CRISPR"))), /*#__PURE__*/React.createElement("button", {
    style: {
      padding: "9px 0",
      background: "var(--accent-red)",
      color: "white",
      border: "none",
      borderRadius: 7,
      fontSize: 13,
      fontWeight: 500,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      width: "100%",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 6
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check",
    size: 14
  }), " Verify & Save")), tab === "dictionary" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-muted)",
      marginBottom: 14,
      lineHeight: 1.6
    }
  }, "Custom dictionary entries improve how queries are matched \u2014 abbreviations and local terms are expanded before the search runs."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 0,
      borderBottom: "1px solid var(--border-light)",
      marginBottom: 14
    }
  }, ["abbreviations", "synonyms", "stop expansions"].map(t => /*#__PURE__*/React.createElement("button", {
    key: t,
    onClick: () => setDictTab(t),
    style: {
      padding: "7px 14px",
      border: "none",
      background: "transparent",
      fontSize: 12,
      fontWeight: dictTab === t ? 500 : 400,
      color: dictTab === t ? "var(--accent-red)" : "var(--text-muted)",
      cursor: "pointer",
      borderBottom: `2px solid ${dictTab === t ? "var(--accent-red)" : "transparent"}`,
      fontFamily: "var(--font-ui)",
      textTransform: "capitalize"
    }
  }, t))), dictTab === "abbreviations" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)"
    }
  }, dictEntries.length, " entries"), /*#__PURE__*/React.createElement("button", {
    style: {
      fontSize: 12,
      padding: "5px 10px",
      background: "var(--accent-red)",
      color: "white",
      border: "none",
      borderRadius: 5,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      gap: 4
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plus",
    size: 12
  }), " Add Entry")), /*#__PURE__*/React.createElement("div", {
    style: {
      border: "1px solid var(--border)",
      borderRadius: 8,
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "120px 1fr 64px",
      background: "var(--bg)",
      padding: "7px 12px",
      borderBottom: "1px solid var(--border)"
    }
  }, ["Abbreviation", "Expansion", ""].map(h => /*#__PURE__*/React.createElement("span", {
    key: h,
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, h))), dictEntries.map((e, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "grid",
      gridTemplateColumns: "120px 1fr 64px",
      padding: "9px 12px",
      borderBottom: i < dictEntries.length - 1 ? "1px solid var(--border-light)" : "none",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      fontFamily: "monospace",
      fontWeight: 600,
      color: "var(--text)"
    }
  }, e.abbr), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)"
    }
  }, e.full), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 4
    }
  }, /*#__PURE__*/React.createElement("button", {
    style: {
      border: "none",
      background: "transparent",
      color: "var(--text-muted)",
      cursor: "pointer",
      padding: 3,
      borderRadius: 3,
      display: "flex"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "edit",
    size: 13
  })), /*#__PURE__*/React.createElement("button", {
    onClick: () => setDictEntries(dictEntries.filter((_, j) => j !== i)),
    style: {
      border: "none",
      background: "transparent",
      color: "var(--text-muted)",
      cursor: "pointer",
      padding: 3,
      borderRadius: 3,
      display: "flex"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "trash",
    size: 13
  }))))))), dictTab === "synonyms" && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px 0",
      textAlign: "center",
      color: "var(--text-muted)"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "book",
    size: 28,
    style: {
      marginBottom: 10,
      opacity: 0.3
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 13
    }
  }, "No synonyms defined yet.", /*#__PURE__*/React.createElement("br", null), "Add entries to improve query recall.")), dictTab === "stop expansions" && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px 0"
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)",
      marginBottom: 10,
      lineHeight: 1.6
    }
  }, "Terms the AI should ", /*#__PURE__*/React.createElement("em", null, "not"), " expand. Useful for acronyms like \"BC\" (province) or \"UBC\"."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: 6
    }
  }, ["BC", "UBC", "FIPPA"].map(term => /*#__PURE__*/React.createElement("div", {
    key: term,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 4,
      padding: "4px 8px",
      background: "var(--bg-panel)",
      border: "1px solid var(--border)",
      borderRadius: 5
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      fontFamily: "monospace",
      fontWeight: 600,
      color: "var(--text)"
    }
  }, term), /*#__PURE__*/React.createElement("button", {
    style: {
      border: "none",
      background: "transparent",
      color: "var(--text-muted)",
      cursor: "pointer",
      padding: 1,
      display: "flex"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "close",
    size: 11
  })))), /*#__PURE__*/React.createElement("button", {
    style: {
      padding: "4px 10px",
      background: "transparent",
      border: "1px dashed var(--border)",
      borderRadius: 5,
      fontSize: 12,
      color: "var(--text-muted)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      gap: 4
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plus",
    size: 11
  }), " Add"))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 14,
      display: "flex",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("button", {
    style: {
      flex: 1,
      padding: "7px 0",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 6,
      fontSize: 12,
      color: "var(--text-secondary)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 5
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "download",
    size: 13
  }), " Export JSON"), /*#__PURE__*/React.createElement("button", {
    style: {
      flex: 1,
      padding: "7px 0",
      background: "var(--accent-red)",
      color: "white",
      border: "none",
      borderRadius: 6,
      fontSize: 12,
      fontWeight: 500,
      cursor: "pointer",
      fontFamily: "var(--font-ui)"
    }
  }, "Save Dictionary"))), tab === "interface" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "10px 14px",
      background: "var(--bg)",
      border: "1px solid var(--border-light)",
      borderRadius: 8,
      display: "flex",
      gap: 10,
      alignItems: "flex-start"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "info",
    size: 14,
    style: {
      color: "var(--accent-teal)",
      flexShrink: 0,
      marginTop: 1
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12.5,
      color: "var(--text-secondary)",
      lineHeight: 1.55
    }
  }, "The search screen stays minimal by default \u2014 only the search box, results, and a status line. Turn features on as you need them. Toggles persist across reloads. ", /*#__PURE__*/React.createElement("strong", {
    style: {
      color: "var(--text)"
    }
  }, "Reliability signals"), " (demo-data banner, degraded notices, backend pill) are always shown and cannot be hidden.")), [{
    key: "advancedFiltersOpen",
    label: "Advanced filters row always open",
    desc: "Keep the year/type/access/sort filters expanded under the search box (default: collapsed to “Filters”)"
  }, {
    key: "savedHistoryNav",
    label: "Saved & History nav",
    desc: "Show the Saved Papers and History items in the sidebar (shown by default)"
  }, {
    key: "databasesTab",
    label: "Databases tab",
    desc: "Show the Duck Library databases browser in the sidebar (hidden by default)"
  }, {
    key: "analyticsApp",
    label: "About-index app (suite nav)",
    desc: "Show “About index” in the sidebar — the corpus-disclosures analytics app (hidden by default)"
  }, {
    key: "indexManagerApp",
    label: "Index Manager app (suite nav)",
    desc: "Show “Index” in the sidebar — personas/sections, warm cache, storage budget (hidden by default)"
  }, {
    key: "adminPanels",
    label: "Admin / operator panels",
    desc: "Show the Admin dashboard (models, curation, logs) — hidden by default for end users"
  }].map(({
    key,
    label,
    desc
  }) => {
    const on = !!(interfacePrefs && interfacePrefs[key]);
    return /*#__PURE__*/React.createElement("div", {
      key: key,
      style: {
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 12,
        padding: "10px 12px",
        background: "var(--bg-panel)",
        border: "1px solid var(--border-light)",
        borderRadius: 8
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 500,
        color: "var(--text)"
      }
    }, label), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11.5,
        color: "var(--text-muted)",
        marginTop: 2
      }
    }, desc)), /*#__PURE__*/React.createElement("button", {
      onClick: () => setInterfacePref(key, !on),
      "aria-pressed": on,
      role: "switch",
      style: {
        width: 38,
        height: 22,
        borderRadius: 11,
        background: on ? "var(--accent-red)" : "var(--border)",
        border: "none",
        cursor: "pointer",
        position: "relative",
        flexShrink: 0,
        transition: "background 0.2s"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 16,
        height: 16,
        borderRadius: "50%",
        background: "white",
        position: "absolute",
        top: 3,
        left: on ? 19 : 3,
        transition: "left 0.2s",
        boxShadow: "0 1px 3px rgba(0,0,0,0.2)"
      }
    })));
  }), (() => {
    const eff = !interfacePrefs || interfacePrefs.searchQueueAuto !== false ? !!sequential : !!(interfacePrefs && interfacePrefs.searchQueue);
    return /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 12,
        padding: "10px 12px",
        background: "var(--bg-panel)",
        border: "1px solid var(--border-light)",
        borderRadius: 8
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 13,
        fontWeight: 500,
        color: "var(--text)"
      }
    }, "Search queue"), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: 11.5,
        color: "var(--text-muted)",
        marginTop: 2
      }
    }, "Line up searches and run them one at a time \u2014 best when running from a USB drive. ", sequential ? "On automatically because this copy is in sequential (USB) mode." : "Off by default on fast local installs.")), /*#__PURE__*/React.createElement("button", {
      onClick: () => {
        setInterfacePref("searchQueueAuto", false);
        setInterfacePref("searchQueue", !eff);
      },
      "aria-pressed": eff,
      role: "switch",
      style: {
        width: 38,
        height: 22,
        borderRadius: 11,
        background: eff ? "var(--accent-red)" : "var(--border)",
        border: "none",
        cursor: "pointer",
        position: "relative",
        flexShrink: 0,
        transition: "background 0.2s"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: 16,
        height: 16,
        borderRadius: "50%",
        background: "white",
        position: "absolute",
        top: 3,
        left: eff ? 19 : 3,
        transition: "left 0.2s",
        boxShadow: "0 1px 3px rgba(0,0,0,0.2)"
      }
    })));
  })(), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      gap: 12,
      padding: "10px 12px",
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 8
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 500,
      color: "var(--text)"
    }
  }, "Density"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      marginTop: 2
    }
  }, "comfortable (default) adds breathing room; compact tightens result cards.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 4,
      background: "var(--bg)",
      borderRadius: 8,
      padding: 2
    }
  }, ["comfortable", "compact"].map(d => /*#__PURE__*/React.createElement("button", {
    key: d,
    onClick: () => setInterfacePref("density", d),
    style: {
      padding: "5px 12px",
      borderRadius: 6,
      border: "none",
      background: (interfacePrefs && interfacePrefs.density) === d ? "var(--accent-red)" : "transparent",
      color: (interfacePrefs && interfacePrefs.density) === d ? "white" : "var(--text-secondary)",
      fontSize: 12,
      fontWeight: 500,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      textTransform: "capitalize"
    }
  }, d))))), tab === "privacy" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 14
    }
  }, [{
    label: "Query Logging",
    desc: "Store search history locally for history/analytics",
    defaultOn: true
  }, {
    label: "Anonymous Usage Stats",
    desc: "Send anonymous query count to help improve the system",
    defaultOn: false
  }, {
    label: "SPECTER2 Reranking",
    desc: "Fetch embeddings from Semantic Scholar API",
    defaultOn: true
  }].map(({
    label,
    desc,
    defaultOn
  }) => /*#__PURE__*/React.createElement(PrivacyToggle, {
    key: label,
    label: label,
    desc: desc,
    defaultOn: defaultOn
  })))));
};
const AdminScreen = () => {
  const [tab, setTab] = React.useState("overview");
  const modelVersions = [{
    version: "v3",
    date: "2026-02-15",
    examples: 487,
    accuracy: "82%",
    status: "Active"
  }, {
    version: "v2",
    date: "2026-01-10",
    examples: 312,
    accuracy: "78%",
    status: "Archived"
  }, {
    version: "v1",
    date: "2025-12-01",
    examples: 200,
    accuracy: "71%",
    status: "Archived"
  }, {
    version: "base",
    date: "—",
    examples: "—",
    accuracy: "65%",
    status: "Fallback"
  }];
  const pendingQueries = [{
    q: "salmon habitat papers British Columbia",
    llm_out: '{"terms": ["salmon", "habitat", "British Columbia"], "type": "article"}',
    refined: "salmon habitat British Columbia"
  }, {
    q: "indigenous studies papers 2023",
    llm_out: '{"terms": ["indigenous", "studies"], "from_publication_date": "2023-01-01"}',
    refined: "indigenous studies 2023"
  }, {
    q: "open access remote sensing review",
    llm_out: '{"terms": ["remote", "sensing", "review"], "is_oa": true}',
    refined: "remote sensing review open access"
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: "auto",
      padding: "20px 24px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10,
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 28,
      height: 28,
      borderRadius: 6,
      background: "var(--accent-red)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "admin",
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
  }, "Admin Dashboard"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      color: "var(--text-muted)"
    }
  }, "Token protected \xB7 admin@ducklibrary.example"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 0,
      borderBottom: "1px solid var(--border-light)",
      marginBottom: 20
    }
  }, ["overview", "models", "curate", "logs"].map(t => /*#__PURE__*/React.createElement("button", {
    key: t,
    onClick: () => setTab(t),
    style: {
      padding: "8px 16px",
      border: "none",
      background: "transparent",
      fontSize: 13,
      fontWeight: tab === t ? 500 : 400,
      color: tab === t ? "var(--accent-red)" : "var(--text-secondary)",
      cursor: "pointer",
      borderBottom: `2px solid ${tab === t ? "var(--accent-red)" : "transparent"}`,
      fontFamily: "var(--font-ui)",
      textTransform: "capitalize",
      transition: "color 0.15s"
    }
  }, t))), tab === "overview" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: 10,
      marginBottom: 20
    }
  }, [{
    label: "Queries (30d)",
    value: "1,247",
    icon: "search",
    color: "var(--accent-red)"
  }, {
    label: "User Refinements",
    value: "312 (25%)",
    icon: "edit",
    color: "var(--accent-amber)"
  }, {
    label: "Est. Accuracy",
    value: "~75%",
    icon: "activity",
    color: "var(--accent-teal)"
  }, {
    label: "Avg Latency",
    value: "487ms",
    icon: "cpu",
    color: "oklch(52% 0.14 280)"
  }].map(({
    label,
    value,
    icon,
    color
  }) => /*#__PURE__*/React.createElement("div", {
    key: label,
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
  }, label), /*#__PURE__*/React.createElement(Icon, {
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
      fontVariantNumeric: "tabular-nums"
    }
  }, value)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 8,
      padding: "14px 16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em",
      marginBottom: 10
    }
  }, "Active Model"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 15,
      fontWeight: 600,
      color: "var(--text)",
      marginBottom: 4
    }
  }, "Semantic hybrid index"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-secondary)",
      marginBottom: 8
    }
  }, "Learned-sparse + dense retrieval \xB7 cross-encoder rerank"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      padding: "2px 8px",
      background: "oklch(93% 0.05 145)",
      color: "oklch(42% 0.14 145)",
      borderRadius: 4,
      fontWeight: 500
    }
  }, "82% accuracy"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      padding: "2px 8px",
      background: "var(--accent-teal-light)",
      color: "var(--accent-teal)",
      borderRadius: 4,
      fontWeight: 500
    }
  }, "Active"))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 8,
      padding: "14px 16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em",
      marginBottom: 10
    }
  }, "Improvement"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12.5,
      fontWeight: 500,
      color: "var(--text)",
      marginBottom: 2
    }
  }, "RAG Examples"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginBottom: 6
    }
  }, "234 curated pairs ready"), /*#__PURE__*/React.createElement("button", {
    style: {
      fontSize: 11,
      padding: "4px 10px",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 5,
      color: "var(--text-secondary)",
      cursor: "pointer",
      fontFamily: "var(--font-ui)"
    }
  }, "Review & Curate Queries")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12.5,
      fontWeight: 500,
      color: "var(--text)",
      marginBottom: 2
    }
  }, "Fine-Tune (requires GPU)"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginBottom: 6
    }
  }, "487 training examples available"), /*#__PURE__*/React.createElement("button", {
    style: {
      fontSize: 11,
      padding: "4px 10px",
      background: "var(--accent-red)",
      color: "white",
      border: "none",
      borderRadius: 5,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      fontWeight: 500
    }
  }, "Start Fine-Tune Job"))))), tab === "models" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 8,
      overflow: "hidden",
      marginBottom: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "80px 1fr 80px 80px 80px 100px",
      padding: "8px 14px",
      background: "var(--bg)",
      borderBottom: "1px solid var(--border)"
    }
  }, ["Version", "Date", "Examples", "Accuracy", "Status", "Actions"].map(h => /*#__PURE__*/React.createElement("span", {
    key: h,
    style: {
      fontSize: 11,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em"
    }
  }, h))), modelVersions.map((m, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "grid",
      gridTemplateColumns: "80px 1fr 80px 80px 80px 100px",
      padding: "10px 14px",
      borderBottom: i < modelVersions.length - 1 ? "1px solid var(--border-light)" : "none",
      alignItems: "center",
      background: m.status === "Active" ? "oklch(98% 0.008 145)" : "transparent"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 600,
      color: "var(--text)",
      fontFamily: "monospace"
    }
  }, m.version), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-secondary)"
    }
  }, m.date), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 12,
      color: "var(--text-secondary)"
    }
  }, m.examples), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 13,
      fontWeight: 600,
      color: m.status === "Active" ? "oklch(42% 0.14 145)" : "var(--text-secondary)"
    }
  }, m.accuracy), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 11,
      padding: "2px 7px",
      borderRadius: 4,
      background: m.status === "Active" ? "oklch(93% 0.05 145)" : m.status === "Fallback" ? "var(--accent-red-light)" : "var(--bg)",
      color: m.status === "Active" ? "oklch(42% 0.14 145)" : m.status === "Fallback" ? "var(--accent-red)" : "var(--text-muted)",
      fontWeight: 500,
      display: "inline-block"
    }
  }, m.status), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 4
    }
  }, m.status !== "Active" && /*#__PURE__*/React.createElement("button", {
    style: {
      fontSize: 10,
      padding: "2px 7px",
      background: "var(--accent-red-light)",
      color: "var(--accent-red)",
      border: "none",
      borderRadius: 4,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      fontWeight: 500
    }
  }, "Activate"), /*#__PURE__*/React.createElement("button", {
    style: {
      fontSize: 10,
      padding: "2px 7px",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 4,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      color: "var(--text-secondary)"
    }
  }, "Log"))))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 8,
      padding: "16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 500,
      color: "var(--text)",
      marginBottom: 10
    }
  }, "Schedule Fine-Tuning"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8,
      alignItems: "center",
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("select", {
    style: {
      flex: 1,
      padding: "7px 10px",
      border: "1px solid var(--border)",
      borderRadius: 6,
      fontSize: 12.5,
      color: "var(--text)",
      background: "var(--bg)",
      fontFamily: "var(--font-ui)",
      outline: "none"
    }
  }, /*#__PURE__*/React.createElement("option", null, "Every month"), /*#__PURE__*/React.createElement("option", null, "Every 2 weeks"), /*#__PURE__*/React.createElement("option", null, "Manual only")), /*#__PURE__*/React.createElement("button", {
    style: {
      padding: "7px 14px",
      background: "var(--accent-red)",
      color: "white",
      border: "none",
      borderRadius: 6,
      fontSize: 12.5,
      fontWeight: 500,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      whiteSpace: "nowrap"
    }
  }, "Run Now")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 11.5,
      color: "var(--text-muted)",
      lineHeight: 1.5
    }
  }, "Last run: ", /*#__PURE__*/React.createElement("strong", null, "2026-02-15"), " \xB7 accuracy 75% \u2192 82% \xB7 duration 52 min on A100"))), tab === "curate" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      marginBottom: 14
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 13,
      fontWeight: 500,
      color: "var(--text)"
    }
  }, "Query Curation"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)"
    }
  }, "23 / 156 pending reviewed")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("select", {
    style: {
      padding: "5px 10px",
      border: "1px solid var(--border)",
      borderRadius: 5,
      fontSize: 12,
      color: "var(--text)",
      background: "var(--bg-panel)",
      fontFamily: "var(--font-ui)",
      outline: "none"
    }
  }, /*#__PURE__*/React.createElement("option", null, "Refined only"), /*#__PURE__*/React.createElement("option", null, "All queries")), /*#__PURE__*/React.createElement("select", {
    style: {
      padding: "5px 10px",
      border: "1px solid var(--border)",
      borderRadius: 5,
      fontSize: 12,
      color: "var(--text)",
      background: "var(--bg-panel)",
      fontFamily: "var(--font-ui)",
      outline: "none"
    }
  }, /*#__PURE__*/React.createElement("option", null, "Last 7 days"), /*#__PURE__*/React.createElement("option", null, "Last 30 days")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 10
    }
  }, pendingQueries.map((pq, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      background: "var(--bg-panel)",
      border: "1px solid var(--border-light)",
      borderRadius: 8,
      padding: "14px 16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      color: "var(--text-muted)",
      marginBottom: 4
    }
  }, "User query"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 13,
      fontWeight: 500,
      color: "var(--text)",
      marginBottom: 8
    }
  }, "\"", pq.q, "\""), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 10,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em",
      marginBottom: 4
    }
  }, "LLM Output"), /*#__PURE__*/React.createElement("pre", {
    style: {
      fontSize: 11,
      background: "var(--bg)",
      padding: "6px 8px",
      borderRadius: 5,
      color: "var(--text-secondary)",
      overflowX: "auto",
      margin: 0,
      border: "1px solid var(--border)"
    }
  }, pq.llm_out)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 10,
      fontWeight: 600,
      color: "var(--text-muted)",
      textTransform: "uppercase",
      letterSpacing: "0.05em",
      marginBottom: 4
    }
  }, "User Refined To"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: 12,
      background: "oklch(93% 0.05 145)",
      padding: "6px 8px",
      borderRadius: 5,
      color: "oklch(32% 0.10 145)",
      border: "1px solid oklch(84% 0.07 145)",
      fontStyle: "italic"
    }
  }, "\"", pq.refined, "\""))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 6
    }
  }, /*#__PURE__*/React.createElement("button", {
    style: {
      flex: 1,
      padding: "6px 0",
      background: "oklch(93% 0.05 145)",
      color: "oklch(42% 0.14 145)",
      border: "1px solid oklch(84% 0.07 145)",
      borderRadius: 5,
      fontSize: 12,
      fontWeight: 500,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      gap: 4
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check",
    size: 12
  }), " Add to training"), /*#__PURE__*/React.createElement("button", {
    style: {
      flex: 1,
      padding: "6px 0",
      background: "var(--bg)",
      color: "var(--text-muted)",
      border: "1px solid var(--border)",
      borderRadius: 5,
      fontSize: 12,
      cursor: "pointer",
      fontFamily: "var(--font-ui)"
    }
  }, "Skip"), /*#__PURE__*/React.createElement("button", {
    style: {
      padding: "6px 12px",
      background: "var(--bg)",
      color: "var(--accent-amber)",
      border: "1px solid var(--accent-amber-light)",
      borderRadius: 5,
      fontSize: 12,
      cursor: "pointer",
      fontFamily: "var(--font-ui)",
      display: "flex",
      alignItems: "center",
      gap: 4
    }
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "warning",
    size: 12
  }), " Flag")))))), tab === "logs" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      background: "#0d1117",
      borderRadius: 8,
      padding: "14px 16px",
      fontFamily: "monospace",
      fontSize: 11.5,
      color: "#8b949e",
      lineHeight: 1.7,
      maxHeight: 480,
      overflow: "auto"
    }
  }, [{
    time: "14:41:02",
    level: "INFO",
    msg: "Query parsed: 'machine learning drug discovery' → {terms: ['machine learning', 'drug discovery'], material_type: 'article'}",
    color: "#8b949e"
  }, {
    time: "14:41:03",
    level: "INFO",
    msg: "OpenAlex: 50 results fetched in 312ms",
    color: "#8b949e"
  }, {
    time: "14:41:03",
    level: "INFO",
    msg: "Semantic Scholar: SPECTER2 embeddings batch 50/50 in 487ms",
    color: "#8b949e"
  }, {
    time: "14:41:03",
    level: "INFO",
    msg: "Access resolver: 12 OA, 23 Duck proxy, 8 Unpaywall, 7 DOI fallback",
    color: "#8b949e"
  }, {
    time: "14:41:03",
    level: "INFO",
    msg: "Reranker: NDCG@10 pipeline complete in 2ms",
    color: "#8b949e"
  }, {
    time: "14:41:04",
    level: "INFO",
    msg: "Returned 7 results to UI in 1.2s total",
    color: "#8b949e"
  }, {
    time: "11:08:15",
    level: "WARN",
    msg: "Semantic Scholar rate limit hit (1 req/s), backing off 1.2s",
    color: "#d29922"
  }, {
    time: "11:08:16",
    level: "INFO",
    msg: "Circuit breaker: semantic_scholar CLOSED (healthy)",
    color: "#8b949e"
  }, {
    time: "11:00:00",
    level: "INFO",
    msg: "Solr registry refreshed: 764 records cached (~198KB)",
    color: "#3fb950"
  }, {
    time: "10:45:33",
    level: "ERROR",
    msg: "Unpaywall: 10.1039/D3SC01234X not found — DOI fallback used",
    color: "#f85149"
  }].map((log, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "#484f58",
      flexShrink: 0
    }
  }, log.time), /*#__PURE__*/React.createElement("span", {
    style: {
      color: log.level === "ERROR" ? "#f85149" : log.level === "WARN" ? "#d29922" : "#3fb950",
      flexShrink: 0,
      width: 36
    }
  }, log.level), /*#__PURE__*/React.createElement("span", {
    style: {
      color: log.color
    }
  }, log.msg))))));
};
const App = () => {
  const [screen, setScreen] = React.useState("search");
  const [savedIds, setSavedIds] = React.useState(new Set());
  const [aiStatus, setAiStatus] = React.useState("online");
  const [serverSequential, setServerSequential] = React.useState(false);
  const [serverDraftStream, setServerDraftStream] = React.useState(false);
  React.useEffect(() => {
    let cancelled = false;
    if (window.SFUApi) {
      window.SFUApi.health().then(r => {
        if (cancelled) return;
        setAiStatus(r.source === "live" ? "online" : "offline");
        setServerSequential(!!r.sequential);
        setServerDraftStream(!!r.draftStream);
      });
    }
    return () => {
      cancelled = true;
    };
  }, []);
  React.useEffect(() => {
    const onMsg = e => {
      if (e.data && typeof e.data.suiteScreen === "string") setScreen(e.data.suiteScreen);
    };
    window.addEventListener("message", onMsg);
    if (window.parent !== window) window.parent.postMessage({
      suiteReady: "search"
    }, "*");
    return () => window.removeEventListener("message", onMsg);
  }, []);
  const [rerunReq, setRerunReq] = React.useState(null);
  const requestRerun = q => {
    setRerunReq({
      q,
      n: Date.now()
    });
    setScreen("search");
  };
  React.useEffect(() => {
    const onRerun = e => {
      if (e.detail && e.detail.q) requestRerun(e.detail.q);
    };
    window.addEventListener("sfu-history-rerun", onRerun);
    const pending = window.SFUHistory && window.SFUHistory.takePending();
    if (pending) requestRerun(pending);
    return () => window.removeEventListener("sfu-history-rerun", onRerun);
  }, []);
  const [interfacePrefs, setInterfacePref] = window.SFUUI && window.SFUUI.useInterfacePrefs ? window.SFUUI.useInterfacePrefs() : React.useState(window.SFUUI && window.SFUUI.readInterfacePrefs ? window.SFUUI.readInterfacePrefs() : {});
  const toggleSave = id => {
    setSavedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);else next.add(id);
      return next;
    });
  };
  const accent = {
    main: "oklch(52% 0.18 25)",
    light: "oklch(94% 0.04 25)",
    mid: "oklch(70% 0.10 25)"
  };
  const hiddenScreens = {};
  if (!interfacePrefs.savedHistoryNav) {
    hiddenScreens.saved = true;
    hiddenScreens.history = true;
  }
  if (!interfacePrefs.databasesTab) hiddenScreens.databases = true;
  if (!interfacePrefs.adminPanels) hiddenScreens.admin = true;
  if (hiddenScreens[screen]) {}
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, `
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        @keyframes sfu-skimmer { 0%, 100% { opacity: 0.55; } 50% { opacity: 0.9; } }
        :root {
          --accent-red: ${accent.main};
          --accent-red-light: ${accent.light};
          --accent-red-mid: ${accent.mid};
        }
      `), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      height: "100vh",
      overflow: "hidden"
    }
  }, /*#__PURE__*/React.createElement(SuiteSidebar, {
    app: "search",
    active: screen,
    onScreen: setScreen,
    hiddenScreens: hiddenScreens,
    interfacePrefs: interfacePrefs
  }), /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      display: "flex",
      flexDirection: "column",
      minWidth: 0,
      overflow: "hidden"
    }
  }, screen === "search" && /*#__PURE__*/React.createElement(SearchScreen, {
    savedIds: savedIds,
    toggleSave: toggleSave,
    setAiStatus: setAiStatus,
    interfacePrefs: interfacePrefs,
    sequential: serverSequential,
    draftStream: serverDraftStream,
    rerunReq: rerunReq,
    onRerunConsumed: () => setRerunReq(null)
  }), screen === "saved" && !hiddenScreens.saved && /*#__PURE__*/React.createElement(SavedScreen, {
    savedIds: savedIds,
    toggleSave: toggleSave
  }), screen === "history" && !hiddenScreens.history && /*#__PURE__*/React.createElement(HistoryScreen, {
    onRerun: requestRerun
  }), screen === "databases" && !hiddenScreens.databases && /*#__PURE__*/React.createElement(DatabasesScreen, null), screen === "settings" && /*#__PURE__*/React.createElement(SettingsScreen, {
    interfacePrefs: interfacePrefs,
    setInterfacePref: setInterfacePref,
    sequential: serverSequential
  }), screen === "admin" && !hiddenScreens.admin && /*#__PURE__*/React.createElement(AdminScreen, null), hiddenScreens[screen] && screen !== "search" && screen !== "settings" && /*#__PURE__*/React.createElement(SearchScreen, {
    savedIds: savedIds,
    toggleSave: toggleSave,
    setAiStatus: setAiStatus,
    interfacePrefs: interfacePrefs,
    sequential: serverSequential,
    draftStream: serverDraftStream,
    rerunReq: rerunReq,
    onRerunConsumed: () => setRerunReq(null)
  }))));
};
ReactDOM.createRoot(document.getElementById("root")).render(/*#__PURE__*/React.createElement(App, null));