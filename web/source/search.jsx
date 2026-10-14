const Icon = NIcon;


const AccessBadge = ({ access, compact = false }) => {
  const configs = {
    open_access:   { bg: "var(--accent-teal-light)", color: "var(--accent-teal)", label: compact ? "OA" : "Open Access" },
    unpaywall_oa:  { bg: "oklch(93% 0.05 145)", color: "oklch(42% 0.14 145)", label: compact ? "Free Copy" : "Free via Unpaywall" },
    sfu_proxy:     { bg: "var(--accent-red-light)", color: "var(--accent-red)", label: compact ? "Duck" : "Duck Library" },
    sfu_direct:    { bg: "var(--accent-red-light)", color: "var(--accent-red)", label: compact ? "Duck" : "Duck Library" },
    doi_fallback:  { bg: "oklch(93% 0.01 250)", color: "var(--text-muted)", label: compact ? "DOI" : "Check Access" },
  };
  const cfg = configs[access?.type] || configs.doi_fallback;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: compact ? "2px 6px" : "3px 8px", borderRadius: 4, background: cfg.bg, color: cfg.color, fontSize: compact ? 11 : 12, fontWeight: 500, letterSpacing: "0.02em", whiteSpace: "nowrap" }}>
      {cfg.label}
    </span>
  );
};


const CitationCount = ({ n }) => (
  <span style={{ color: "var(--text-muted)", fontSize: 12, display: "inline-flex", alignItems: "center", gap: 3 }}>
    <Icon name="link" size={11} />
    {n.toLocaleString()} citations
  </span>
);


const SearchBar = ({ query, setQuery, onSearch, loading, filters, setFilters, compact = false }) => {
  const [focused, setFocused] = React.useState(false);

  
  
  
  
  
  
  
  
  const specCtrl = React.useRef(null);
  if (specCtrl.current === null && typeof window !== "undefined" &&
      window.SFUApi && typeof window.SFUApi.createSpeculationController === "function") {
    specCtrl.current = window.SFUApi.createSpeculationController(
      window.SFUApi.speculate.bind(window.SFUApi), filters);
  }

  const handleKey = (e) => {
    if (e.key === "Enter") {
      
      if (specCtrl.current) specCtrl.current.cancel();
      onSearch();
    }
  };

  const handleChange = (val) => {
    setQuery(val);
    if (specCtrl.current) specCtrl.current.onType(val);
  };

  return (
    <div style={{ width: "100%" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 0, background: "var(--bg-panel)", border: `1.5px solid ${focused ? "var(--accent-red)" : "var(--border)"}`, borderRadius: compact ? 8 : 10, padding: compact ? "0 12px" : "0 14px", boxShadow: focused ? "0 0 0 3px var(--accent-red-light)" : "none", transition: "border-color 0.15s, box-shadow 0.15s" }}>
          <Icon name="search" size={16} style={{ color: focused ? "var(--accent-red)" : "var(--text-muted)", flexShrink: 0, transition: "color 0.15s" }} />
          <input
            value={query}
            onChange={e => handleChange(e.target.value)}
            onKeyDown={handleKey}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder="Search the library — try natural language…"
            style={{ flex: 1, minWidth: 0, width: "100%", border: "none", background: "transparent", outline: "none", padding: compact ? "9px 10px" : "12px 10px", fontSize: compact ? 13 : 15, color: "var(--text)", fontFamily: "var(--font-ui)" }}
          />
          {query && (
            <button onClick={() => handleChange("")} style={{ border: "none", background: "transparent", padding: 4, color: "var(--text-muted)", cursor: "pointer", borderRadius: 4, display: "flex", alignItems: "center" }}>
              <Icon name="close" size={14} />
            </button>
          )}
        </div>
        <button onClick={onSearch} disabled={loading} style={{ padding: compact ? "9px 16px" : "12px 20px", background: "var(--accent-red)", color: "white", border: "none", borderRadius: compact ? 8 : 10, fontSize: 13, fontWeight: 500, cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1, display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap", flexShrink: 0 }}>
          {loading ? <div style={{ width: 14, height: 14, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "white", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} /> : <Icon name="search" size={14} />}
          {compact ? "Search" : "Search"}
        </button>
      </div>

      {}
      {!compact && (
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          {[
            { key: "type", label: "Type", options: ["All", "Article", "Book", "Thesis", "Conference"] },
            { key: "date", label: "Date", options: ["Any time", "Last year", "Last 5 years", "Last 10 years"] },
            { key: "access", label: "Access", options: ["Any", "Open Access", "Duck Library", "Unpaywall"] },
            { key: "sort", label: "Sort", options: ["Relevance", "Most Recent", "Most Cited", "Title A–Z"] },
          ].map(f => (
            <div key={f.key} style={{ position: "relative" }}>
              <select
                value={filters[f.key] || f.options[0]}
                onChange={e => setFilters({ ...filters, [f.key]: e.target.value })}
                style={{ appearance: "none", background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 6, padding: "5px 24px 5px 10px", fontSize: 12, color: "var(--text)", cursor: "pointer", fontFamily: "var(--font-ui)" }}
              >
                {f.options.map(o => <option key={o}>{o}</option>)}
              </select>
              <Icon name="chevronDown" size={12} style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)", pointerEvents: "none" }} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};


const SOURCE_COVERS = {
  "Molecular Informatics":            { tone: "oklch(38% 0.12 265)", fg: "oklch(96% 0.02 80)", pub: "Wiley", motif: "grid" },
  "Drug Discovery Today":             { tone: "oklch(34% 0.10 25)",  fg: "oklch(96% 0.02 80)", pub: "Elsevier", motif: "bar" },
  "Nature Machine Intelligence":      { tone: "oklch(22% 0.018 250)", fg: "oklch(96% 0.02 80)", pub: "Springer Nature", motif: "rule" },
  "Journal of Chemical Information and Modeling": { tone: "oklch(40% 0.08 145)", fg: "oklch(96% 0.02 80)", pub: "ACS", motif: "diag" },
  "Science":                          { tone: "oklch(34% 0.13 30)",  fg: "oklch(96% 0.02 80)", pub: "AAAS", motif: "rule" },
  "ACS Central Science":              { tone: "oklch(45% 0.13 200)", fg: "oklch(96% 0.02 80)", pub: "ACS", motif: "grid" },
  "Nature Communications":            { tone: "oklch(28% 0.06 60)",  fg: "oklch(96% 0.02 80)", pub: "Springer Nature", motif: "bar" },
};

const SourceThumbnail = ({ result }) => {
  const cfg = SOURCE_COVERS[result.source] || { tone: "oklch(36% 0.04 250)", fg: "oklch(96% 0.02 80)", pub: "—", motif: "rule" };
  const titleAbbr = result.source
    .replace(/Journal of /i, "J. ")
    .replace(/and /gi, "& ");

  return (
    <div
      aria-hidden="true"
      style={{
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
        padding: "6px 5px 5px",
      }}
    >
      {}
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 3, background: "linear-gradient(to right, oklch(0% 0 0 / 0.18), transparent)" }} />

      {}
      <div style={{ fontSize: 5.5, fontFamily: "var(--font-ui)", letterSpacing: "0.12em", textTransform: "uppercase", opacity: 0.7, fontWeight: 500 }}>
        {cfg.pub}
      </div>

      {}
      <div style={{ fontSize: titleAbbr.length > 18 ? 8 : 9.5, fontWeight: 500, lineHeight: 1.05, marginTop: 3, textWrap: "balance" }}>
        {titleAbbr}
      </div>

      {}
      <div style={{ flex: 1, marginTop: 4, position: "relative", opacity: 0.55 }}>
        {cfg.motif === "grid" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 1.5, height: "100%" }}>
            {Array.from({ length: 9 }).map((_, i) => (
              <div key={i} style={{ background: cfg.fg, opacity: 0.10 + (i % 3) * 0.08, borderRadius: 1 }} />
            ))}
          </div>
        )}
        {cfg.motif === "bar" && (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 1.5, height: "100%" }}>
            {[0.4, 0.7, 0.55, 0.85, 0.3, 0.6, 0.45].map((h, i) => (
              <div key={i} style={{ flex: 1, height: `${h * 100}%`, background: cfg.fg, opacity: 0.45, borderRadius: 0.5 }} />
            ))}
          </div>
        )}
        {cfg.motif === "rule" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 2 }}>
            {[100, 80, 60, 90, 70].map((w, i) => (
              <div key={i} style={{ height: 1, width: `${w}%`, background: cfg.fg, opacity: 0.35 }} />
            ))}
          </div>
        )}
        {cfg.motif === "diag" && (
          <div style={{ height: "100%", background: `repeating-linear-gradient(45deg, transparent 0 4px, ${cfg.fg.replace(")", " / 0.18)")} 4px 5px)` }} />
        )}
      </div>

      {}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", fontSize: 6, fontFamily: "var(--font-ui)", letterSpacing: "0.06em", opacity: 0.85, fontWeight: 500, marginTop: 3 }}>
        <span>VOL {result.volume}</span>
        <span>{result.year}</span>
      </div>
    </div>
  );
};


window.__sfuResults = window.__sfuResults || {};

const engage = (fn, ...args) => {
  try {
    const e = window.SFUApi && window.SFUApi.engagement;
    if (e && typeof e[fn] === "function") return e[fn](...args);
  } catch (err) {  }
  return false;
};

const ResultCard = ({ result, index, onClick, saved, onSave, preliminary, onHover }) => {
  const [copied, setCopied] = React.useState(null);
  React.useEffect(() => { window.__sfuResults[result.id] = result; }, [result]);

  const handleCopy = (format, e) => {
    e.stopPropagation();
    engage("action", result, "citation");
    const citations = {
      APA: `${result.authors.join(", ")} (${result.year}). ${result.title}. *${result.source}*, *${result.volume}*(${result.issue}). https://doi.org/${result.doi}`,
      MLA: `${result.authors[0]} et al. "${result.title}." *${result.source}* ${result.volume}.${result.issue} (${result.year}).`,
      BibTeX: `@article{${result.id},\n  title={${result.title}},\n  author={${result.authors.join(" and ")}},\n  journal={${result.source}},\n  year={${result.year}}\n}`,
    };
    setCopied(format);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <div
      onClick={() => onClick(result)}
      style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 10, padding: "16px 18px", marginBottom: 8, cursor: "pointer", transition: "border-color 0.15s, box-shadow 0.15s" }}
      data-result-id={result.id}
      onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.boxShadow = "var(--shadow-sm)"; if (onHover) onHover(result.id); }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border-light)"; e.currentTarget.style.boxShadow = "none"; if (onHover) onHover(null); }}
    >
      <div style={{ display: "flex", gap: 14 }}>
        {}
        <div style={{ width: 22, flexShrink: 0, color: "var(--text-muted)", fontSize: 12, paddingTop: 3, textAlign: "right" }}>{index}.</div>

        {}
        <SourceThumbnail result={result} />

        {}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 4 }}>
            <h3 style={{ fontFamily: "var(--font-serif)", fontSize: 15, fontWeight: 500, color: "var(--text)", lineHeight: 1.4, margin: 0, flex: 1, textWrap: "pretty" }}>
              {preliminary && (
                <span data-testid="sfu-preliminary-badge" style={{ fontFamily: "var(--font-ui)", fontSize: 10.5, fontWeight: 600, letterSpacing: 0.2, textTransform: "uppercase", padding: "1px 6px", marginRight: 7, borderRadius: 4, background: "var(--accent-amber-light)", color: "var(--text-secondary)", border: "1px solid var(--border)", verticalAlign: "2px" }}>Preliminary</span>
              )}
              {result.title}
            </h3>
            <button onClick={e => { e.stopPropagation(); if (!saved) engage("action", result, "save"); onSave(result.id); }} data-testid="sfu-card-save" style={{ border: "none", background: "transparent", color: saved ? "var(--accent-red)" : "var(--text-muted)", cursor: "pointer", padding: 4, flexShrink: 0, display: "flex", borderRadius: 4, transition: "color 0.15s" }}>
              <Icon name="bookmark" size={14} style={{ fill: saved ? "var(--accent-red)" : "none" }} />
            </button>
          </div>

          {}
          <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 6, lineHeight: 1.4 }}>
            {result.authors.slice(0, 3).join(", ")}{result.authors.length > 3 ? " et al." : ""} · {result.source} · {result.year}
            {result.volume ? ` · Vol. ${result.volume}` : ""}
          </p>

          {}
          {result.tldr && (
            <p style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 8, lineHeight: 1.55, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
              {result.tldr}
            </p>
          )}

          {}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <AccessBadge access={result.access} compact />
            <CitationCount n={result.cited_by} />

            <div style={{ marginLeft: "auto", display: "flex", gap: 4, flexShrink: 0 }} onClick={e => e.stopPropagation()}>
              {["APA", "MLA", "BibTeX"].map(fmt => (
                <button key={fmt} onClick={e => handleCopy(fmt, e)} style={{ fontSize: 11, padding: "3px 7px", border: "1px solid var(--border)", borderRadius: 4, background: copied === fmt ? "var(--accent-teal-light)" : "var(--bg)", color: copied === fmt ? "var(--accent-teal)" : "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", gap: 3, transition: "all 0.15s" }}>
                  {copied === fmt ? <Icon name="check" size={10} /> : <Icon name="copy" size={10} />}
                  {fmt}
                </button>
              ))}
              <button onClick={e => e.stopPropagation()} style={{ fontSize: 11, padding: "3px 7px", border: "1px solid var(--border)", borderRadius: 4, background: "var(--bg)", color: "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", gap: 3 }}>
                <Icon name="zotero" size={10} />
                Zotero
              </button>
              <a href={result.doi ? `https://doi.org/${result.doi}` : "#"} target="_blank" rel="noopener noreferrer" onClick={e => { e.stopPropagation(); engage("action", result, "pdf"); }} data-testid="sfu-card-access" style={{ fontSize: 11, padding: "3px 7px", border: "1px solid var(--border)", borderRadius: 4, background: "var(--bg)", color: "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", gap: 3, textDecoration: "none" }}>
                <Icon name="externalLink" size={10} />
                {result.access?.type === "open_access" ? "PDF" : "Access"}
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};


const SkeletonResultCard = ({ index }) => (
  <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 10, padding: "16px 18px", marginBottom: 8, height: 110 }} data-skeleton-card>
    <div style={{ display: "flex", gap: 14 }}>
      <div style={{ width: 22, flexShrink: 0, paddingTop: 3 }} />
      <div style={{ width: 64, height: 86, flexShrink: 0, borderRadius: 3, background: "var(--border)", animation: "sfu-skimmer 1.4s ease infinite" }} />
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 7, paddingTop: 2 }}>
        <div style={{ height: 14, background: "var(--border)", borderRadius: 3, width: "75%", animation: "sfu-skimmer 1.4s ease infinite" }} />
        <div style={{ height: 10, background: "var(--border)", borderRadius: 3, width: "50%", animation: "sfu-skimmer 1.4s ease infinite" }} />
        <div style={{ height: 10, background: "var(--border)", borderRadius: 3, width: "90%", animation: "sfu-skimmer 1.4s ease infinite" }} />
      </div>
    </div>
  </div>
);


const FiltersExpander = ({ filters, setFilters, alwaysOpen }) => {
  const [open, setOpen] = React.useState(!!alwaysOpen);
  React.useEffect(() => { setOpen(!!alwaysOpen); }, [alwaysOpen]);
  const filterDefs = [
    { key: "type", label: "Type", options: ["All", "Article", "Book", "Thesis", "Conference"] },
    { key: "date", label: "Date", options: ["Any time", "Last year", "Last 5 years", "Last 10 years"] },
    { key: "access", label: "Access", options: ["Any", "Open Access", "Duck Library", "Unpaywall"] },
    { key: "sort", label: "Sort", options: ["Relevance", "Most Recent", "Most Cited", "Title A–Z"] },
  ];
  return (
    <div style={{ marginTop: 8 }}>
      <button onClick={() => setOpen(o => !o)} aria-expanded={open}
        style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 2px", border: "none", background: "transparent", color: "var(--text-secondary)", fontSize: 12, fontWeight: 500, cursor: "pointer", fontFamily: "var(--font-ui)" }}>
        <Icon name="filter" size={13} />
        {open ? "Hide filters" : "Filters"}
        <Icon name={open ? "chevronDown" : "chevronRight"} size={12} />
      </button>
      {open && (
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          {filterDefs.map(f => (
            <div key={f.key} style={{ position: "relative" }}>
              <select value={filters[f.key] || f.options[0]} onChange={e => setFilters({ ...filters, [f.key]: e.target.value })}
                style={{ appearance: "none", background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 6, padding: "5px 24px 5px 10px", fontSize: 12, color: "var(--text)", cursor: "pointer", fontFamily: "var(--font-ui)" }}>
                {f.options.map(o => <option key={o}>{o}</option>)}
              </select>
              <Icon name="chevronDown" size={12} style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)", pointerEvents: "none" }} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};


const ResultDetail = ({ result, onClose, saved, onSave }) => {
  const [activeTab, setActiveTab] = React.useState("abstract");
  const [copied, setCopied] = React.useState(null);

  if (!result) return null;

  const citationFormats = {
    APA: `${result.authors.join(", ")} (${result.year}). ${result.title}. *${result.source}*, *${result.volume}*(${result.issue}). https://doi.org/${result.doi}`,
    MLA: `${result.authors[0]} et al. "${result.title}." *${result.source}* ${result.volume}.${result.issue} (${result.year}).`,
    Chicago: `${result.authors.join(", ")}. "${result.title}." *${result.source}* ${result.volume}, no. ${result.issue} (${result.year}).`,
    BibTeX: `@article{${result.id},\n  title     = {${result.title}},\n  author    = {${result.authors.join(" and ")}},\n  journal   = {${result.source}},\n  volume    = {${result.volume}},\n  number    = {${result.issue}},\n  year      = {${result.year}},\n  doi       = {${result.doi}}\n}`,
  };

  return (
    <div style={{ width: 400, borderLeft: "1px solid var(--border)", background: "var(--bg-panel)", display: "flex", flexDirection: "column", height: "100%", flexShrink: 0 }}>
      {}
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border-light)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text-secondary)" }}>Paper Details</span>
        <button onClick={onClose} style={{ border: "none", background: "transparent", cursor: "pointer", color: "var(--text-muted)", padding: 4, borderRadius: 4, display: "flex" }}>
          <Icon name="close" size={14} />
        </button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "16px" }}>
        {}
        <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 16, fontWeight: 500, lineHeight: 1.45, color: "var(--text)", marginBottom: 10, textWrap: "pretty" }}>
          {result.title}
        </h2>

        {}
        <p style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 10, lineHeight: 1.5 }}>
          {result.authors.join(", ")}
        </p>

        {}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 16px", marginBottom: 14, padding: "10px 12px", background: "var(--bg)", borderRadius: 7 }}>
          {[
            { label: "Journal", value: result.source },
            { label: "Year", value: result.year },
            { label: "Volume", value: `${result.volume} (${result.issue})` },
            { label: "Citations", value: result.cited_by.toLocaleString() },
            { label: "Type", value: result.type },
            { label: "DOI", value: result.doi.slice(0, 24) + "…" },
          ].map(({ label, value }) => (
            <div key={label}>
              <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2 }}>{label}</div>
              <div style={{ fontSize: 12, color: "var(--text)", fontWeight: 500 }}>{value}</div>
            </div>
          ))}
        </div>

        {}
        <div style={{ padding: "10px 12px", borderRadius: 7, background: result.access?.type === "open_access" ? "var(--accent-teal-light)" : result.access?.type.startsWith("sfu") ? "var(--accent-red-light)" : "var(--bg)", marginBottom: 14, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: result.access?.type === "open_access" ? "var(--accent-teal)" : result.access?.type.startsWith("sfu") ? "var(--accent-red)" : "var(--text-muted)", marginBottom: 2 }}>
              {result.access?.type === "open_access" ? "Open Access" : result.access?.type === "unpaywall_oa" ? "Free Copy Available" : result.access?.type.startsWith("sfu") ? "Duck Library Access" : "Limited Access"}
            </div>
            <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>{result.access?.label}</div>
          </div>
          <a href={result.doi ? `https://doi.org/${result.doi}` : "#"} target="_blank" rel="noopener noreferrer" onClick={() => engage("action", result, "pdf")} style={{ fontSize: 11, padding: "5px 10px", background: "white", border: "none", borderRadius: 5, color: "var(--accent-red)", fontWeight: 600, cursor: "pointer", textDecoration: "none", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", gap: 4 }}>
            <Icon name="externalLink" size={11} />
            Open
          </a>
        </div>

        {}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 14 }}>
          {result.topics?.map(t => (
            <span key={t} style={{ fontSize: 11, padding: "3px 8px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 4, color: "var(--text-secondary)" }}>{t}</span>
          ))}
        </div>

        {}
        <div style={{ display: "flex", borderBottom: "1px solid var(--border-light)", marginBottom: 12 }}>
          {["abstract", "citations", "export"].map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)} style={{ flex: 1, padding: "7px 0", border: "none", background: "transparent", fontSize: 12, fontWeight: activeTab === tab ? 500 : 400, color: activeTab === tab ? "var(--accent-red)" : "var(--text-muted)", cursor: "pointer", borderBottom: `2px solid ${activeTab === tab ? "var(--accent-red)" : "transparent"}`, transition: "color 0.15s", fontFamily: "var(--font-ui)", textTransform: "capitalize" }}>
              {tab}
            </button>
          ))}
        </div>

        {activeTab === "abstract" && (
          <div>
            {result.tldr && (
              <div style={{ padding: "8px 10px", background: "var(--accent-red-light)", borderRadius: 6, marginBottom: 10 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--accent-red)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>AI Summary (TLDR)</div>
                <p style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.5 }}>{result.tldr}</p>
              </div>
            )}
            <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.65 }}>{result.abstract}</p>
          </div>
        )}

        {activeTab === "citations" && (
          <div>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 10 }}>Cited by {result.cited_by.toLocaleString()} works via Semantic Scholar</p>
            {[1, 2, 3].map(i => (
              <div key={i} style={{ padding: "10px 0", borderBottom: "1px solid var(--border-light)" }}>
                <p style={{ fontSize: 12, fontFamily: "var(--font-serif)", color: "var(--text)", lineHeight: 1.4, marginBottom: 4 }}>Related paper title {i} citing this work in the context of drug discovery</p>
                <p style={{ fontSize: 11, color: "var(--text-muted)" }}>Author et al. · Journal · 202{i + 2}</p>
              </div>
            ))}
            <button style={{ marginTop: 10, fontSize: 12, color: "var(--accent-red)", background: "transparent", border: "none", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", gap: 4 }}>
              View all on Semantic Scholar <Icon name="externalLink" size={12} />
            </button>
          </div>
        )}

        {activeTab === "export" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {Object.entries(citationFormats).map(([fmt, text]) => (
              <div key={fmt} style={{ border: "1px solid var(--border)", borderRadius: 7, overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 10px", background: "var(--bg)", borderBottom: "1px solid var(--border)" }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary)", letterSpacing: "0.04em" }}>{fmt}</span>
                  <button onClick={() => { engage("action", result, "citation"); setCopied(fmt); }} style={{ fontSize: 10, padding: "2px 8px", background: copied === fmt ? "var(--accent-teal-light)" : "white", color: copied === fmt ? "var(--accent-teal)" : "var(--text-secondary)", border: "1px solid var(--border)", borderRadius: 4, cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", gap: 3 }}>
                    {copied === fmt ? <><Icon name="check" size={10} /> Copied</> : <><Icon name="copy" size={10} /> Copy</>}
                  </button>
                </div>
                <div style={{ padding: "8px 10px", fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.6, fontFamily: fmt === "BibTeX" ? "monospace" : "var(--font-ui)", whiteSpace: "pre-wrap", maxHeight: 80, overflow: "auto" }}>
                  {text}
                </div>
              </div>
            ))}
            <button style={{ marginTop: 4, padding: "8px 0", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 7, fontSize: 12, color: "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", justifyContent: "center", gap: 6, width: "100%" }}>
              <Icon name="zotero" size={13} />
              Save all to Zotero…
            </button>
          </div>
        )}
      </div>

      {}
      <div style={{ borderTop: "1px solid var(--border-light)", padding: "12px 16px", display: "flex", gap: 8 }}>
        <button onClick={() => { if (!saved) engage("action", result, "save"); onSave(result.id); }} style={{ flex: 1, padding: "7px 0", background: saved ? "var(--accent-red-light)" : "var(--bg)", border: `1px solid ${saved ? "var(--accent-red-mid)" : "var(--border)"}`, borderRadius: 6, fontSize: 12, color: saved ? "var(--accent-red)" : "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", justifyContent: "center", gap: 5 }}>
          <Icon name="bookmark" size={13} style={{ fill: saved ? "var(--accent-red)" : "none" }} />
          {saved ? "Saved" : "Save"}
        </button>
        <button style={{ flex: 1, padding: "7px 0", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12, color: "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", justifyContent: "center", gap: 5 }}>
          <Icon name="zotero" size={13} />
          Zotero
        </button>
        <a href={result.doi ? `https://doi.org/${result.doi}` : "#"} target="_blank" rel="noopener noreferrer" onClick={() => engage("action", result, "pdf")} style={{ flex: 1, padding: "7px 0", background: "var(--accent-red)", border: "none", borderRadius: 6, fontSize: 12, color: "white", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", justifyContent: "center", gap: 5, textDecoration: "none", fontWeight: 500 }}>
          <Icon name="externalLink" size={13} />
          Access
        </a>
      </div>
    </div>
  );
};


const PROV_SUBJECTS = ["Natural Sciences", "Health & Medicine", "Social Sciences", "Engineering & CS", "Arts & Humanities"];
const PROV_ERAS = ["pre-2010", "2010–present"];
const provKey = (s, e) => s + "|" + e;

const EnginePill = ({ label, ok }) => (
  <span style={{
    display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 9px", borderRadius: 5,
    fontSize: 11.5, fontWeight: 500, whiteSpace: "nowrap",
    background: ok ? "var(--accent-teal-light)" : "var(--accent-red-light)",
    color: ok ? "var(--accent-teal)" : "var(--accent-red)",
    border: "1px solid " + (ok ? "transparent" : "var(--accent-red)"),
  }}>
    <Icon name={ok ? "check" : "close"} size={11} />
    {label}
  </span>
);

const ProvRow = ({ tone = "neutral", icon, title, children, muted = false }) => {
  const tones = {
    warn:    { bg: "var(--accent-amber-light)", ic: "oklch(52% 0.13 75)" },
    alert:   { bg: "var(--accent-red-light)",   ic: "var(--accent-red)" },
    ok:      { bg: "var(--accent-teal-light)",  ic: "var(--accent-teal)" },
    neutral: { bg: "var(--bg)",                 ic: "var(--text-muted)" },
  };
  const t = tones[tone];
  return (
    <div style={{ display: "flex", gap: 12, padding: muted ? "11px 0 2px" : "14px 0", borderTop: "1px solid var(--border-light)" }}>
      <span style={{ width: 26, height: 26, borderRadius: 7, background: t.bg, color: t.ic, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, marginTop: 1 }}>
        <Icon name={icon} size={muted ? 13 : 15} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: muted ? 12 : 13.5, fontWeight: 600, color: muted ? "var(--text-secondary)" : "var(--text)", marginBottom: 3 }}>{title}</div>
        <div style={{ fontSize: muted ? 11.5 : 12.5, color: muted ? "var(--text-muted)" : "var(--text-secondary)", lineHeight: 1.55 }}>{children}</div>
      </div>
    </div>
  );
};

const ProvAction = ({ icon, children, onClick, busy }) => (
  <button onClick={onClick} disabled={busy} style={{
    display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 11px", borderRadius: 6,
    border: "1px solid var(--accent-red)", background: "var(--bg-panel)", color: "var(--accent-red)",
    fontSize: 12, fontWeight: 500, cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1,
  }}
  onMouseEnter={e => { if (!busy) e.currentTarget.style.background = "var(--accent-red-light)"; }}
  onMouseLeave={e => { e.currentTarget.style.background = "var(--bg-panel)"; }}>
    <Icon name={icon} size={13} />
    {children}
  </button>
);

const SearchProvenanceCard = ({ degraded }) => {
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
    PROV_SUBJECTS.forEach(s => { if (n.has(provKey(s, "2010–present"))) n.add(provKey(s, "pre-2010")); });
    return n;
  });
  const addSubject = (s) => { setSearched(prev => new Set(prev).add(provKey(s, "2010–present"))); setProfileOpen(false); };

  const goAbout = () => { if (window.parent !== window) window.parent.postMessage({ suiteNav: "analytics" }, "*"); else window.location.href = "Research Analytics.html"; };

  const sev = degraded ? { color: "var(--accent-red)", bg: "var(--accent-red-light)" }
            : full ? { color: "var(--accent-teal)", bg: "var(--accent-teal-light)" }
            : { color: "oklch(52% 0.13 75)", bg: "var(--accent-amber-light)" };

  return (
    <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 10, marginBottom: 16, boxShadow: "var(--shadow-sm)", overflow: "hidden" }} data-comment-anchor="search-provenance">
      {}
      <button onClick={() => setOpen(!open)} style={{ width: "100%", display: "flex", alignItems: "center", gap: 11, padding: "12px 16px", border: "none", background: "transparent", textAlign: "left" }}>
        <span style={{ width: 28, height: 28, borderRadius: 8, background: sev.bg, color: sev.color, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <Icon name={degraded ? "warning" : full ? "check" : "info"} size={16} />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 600 }}>
            What this search covered
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 1 }}>
            Read <strong style={{ color: sev.color }}>{count} of {total}</strong> index sections
            {degraded ? " · 1 engine unavailable" : full ? " · full index" : " · partial coverage"}
          </div>
        </div>
        <span style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          {open ? "Hide" : "Details"}
          <Icon name={open ? "chevronDown" : "chevronRight"} size={14} />
        </span>
      </button>

      {open && (
        <div style={{ padding: "0 16px 16px" }}>
          {}
          {degraded && (
            <div style={{ display: "flex", gap: 10, padding: "11px 13px", background: "var(--accent-red-light)", borderRadius: 8, borderLeft: "3px solid var(--accent-red)", marginBottom: 4 }}>
              <Icon name="warning" size={15} style={{ color: "var(--accent-red)", flexShrink: 0, marginTop: 1 }} />
              <div style={{ fontSize: 12.5, color: "var(--text)", lineHeight: 1.5 }}>
                <strong style={{ fontWeight: 600 }}>The semantic-sparse engine (SPLADE) was unavailable for this query.</strong> Results came from keyword and dense matching only — a paper that matches your topic in meaning but not in exact wording may be missing. Re-run later for the full mix.
              </div>
            </div>
          )}

          {}
          {degraded && (
            <ProvRow tone="alert" icon="cpu" title="Which engines ran">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6, marginBottom: 6 }}>
                <EnginePill label="Keyword" ok={true} />
                <EnginePill label="Semantic-sparse (SPLADE)" ok={false} />
                <EnginePill label="Semantic-dense" ok={true} />
              </div>
              Results were fused from 2 of 3 engines with Reciprocal Rank Fusion (k = 60), which weights each engine equally.
            </ProvRow>
          )}

          {}
          <ProvRow tone={full ? "ok" : "warn"} icon="server" title={full ? "Full index searched" : "Most of the index was not searched"}>
            {full
              ? "Every section was unpacked and searched, across all five disciplines and both eras. This is now a complete view of the index."
              : <>Your query was routed to a single section — <strong style={{ color: "var(--text)" }}>Social Sciences · 2010–present</strong>. The other {total - count} sections stayed in cold storage or were pruned by your date filter, including <strong style={{ color: "var(--text)" }}>Arts &amp; Humanities</strong>, where much of this literature sits, and everything published before 2010.</>}

            {}
            <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "118px 1fr 1fr", gap: 5, alignItems: "center" }}>
              <span />
              {PROV_ERAS.map(e => <span key={e} style={{ fontSize: 10.5, color: "var(--text-muted)", textAlign: "center", letterSpacing: "0.03em" }}>{e}</span>)}
              {PROV_SUBJECTS.map(s => (
                <React.Fragment key={s}>
                  <span style={{ fontSize: 11.5, color: "var(--text-secondary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s}</span>
                  {PROV_ERAS.map(e => {
                    const on = isOn(s, e);
                    return (
                      <div key={e} style={{
                        height: 28, borderRadius: 5, display: "flex", alignItems: "center", justifyContent: "center", gap: 4,
                        fontSize: 10.5, fontWeight: 500,
                        background: on ? "var(--accent-teal-light)" : "var(--bg)",
                        border: on ? "1px solid var(--accent-teal)" : "1px dashed var(--border)",
                        color: on ? "var(--accent-teal)" : "var(--text-muted)",
                      }}>
                        {on ? <><Icon name="check" size={11} /> searched</> : "cold"}
                      </div>
                    );
                  })}
                </React.Fragment>
              ))}
            </div>

            {}
            {!full && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 13, position: "relative" }}>
                <ProvAction icon="server" onClick={widen} busy={unpacking}>
                  {unpacking ? "Unpacking sections…" : "Widen search — unpack cold sections"}
                </ProvAction>
                {eraPruned && (
                  <ProvAction icon="history" onClick={removeDate}>Remove date filter (pre-2010)</ProvAction>
                )}
                {missingSubjects.length > 0 && (
                  <div style={{ position: "relative" }}>
                    <ProvAction icon="filter" onClick={() => setProfileOpen(o => !o)}>Switch subject profile</ProvAction>
                    {profileOpen && (
                      <div style={{ position: "absolute", top: "calc(100% + 4px)", left: 0, zIndex: 5, background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 8, boxShadow: "var(--shadow-md)", padding: 4, minWidth: 180 }}>
                        {missingSubjects.map(s => (
                          <button key={s} onClick={() => addSubject(s)} style={{ display: "block", width: "100%", textAlign: "left", padding: "7px 10px", border: "none", background: "transparent", borderRadius: 5, fontSize: 12.5, color: "var(--text)" }}
                            onMouseEnter={e => e.currentTarget.style.background = "var(--bg)"}
                            onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                            Add {s}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </ProvRow>

          {}
          <ProvRow tone="warn" icon="info" title="Tuned for English">
            Matching favours English. Scholarship written in other languages — including Indigenous-language and non-English-venue work — ranks lower or is missed entirely, because the semantic model and the section vocabularies are English-only.
          </ProvRow>

          {}
          <ProvRow tone="warn" icon="history" title="Recent work is favoured by default">
            Your profile defaults to recent material (2010 onward) and the ranker adds a small recency boost. Foundational and historical work is under-represented unless you remove the date filter above.
          </ProvRow>

          {}
          {!degraded && (
            <ProvRow tone="ok" icon="cpu" title="Which engines ran">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6, marginBottom: 6 }}>
                <EnginePill label="Keyword" ok={true} />
                <EnginePill label="Semantic-sparse (SPLADE)" ok={true} />
                <EnginePill label="Semantic-dense" ok={true} />
              </div>
              All three engines ran and were fused with Reciprocal Rank Fusion (k = 60), which weights each engine equally — a result strong in only one method can be pushed down by the others.
            </ProvRow>
          )}

          {}
          <ProvRow tone="neutral" icon="book" title="Open access & missing abstracts">
            About <strong style={{ color: "var(--text)" }}>38%</strong> of these results are open access. A handful were missing abstracts (the source metadata failed to load) and may rank lower, since the ranker rewards records with complete text to judge.
          </ProvRow>

          {}
          <ProvRow tone="neutral" icon="search" title="Keyword matching is literal">
            The keyword engine does not match word variants or spellings on its own — "labour" ≠ "labor", "fisheries" ≠ "fishing". If results look thin, try alternate forms and spellings.
          </ProvRow>

          {}
          <ProvRow tone="neutral" icon="cpu" title="Speed trade-offs" muted={true}>
            For speed, very long queries are compressed to their most important terms and a small number of borderline matches may be dropped. Measured impact on recall is minor.
          </ProvRow>

          {}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border-light)" }}>
            <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-ui)" }}>
              Fields from <code style={{ fontFamily: "ui-monospace, monospace", fontSize: 10.5, background: "var(--bg)", padding: "1px 5px", borderRadius: 3, border: "1px solid var(--border-light)" }}>get_search_provenance</code> · index of 150,413,098 documents
            </span>
            <button onClick={goAbout} style={{ display: "inline-flex", alignItems: "center", gap: 5, border: "none", background: "transparent", color: "var(--accent-red)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
              About this index <Icon name="chevronRight" size={13} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};


const SequentialBanner = () => (
  <div style={{ padding: "10px 13px", background: "var(--accent-teal-light)", borderRadius: 8, borderLeft: "3px solid var(--accent-teal)", marginBottom: 12, fontSize: 12.5, color: "var(--text)", lineHeight: 1.5, display: "flex", gap: 8, alignItems: "flex-start" }} role="status">
    <Icon name="info" size={14} style={{ color: "var(--accent-teal)", flexShrink: 0, marginTop: 1 }} />
    <span><strong style={{ fontWeight: 600 }}>Running from USB —</strong> searches run one at a time and line up below. For instant results, install to this PC (run SETUP.bat on the drive).</span>
  </div>
);

const QueueStatusChip = ({ item, ahead }) => {
  const map = {
    queued:  { bg: "var(--border-light)", fg: "var(--text-secondary)", text: ahead > 0 ? `Queued · ${ahead} ahead` : "Queued · next" },
    running: { bg: "var(--accent-amber-light)", fg: "var(--accent-amber)", text: "Searching…" },
    done:    { bg: "var(--accent-teal-light)", fg: "var(--accent-teal)", text: `${item.count} result${item.count === 1 ? "" : "s"}` },
    error:   { bg: "var(--accent-red-light)", fg: "var(--accent-red)", text: "Failed" },
  };
  const s = map[item.status] || map.queued;
  return (
    <span style={{ fontSize: 11, fontWeight: 600, color: s.fg, background: s.bg, borderRadius: 999, padding: "2px 9px", whiteSpace: "nowrap", flexShrink: 0 }}>{s.text}</span>
  );
};

const SearchQueuePanel = ({ queue, viewedId, onView, onRemove, onClear }) => {
  const doneCount = queue.filter(q => q.status === "done" || q.status === "error").length;
  let queuedSeen = 0;
  return (
    <div style={{ border: "1px solid var(--border-light)", borderRadius: 10, background: "var(--bg-panel)", marginBottom: 14, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 12px", borderBottom: "1px solid var(--border-light)", background: "var(--bg)" }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text)", display: "flex", alignItems: "center", gap: 7 }}>
          <Icon name="history" size={14} style={{ color: "var(--text-muted)" }} />
          Search queue <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· {queue.length}</span>
        </span>
        {doneCount > 0 && (
          <button onClick={onClear} style={{ fontSize: 11.5, color: "var(--text-secondary)", background: "none", border: "none", cursor: "pointer", fontFamily: "var(--font-ui)" }}>Clear completed</button>
        )}
      </div>
      <div style={{ maxHeight: 176, overflowY: "auto" }}>
        {queue.map((item) => {
          const ahead = item.status === "queued" ? queuedSeen++ : 0;
          const clickable = item.status === "done";
          return (
            <div key={item.id} onClick={clickable ? () => onView(item) : undefined}
              style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", borderTop: "1px solid var(--border-light)", cursor: clickable ? "pointer" : "default", background: item.id === viewedId ? "var(--accent-red-light)" : "transparent" }}>
              <QueueStatusChip item={item} ahead={ahead} />
              <span style={{ flex: 1, minWidth: 0, fontSize: 12.5, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={item.query}>{item.query}</span>
              {item.status === "running" ? (
                <span style={{ width: 44, height: 4, borderRadius: 2, background: "var(--border)", overflow: "hidden", flexShrink: 0 }}>
                  <span style={{ display: "block", height: "100%", width: "45%", background: "var(--accent-amber)", borderRadius: 2, animation: "sfu-skimmer 1.1s ease-in-out infinite" }} />
                </span>
              ) : (
                <button onClick={(e) => { e.stopPropagation(); onRemove(item.id); }} aria-label="Remove from queue" title="Remove"
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", flexShrink: 0, fontSize: 15, lineHeight: 1, padding: "0 2px" }}>×</button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const SearchScreen = ({ savedIds, toggleSave, degraded, setAiStatus, interfacePrefs, sequential, draftStream, rerunReq, onRerunConsumed }) => {
  const [query, setQuery] = React.useState("");
  const [filters, setFilters] = React.useState({ type: "All", date: "Any time", access: "Any", sort: "Relevance" });
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
    const note = () => { if (swapRef.current) swapRef.current.noteActivity(); };
    const evs = ["mousemove", "keydown", "pointerdown", "wheel", "selectionchange", "touchstart"];
    evs.forEach(ev => document.addEventListener(ev, note, { passive: true }));
    const sc = scrollRef.current;
    if (sc) sc.addEventListener("scroll", note, { passive: true });
    return () => {
      evs.forEach(ev => document.removeEventListener(ev, note));
      if (sc) sc.removeEventListener("scroll", note);
      if (swapRef.current) swapRef.current.cancel();
    };
  }, []);
  const onCardHover = React.useCallback(id => { if (swapRef.current) swapRef.current.setHovered(id); }, []);

  
  
  
  
  
  
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
    const iv = setTimeout(() => setRetryState(s => s && ({ remaining: s.remaining - 1 })), 700);
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
      new window.Notification(ok ? "Search done: " + q : "Search failed: " + q,
        { body: ok ? (count + " result" + (count === 1 ? "" : "s")) : "Open the queue to retry." });
    } catch (e) {  }
  };

  const enqueue = (raw) => {
    const q = (raw || "").trim();
    if (!q) return;
    try { if (typeof window.Notification === "function" && window.Notification.permission === "default") window.Notification.requestPermission(); } catch (e) {}
    const id = "q" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    setQueue(prev => [...prev, { id, query: q, filters: filtersRef.current, status: "queued", count: 0, results: [], mock: false, error: null }]);
    setSearched(true);   
    setQuery("");        
  };

  
  
  React.useEffect(() => {
    if (!queueOn || runningRef.current) return;
    const next = queue.find(it => it.status === "queued");
    if (!next) return;
    runningRef.current = true;
    setQueue(qs => qs.map(it => it.id === next.id ? { ...it, status: "running" } : it));
    (async () => {
      try {
        const res = await window.SFUApi.search(next.query, next.filters, window.SFUApi.MAX_PAGES);
        if (res.source === "retry") {
          
          const backoff = Math.max(1, res.retryAfter || 3) * 1000;
          setTimeout(() => {
            setQueue(qs => qs.map(it => it.id === next.id ? { ...it, status: "queued" } : it));
            runningRef.current = false;
          }, backoff);
          return;
        }
        const live = res.source === "live" && res.results && res.results.length > 0;
        const list = live ? res.results : ((window.SFUMock && window.SFUMock.results) || []);
        if (res.source === "live") { engageQueryRef.current = next.query; engage("query", next.query); }
        const count = list.length;
        setQueue(qs => qs.map(it => it.id === next.id ? { ...it, status: "done", count, results: list, mock: !live } : it));
        if (window.SFUHistory) window.SFUHistory.record({ q: next.query, at: Date.now(), results: count, live });
        setResults(list); setUsingMock(!live); setViewed({ id: next.id, query: next.query }); setSelected(null);
        setPage(window.SFUApi.MAX_PAGES); setHasMore(false); setPageError(null);
        notifyDone(next.query, true, count);
      } catch (e) {
        setQueue(qs => qs.map(it => it.id === next.id ? { ...it, status: "error", error: String((e && e.message) || e) } : it));
        notifyDone(next.query, false, 0);
      }
      runningRef.current = false;  
    })();
  }, [queue, queueOn]);

  const viewQueued = (item) => {
    if (item.status !== "done") return;
    engageQueryRef.current = item.query;
    setResults(item.results || []); setUsingMock(!!item.mock);
    setViewed({ id: item.id, query: item.query }); setSelected(null);
    setPage(window.SFUApi.MAX_PAGES); setHasMore(false); setPageError(null);
  };
  const removeQueued = (id) => setQueue(prev => prev.filter(it => it.id !== id));
  const clearCompleted = () => setQueue(prev => prev.filter(it => it.status === "queued" || it.status === "running"));
  const handleSearch = () => { if (queueOn) enqueue(queryRef.current); else doSearch(); };

  
  
  
  const doSearch = async () => {
    if (!queryRef.current.trim()) return;
    const seq = ++searchSeqRef.current;
    if (swapRef.current) swapRef.current.cancel();
    swapRef.current = null;
    pendingMetaRef.current = null;
    setPreliminary(false);
    const useStream = !!draftStream && !sequential && !queueOn && typeof window.SFUApi.searchStream === "function"
      && typeof window.SFUApi.createDraftSwapController === "function";
    let ctrl = null;
    if (useStream) {
      ctrl = window.SFUApi.createDraftSwapController({
        isSelecting: () => { try { const sel = window.getSelection && window.getSelection(); return !!(sel && String(sel).length > 0); } catch (e) { return false; } },
        apply: (list, info) => {
          if (seq !== searchSeqRef.current) return;
          setResults(list);
          setPreliminary(info.state === "draft");
          if (info.state !== "draft" && pendingMetaRef.current) {
            setPage(pendingMetaRef.current.page);
            setHasMore(pendingMetaRef.current.more);
          }
        },
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
    pageCtxRef.current = { query: queryRef.current, filters: filtersRef.current };
    
    
    try { if (window.SFUApi) window.SFUApi.health().then(r => setHealthWarm(r.warm !== false)); } catch (e) {}
    try {
      const res = ctrl
        ? await window.SFUApi.searchStream(queryRef.current, filtersRef.current, 1, draft => {
            if (seq !== searchSeqRef.current || !draft.results || !draft.results.length) return;
            setHasMore(false);
            setUsingMock(false);
            setLoading(false);
            setSearched(true);
            ctrl.showDraft(draft.results);
          })
        : await window.SFUApi.search(queryRef.current, filtersRef.current, 1);
      if (ctrl && seq !== searchSeqRef.current) return;
      
      if (res.source === "retry") {
        setRetryState({ remaining: res.retryAfter });
        return;
      }
      const liveHasResults = res.source === "live" && res.results && res.results.length > 0;
      if (res.source === "live") { engageQueryRef.current = queryRef.current; engage("query", queryRef.current); }
      
      
      const showingMock = !liveHasResults;
      const sample = (window.SFUMock.results || []);
      const list = liveHasResults || res.source === "mock"
        ? res.results
        : sample.slice(0, window.SFUApi.pageLimit(res.page || 1));
      const more = liveHasResults || res.source === "mock"
        ? !!res.hasMore
        : ((res.page || 1) < window.SFUApi.MAX_PAGES && sample.length > list.length);
      
      
      
      if (window.SFUHistory) window.SFUHistory.record({
        q: queryRef.current, at: Date.now(),
        results: liveHasResults ? list.length : (res.meta && res.meta.count) || 0,
        live: liveHasResults,
      });
      if (ctrl) {
        pendingMetaRef.current = { page: res.page || 1, more: more };
        if (ctrl.state === "idle") { setPage(res.page || 1); setHasMore(more); }
        ctrl.offerFinal(list);
      } else {
        setResults(list);
        setPage(res.page || 1);
        setHasMore(more);
      }
      setUsingMock(showingMock);
      setDegradedNotice(res.degraded ? (res.degradedShards ? `Degraded — ${res.degradedShards} shard(s) unavailable, partial results shown.` : "Degraded — an engine was unavailable for this query, partial results shown.") : null);
      
      
      if (setAiStatus) setAiStatus(res.source === "live" ? "online" : "offline");
    } catch (e) {
      if (ctrl) { if (seq !== searchSeqRef.current) return; ctrl.cancel(); setPreliminary(false); }
      const sample = (window.SFUMock.results || []);
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
    if (next > window.SFUApi.MAX_PAGES) { setHasMore(false); return; }
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
    }, { root: scrollRef.current || null, rootMargin: "300px 0px" });
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
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "0 var(--landing-pad, 60px) 60px" }}>
        <div style={{ marginBottom: 32, textAlign: "center" }}>
          <div style={{ width: 52, height: 52, borderRadius: 14, background: "var(--accent-red)", display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 16 }}>
            <Icon name="search" size={22} style={{ color: "white" }} />
          </div>
          <h1 style={{ fontSize: 26, fontFamily: "var(--font-serif)", fontWeight: 500, color: "var(--text)", marginBottom: 8 }}>Research begins here.</h1>
          <p style={{ fontSize: 14, color: "var(--text-muted)", maxWidth: 400, lineHeight: 1.6 }}>Search 250M+ scholarly works with AI-powered query understanding and Duck Library access resolution.</p>
        </div>
        <div style={{ width: "100%", maxWidth: 600 }}>
          <SearchBar query={query} setQuery={setQuery} onSearch={handleSearch} loading={loading} filters={filters} setFilters={setFilters} compact />
          <FiltersExpander filters={filters} setFilters={setFilters} alwaysOpen={interfacePrefs && interfacePrefs.advancedFiltersOpen} />
        </div>
        {}
        <div style={{ marginTop: 24, display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", maxWidth: 580 }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)", width: "100%", textAlign: "center", marginBottom: 4 }}>Try:</span>
          {["indigenous knowledge systems in climate adaptation", "recent ML papers for drug discovery", "CRISPR gene editing in salmon, open access", "climate change BC fisheries 2020–2025"].map(ex => (
            <button key={ex} onClick={() => { setQuery(ex); }} style={{ fontSize: 12, padding: "6px 12px", background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 16, color: "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)", transition: "border-color 0.15s, color 0.15s" }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--accent-red)"; e.currentTarget.style.color = "var(--accent-red)"; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--text-secondary)"; }}>
              {ex}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {}
      <div style={{ padding: "14px 20px 12px", borderBottom: "1px solid var(--border-light)", background: "var(--bg-panel)" }}>
        <SearchBar query={query} setQuery={setQuery} onSearch={handleSearch} loading={loading} filters={filters} setFilters={setFilters} compact />
        <FiltersExpander filters={filters} setFilters={setFilters} alwaysOpen={interfacePrefs && interfacePrefs.advancedFiltersOpen} />
      </div>

      {}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {}
        <div ref={scrollRef} style={{ flex: 1, overflow: "auto", padding: "16px 20px" }}>
          {retryState ? (
            
            <div style={{ padding: "24px 0", textAlign: "center" }} role="status" aria-live="polite">
              <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>
                Server busy — retrying in {retryState.remaining}s…
              </div>
              <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                Too many searches at once. Auto-retrying automatically (you don't need to do anything).
              </div>
              <div style={{ width: 200, height: 4, background: "var(--border)", borderRadius: 2, margin: "14px auto 0", overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${Math.max(0, 100 - (retryState.remaining / Math.max(1, retryState.remaining) * 100))}%`, background: "var(--accent-red)", borderRadius: 2, transition: "width 0.7s linear" }} />
              </div>
            </div>
          ) : showWarming ? (
            
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ padding: "11px 13px", background: "var(--accent-amber-light)", borderRadius: 8, borderLeft: "3px solid var(--accent-amber)", fontSize: 12.5, color: "var(--text)", lineHeight: 1.5, display: "flex", gap: 10, alignItems: "flex-start" }} role="status">
                <Icon name="history" size={15} style={{ color: "var(--accent-amber)", flexShrink: 0, marginTop: 1 }} />
                <span><strong style={{ fontWeight: 600 }}>Index warming —</strong> the first search after a restart takes longer while the index pages in. Results are on the way.</span>
              </div>
              {[1, 2, 3].map(i => <SkeletonResultCard key={i} />)}
            </div>
          ) : loading ? (
            
            showSkeleton ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 8, display: "flex", alignItems: "center", gap: 8, fontVariantNumeric: "tabular-nums" }}>
                  Searching <em style={{ fontStyle: "normal", color: "var(--text-secondary)" }}>"{query}"</em> · {(elapsed / 1000).toFixed(1)}s
                </div>
                {[1, 2, 3].map(i => <SkeletonResultCard key={i} />)}
              </div>
            ) : null
          ) : (
            <>
              {}
              {(degradedNotice || degraded) && (
                <div style={{ padding: "10px 13px", background: "var(--accent-amber-light)", borderRadius: 8, borderLeft: "3px solid var(--accent-amber)", marginBottom: 12, fontSize: 12.5, color: "var(--text)", lineHeight: 1.5, display: "flex", gap: 8, alignItems: "flex-start" }} role="status">
                  <Icon name="warning" size={14} style={{ color: "var(--accent-amber)", flexShrink: 0, marginTop: 1 }} />
                  <span>{degradedNotice || "Degraded — partial results shown."}</span>
                </div>
              )}
              {queueOn && <SequentialBanner />}
              {queueOn && queue.length > 0 && (
                <SearchQueuePanel queue={queue} viewedId={viewed && viewed.id}
                  onView={viewQueued} onRemove={removeQueued} onClear={clearCompleted} />
              )}
              {(!queueOn || results.length > 0) ? (
                <>
                  <SearchProvenanceCard degraded={degraded} />
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                    <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                      <strong style={{ color: "var(--text)", fontWeight: 600 }}>{results.length}</strong> {hasMore ? "results loaded" : "results"} for <em>"{queueOn ? ((viewed && viewed.query) || "") : query}"</em>
                    </span>
                  </div>
                  {preliminary && (
                    <div data-testid="sfu-preliminary-note" role="status" aria-live="polite" style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 10, lineHeight: 1.5 }}>
                      Preliminary keyword matches — the ranked list replaces them when you pause.
                    </div>
                  )}
                  {results.map((r, i) => (
                    <ResultCard key={r.id} result={r} index={i + 1} onClick={openResult} saved={savedIds.has(r.id)} onSave={toggleSave} preliminary={preliminary} onHover={swapRef.current ? onCardHover : undefined} />
                  ))}
                  {!queueOn && (
                    <div ref={sentinelRef} data-testid="sfu-scroll-sentinel" style={{ padding: "14px 0 4px", textAlign: "center", minHeight: 8 }}>
                      {loadingMore ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }} aria-live="polite">
                          <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Loading more results…</span>
                          <SkeletonResultCard />
                        </div>
                      ) : pageError ? (
                        <button onClick={loadMore} style={{ fontSize: 12.5, padding: "7px 14px", background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 7, color: "var(--accent-red)", cursor: "pointer", fontFamily: "var(--font-ui)" }}>
                          {pageError} Try again
                        </button>
                      ) : hasMore ? (
                        <button onClick={loadMore} data-testid="sfu-load-more" style={{ fontSize: 12.5, padding: "7px 14px", background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 7, color: "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)" }}>
                          Load more results
                        </button>
                      ) : results.length > 0 ? (
                        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                          End of results{page >= window.SFUApi.MAX_PAGES ? " — refine your query for more" : ""}
                        </span>
                      ) : null}
                    </div>
                  )}
                </>
              ) : (
                <div style={{ padding: "28px 4px", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
                  Your searches will appear here as they finish.
                </div>
              )}
            </>
          )}
        </div>

        {}
        {selected && (
          <ResultDetail result={selected} onClose={() => setSelected(null)} saved={savedIds.has(selected.id)} onSave={toggleSave} />
        )}
      </div>
    </div>
  );
};


const SavedScreen = ({ savedIds, toggleSave }) => {
  
  const pool = {};
  ((window.SFUMock && window.SFUMock.results) || []).forEach(r => { pool[r.id] = r; });
  Object.assign(pool, window.__sfuResults || {});
  const saved = Array.from(savedIds).map(id => pool[id]).filter(Boolean);
  const [selected, setSelected] = React.useState(null);
  return (
    <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
      <div style={{ flex: 1, overflow: "auto", padding: "20px" }}>
        <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 500, marginBottom: 4, color: "var(--text)" }}>Saved Papers</h2>
        <p style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 16 }}>{saved.length} papers saved</p>
        {saved.length === 0 ? (
          <div style={{ textAlign: "center", padding: "60px 0", color: "var(--text-muted)" }}>
            <Icon name="bookmark" size={32} style={{ marginBottom: 12, opacity: 0.3 }} />
            <p style={{ fontSize: 14 }}>No saved papers yet.<br />Bookmark results from your searches.</p>
          </div>
        ) : saved.map((r, i) => (
          <ResultCard key={r.id} result={r} index={i + 1} onClick={setSelected} saved={true} onSave={toggleSave} />
        ))}
      </div>
      {selected && <ResultDetail result={selected} onClose={() => setSelected(null)} saved={savedIds.has(selected.id)} onSave={toggleSave} />}
    </div>
  );
};


const HistoryScreen = ({ onRerun }) => {
  const [entries, setEntries] = React.useState(() => (window.SFUHistory ? window.SFUHistory.read() : []));
  React.useEffect(() => {
    const refresh = () => setEntries(window.SFUHistory ? window.SFUHistory.read() : []);
    window.addEventListener("sfu-history-changed", refresh);
    window.addEventListener("storage", refresh);
    return () => { window.removeEventListener("sfu-history-changed", refresh); window.removeEventListener("storage", refresh); };
  }, []);

  const fmtTime = (at) => {
    const d = new Date(at);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " · " +
           d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  };

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px 24px" }}>
      <div style={{ maxWidth: 720 }}>
        <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 500, marginBottom: 3, color: "var(--text)" }}>Search History</h2>
        <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
          {entries.length} {entries.length === 1 ? "search" : "searches"} · stored locally on this device
          {entries.length > 0 && (
            <> · <button onClick={() => window.SFUHistory && window.SFUHistory.clear()}
              style={{ border: "none", background: "none", color: "var(--accent-red)", fontSize: 12, cursor: "pointer", fontFamily: "var(--font-ui)", padding: 0 }}>Clear all</button></>
          )}
        </p>
        {entries.length === 0 ? (
          <div style={{ textAlign: "center", padding: "60px 0", color: "var(--text-muted)" }}>
            <Icon name="history" size={32} style={{ marginBottom: 12, opacity: 0.3 }} />
            <p style={{ fontSize: 14 }}>No searches yet.<br />Queries you run will appear here so you can revisit them.</p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {entries.map(e => (
              <div key={e.at} style={{ display: "flex", alignItems: "center", gap: 10, padding: "11px 14px", borderRadius: 9, border: "1px solid var(--border-light)", background: "var(--bg-panel)" }}>
                <button onClick={() => onRerun && onRerun(e.q)} title={'Search again: ' + e.q}
                  style={{ flex: 1, minWidth: 0, border: "none", background: "none", textAlign: "left", cursor: "pointer", padding: 0, fontFamily: "var(--font-ui)" }}>
                  <span style={{ display: "block", fontSize: 13.5, color: "var(--text)", fontWeight: 500, lineHeight: 1.35, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.q}</span>
                  <span style={{ display: "block", fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>
                    {fmtTime(e.at)}{typeof e.results === "number" ? ` · ${e.results} results` : ""}{e.live === false ? " · sample data" : ""}
                  </span>
                </button>
                <button onClick={() => onRerun && onRerun(e.q)} title="Run this search again"
                  style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "5px 10px", border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", fontSize: 11.5, color: "var(--text-secondary)", cursor: "pointer", flexShrink: 0, fontFamily: "var(--font-ui)" }}>
                  <Icon name="search" size={11} /> Rerun
                </button>
                <button onClick={() => window.SFUHistory && window.SFUHistory.remove(e.at)} title="Remove from history" aria-label={'Remove "' + e.q + '" from history'}
                  style={{ border: "none", background: "none", color: "var(--text-muted)", cursor: "pointer", padding: 4, borderRadius: 4, display: "flex", flexShrink: 0 }}>
                  <Icon name="close" size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};


const DatabasesScreen = () => {
  const [search, setSearch] = React.useState("");
  const filtered = ((window.SFUMock && window.SFUMock.databases) || []).filter(d =>
    d.name.toLowerCase().includes(search.toLowerCase()) ||
    d.subjects.some(s => s.toLowerCase().includes(search.toLowerCase()))
  );
  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px" }}>
      <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 500, marginBottom: 4, color: "var(--text)" }}>Duck Library Databases</h2>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 14 }}>764 subscription databases · Registry synced daily</p>
      <div style={{ display: "flex", alignItems: "center", gap: 0, background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 7, padding: "0 10px", marginBottom: 14, maxWidth: 400 }}>
        <Icon name="search" size={14} style={{ color: "var(--text-muted)" }} />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Filter databases…" style={{ flex: 1, border: "none", background: "transparent", outline: "none", padding: "8px 8px", fontSize: 13, color: "var(--text)", fontFamily: "var(--font-ui)" }} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 8 }}>
        {filtered.map(db => (
          <div key={db.id} style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8, padding: "12px 14px" }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>{db.name}</span>
              <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 3, background: db.free ? "var(--accent-teal-light)" : "var(--accent-red-light)", color: db.free ? "var(--accent-teal)" : "var(--accent-red)", fontWeight: 500, whiteSpace: "nowrap", marginLeft: 6, flexShrink: 0 }}>
                {db.free ? "Free" : "Duck Sub."}
              </span>
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 5 }}>{db.provider}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
              {db.subjects.map(s => <span key={s} style={{ fontSize: 10, padding: "1px 6px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 3, color: "var(--text-secondary)" }}>{s}</span>)}
              {db.proxy && <span style={{ fontSize: 10, padding: "1px 6px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 3, color: "var(--text-secondary)" }}>EZProxy</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};


const PrivacyToggle = ({ label, desc, defaultOn }) => {
  const [on, setOn] = React.useState(defaultOn);
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, padding: "10px 12px", background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8 }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>{label}</div>
        <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>{desc}</div>
      </div>
      <button onClick={() => setOn(!on)} style={{ width: 38, height: 22, borderRadius: 11, background: on ? "var(--accent-red)" : "var(--border)", border: "none", cursor: "pointer", position: "relative", flexShrink: 0, transition: "background 0.2s" }}>
        <div style={{ width: 16, height: 16, borderRadius: "50%", background: "white", position: "absolute", top: 3, left: on ? 19 : 3, transition: "left 0.2s", boxShadow: "0 1px 3px rgba(0,0,0,0.2)" }} />
      </button>
    </div>
  );
};

const SettingsScreen = ({ interfacePrefs, setInterfacePref, sequential }) => {
  const [tab, setTab] = React.useState("interface");
  const [zoteroKey, setZoteroKey] = React.useState("••••••••••••••••");
  const [dictTab, setDictTab] = React.useState("abbreviations");
  const [dictEntries, setDictEntries] = React.useState([
    { abbr: "REM", full: "Resource & Environmental Management" },
    { abbr: "FASS", full: "Faculty of Arts & Social Sciences" },
    { abbr: "ILL", full: "Interlibrary Loan" },
    { abbr: "LCSH", full: "Library of Congress Subject Headings" },
  ]);

  const settingsTabs = [
    { id: "zotero", label: "Zotero" },
    { id: "dictionary", label: "Dictionary" },
    { id: "interface", label: "Interface" },
    { id: "privacy", label: "Privacy" },
  ];

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px 24px" }}>
      <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 500, marginBottom: 16, color: "var(--text)" }}>Settings</h2>

      {}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border-light)", marginBottom: 20 }}>
        {settingsTabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{ padding: "8px 16px", border: "none", background: "transparent", fontSize: 13, fontWeight: tab === t.id ? 500 : 400, color: tab === t.id ? "var(--accent-red)" : "var(--text-secondary)", cursor: "pointer", borderBottom: `2px solid ${tab === t.id ? "var(--accent-red)" : "transparent"}`, fontFamily: "var(--font-ui)", transition: "color 0.15s" }}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ maxWidth: 560 }}>

        {}
        {tab === "zotero" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ padding: "12px 14px", background: "oklch(93% 0.04 200)", border: "1px solid oklch(82% 0.07 200)", borderRadius: 8, display: "flex", gap: 10 }}>
              <Icon name="info" size={14} style={{ color: "var(--accent-teal)", flexShrink: 0, marginTop: 1 }} />
              <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.55 }}>Get your API key from <strong style={{ color: "var(--accent-teal)" }}>zotero.org/settings/keys</strong>. Zotero integration lets you save papers directly to your library with one click.</p>
            </div>
            {[
              { label: "API Key", value: zoteroKey, setter: setZoteroKey, type: "password" },
              { label: "User ID", value: "1234567", setter: () => {}, type: "text" },
            ].map(({ label, value, setter, type }) => (
              <div key={label}>
                <label style={{ fontSize: 12, fontWeight: 500, color: "var(--text-secondary)", display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</label>
                <input type={type} value={value} onChange={e => setter(e.target.value)} style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12.5, color: "var(--text)", background: "var(--bg-panel)", fontFamily: "monospace", outline: "none" }} />
              </div>
            ))}
            <div>
              <label style={{ fontSize: 12, fontWeight: 500, color: "var(--text-secondary)", display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>Default Collection</label>
              <select style={{ width: "100%", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12.5, color: "var(--text)", background: "var(--bg-panel)", fontFamily: "var(--font-ui)", appearance: "none", outline: "none" }}>
                <option>My Library (root)</option>
                <option>Research / Drug Discovery</option>
                <option>Research / CRISPR</option>
              </select>
            </div>
            <button style={{ padding: "9px 0", background: "var(--accent-red)", color: "white", border: "none", borderRadius: 7, fontSize: 13, fontWeight: 500, cursor: "pointer", fontFamily: "var(--font-ui)", width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
              <Icon name="check" size={14} /> Verify & Save
            </button>
          </div>
        )}

        {}
        {tab === "dictionary" && (
          <div>
            <p style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 14, lineHeight: 1.6 }}>Custom dictionary entries improve how queries are matched — abbreviations and local terms are expanded before the search runs.</p>

            <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border-light)", marginBottom: 14 }}>
              {["abbreviations", "synonyms", "stop expansions"].map(t => (
                <button key={t} onClick={() => setDictTab(t)} style={{ padding: "7px 14px", border: "none", background: "transparent", fontSize: 12, fontWeight: dictTab === t ? 500 : 400, color: dictTab === t ? "var(--accent-red)" : "var(--text-muted)", cursor: "pointer", borderBottom: `2px solid ${dictTab === t ? "var(--accent-red)" : "transparent"}`, fontFamily: "var(--font-ui)", textTransform: "capitalize" }}>
                  {t}
                </button>
              ))}
            </div>

            {dictTab === "abbreviations" && (
              <div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                  <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{dictEntries.length} entries</span>
                  <button style={{ fontSize: 12, padding: "5px 10px", background: "var(--accent-red)", color: "white", border: "none", borderRadius: 5, cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", gap: 4 }}>
                    <Icon name="plus" size={12} /> Add Entry
                  </button>
                </div>
                <div style={{ border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 64px", background: "var(--bg)", padding: "7px 12px", borderBottom: "1px solid var(--border)" }}>
                    {["Abbreviation", "Expansion", ""].map(h => <span key={h} style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</span>)}
                  </div>
                  {dictEntries.map((e, i) => (
                    <div key={i} style={{ display: "grid", gridTemplateColumns: "120px 1fr 64px", padding: "9px 12px", borderBottom: i < dictEntries.length - 1 ? "1px solid var(--border-light)" : "none", alignItems: "center" }}>
                      <span style={{ fontSize: 12.5, fontFamily: "monospace", fontWeight: 600, color: "var(--text)" }}>{e.abbr}</span>
                      <span style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>{e.full}</span>
                      <div style={{ display: "flex", gap: 4 }}>
                        <button style={{ border: "none", background: "transparent", color: "var(--text-muted)", cursor: "pointer", padding: 3, borderRadius: 3, display: "flex" }}><Icon name="edit" size={13} /></button>
                        <button onClick={() => setDictEntries(dictEntries.filter((_, j) => j !== i))} style={{ border: "none", background: "transparent", color: "var(--text-muted)", cursor: "pointer", padding: 3, borderRadius: 3, display: "flex" }}><Icon name="trash" size={13} /></button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {dictTab === "synonyms" && (
              <div style={{ padding: "20px 0", textAlign: "center", color: "var(--text-muted)" }}>
                <Icon name="book" size={28} style={{ marginBottom: 10, opacity: 0.3 }} />
                <p style={{ fontSize: 13 }}>No synonyms defined yet.<br />Add entries to improve query recall.</p>
              </div>
            )}

            {dictTab === "stop expansions" && (
              <div style={{ padding: "20px 0" }}>
                <p style={{ fontSize: 12.5, color: "var(--text-secondary)", marginBottom: 10, lineHeight: 1.6 }}>Terms the AI should <em>not</em> expand. Useful for acronyms like "BC" (province) or "UBC".</p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {["BC", "UBC", "FIPPA"].map(term => (
                    <div key={term} style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 8px", background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 5 }}>
                      <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 600, color: "var(--text)" }}>{term}</span>
                      <button style={{ border: "none", background: "transparent", color: "var(--text-muted)", cursor: "pointer", padding: 1, display: "flex" }}><Icon name="close" size={11} /></button>
                    </div>
                  ))}
                  <button style={{ padding: "4px 10px", background: "transparent", border: "1px dashed var(--border)", borderRadius: 5, fontSize: 12, color: "var(--text-muted)", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", gap: 4 }}>
                    <Icon name="plus" size={11} /> Add
                  </button>
                </div>
              </div>
            )}

            <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
              <button style={{ flex: 1, padding: "7px 0", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12, color: "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", justifyContent: "center", gap: 5 }}>
                <Icon name="download" size={13} /> Export JSON
              </button>
              <button style={{ flex: 1, padding: "7px 0", background: "var(--accent-red)", color: "white", border: "none", borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: "pointer", fontFamily: "var(--font-ui)" }}>Save Dictionary</button>
            </div>
          </div>
        )}

        {}
        {tab === "interface" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ padding: "10px 14px", background: "var(--bg)", border: "1px solid var(--border-light)", borderRadius: 8, display: "flex", gap: 10, alignItems: "flex-start" }}>
              <Icon name="info" size={14} style={{ color: "var(--accent-teal)", flexShrink: 0, marginTop: 1 }} />
              <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.55 }}>
                The search screen stays minimal by default — only the search box, results, and a status line. Turn features on as you need them. Toggles persist across reloads. <strong style={{ color: "var(--text)" }}>Reliability signals</strong> (demo-data banner, degraded notices, backend pill) are always shown and cannot be hidden.
              </p>
            </div>
            {[
              { key: "advancedFiltersOpen", label: "Advanced filters row always open", desc: "Keep the year/type/access/sort filters expanded under the search box (default: collapsed to “Filters”)" },
              { key: "savedHistoryNav", label: "Saved & History nav", desc: "Show the Saved Papers and History items in the sidebar (shown by default)" },
              { key: "databasesTab", label: "Databases tab", desc: "Show the Duck Library databases browser in the sidebar (hidden by default)" },
              { key: "analyticsApp", label: "About-index app (suite nav)", desc: "Show “About index” in the sidebar — the corpus-disclosures analytics app (hidden by default)" },
              { key: "indexManagerApp", label: "Index Manager app (suite nav)", desc: "Show “Index” in the sidebar — personas/sections, warm cache, storage budget (hidden by default)" },
              { key: "adminPanels", label: "Admin / operator panels", desc: "Show the Admin dashboard (models, curation, logs) — hidden by default for end users" },
            ].map(({ key, label, desc }) => {
              const on = !!(interfacePrefs && interfacePrefs[key]);
              return (
                <div key={key} style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, padding: "10px 12px", background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8 }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>{label}</div>
                    <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>{desc}</div>
                  </div>
                  <button onClick={() => setInterfacePref(key, !on)} aria-pressed={on} role="switch"
                    style={{ width: 38, height: 22, borderRadius: 11, background: on ? "var(--accent-red)" : "var(--border)", border: "none", cursor: "pointer", position: "relative", flexShrink: 0, transition: "background 0.2s" }}>
                    <div style={{ width: 16, height: 16, borderRadius: "50%", background: "white", position: "absolute", top: 3, left: on ? 19 : 3, transition: "left 0.2s", boxShadow: "0 1px 3px rgba(0,0,0,0.2)" }} />
                  </button>
                </div>
              );
            })}
            {}
            {(() => {
              const eff = (!interfacePrefs || interfacePrefs.searchQueueAuto !== false) ? !!sequential : !!(interfacePrefs && interfacePrefs.searchQueue);
              return (
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, padding: "10px 12px", background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8 }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>Search queue</div>
                    <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>
                      Line up searches and run them one at a time — best when running from a USB drive. {sequential ? "On automatically because this copy is in sequential (USB) mode." : "Off by default on fast local installs."}
                    </div>
                  </div>
                  <button onClick={() => { setInterfacePref("searchQueueAuto", false); setInterfacePref("searchQueue", !eff); }} aria-pressed={eff} role="switch"
                    style={{ width: 38, height: 22, borderRadius: 11, background: eff ? "var(--accent-red)" : "var(--border)", border: "none", cursor: "pointer", position: "relative", flexShrink: 0, transition: "background 0.2s" }}>
                    <div style={{ width: 16, height: 16, borderRadius: "50%", background: "white", position: "absolute", top: 3, left: eff ? 19 : 3, transition: "left 0.2s", boxShadow: "0 1px 3px rgba(0,0,0,0.2)" }} />
                  </button>
                </div>
              );
            })()}
            {}
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, padding: "10px 12px", background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>Density</div>
                <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 2 }}>comfortable (default) adds breathing room; compact tightens result cards.</div>
              </div>
              <div style={{ display: "flex", gap: 4, background: "var(--bg)", borderRadius: 8, padding: 2 }}>
                {["comfortable", "compact"].map((d) => (
                  <button key={d} onClick={() => setInterfacePref("density", d)}
                    style={{ padding: "5px 12px", borderRadius: 6, border: "none", background: (interfacePrefs && interfacePrefs.density) === d ? "var(--accent-red)" : "transparent", color: (interfacePrefs && interfacePrefs.density) === d ? "white" : "var(--text-secondary)", fontSize: 12, fontWeight: 500, cursor: "pointer", fontFamily: "var(--font-ui)", textTransform: "capitalize" }}>
                    {d}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {}
        {tab === "privacy" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {[
              { label: "Query Logging", desc: "Store search history locally for history/analytics", defaultOn: true },
              { label: "Anonymous Usage Stats", desc: "Send anonymous query count to help improve the system", defaultOn: false },
              { label: "SPECTER2 Reranking", desc: "Fetch embeddings from Semantic Scholar API", defaultOn: true },
            ].map(({ label, desc, defaultOn }) => (
              <PrivacyToggle key={label} label={label} desc={desc} defaultOn={defaultOn} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};


const AdminScreen = () => {
  const [tab, setTab] = React.useState("overview");

  const modelVersions = [
    { version: "v3", date: "2026-02-15", examples: 487, accuracy: "82%", status: "Active" },
    { version: "v2", date: "2026-01-10", examples: 312, accuracy: "78%", status: "Archived" },
    { version: "v1", date: "2025-12-01", examples: 200, accuracy: "71%", status: "Archived" },
    { version: "base", date: "—", examples: "—", accuracy: "65%", status: "Fallback" },
  ];

  const pendingQueries = [
    { q: "salmon habitat papers British Columbia", llm_out: '{"terms": ["salmon", "habitat", "British Columbia"], "type": "article"}', refined: "salmon habitat British Columbia" },
    { q: "indigenous studies papers 2023", llm_out: '{"terms": ["indigenous", "studies"], "from_publication_date": "2023-01-01"}', refined: "indigenous studies 2023" },
    { q: "open access remote sensing review", llm_out: '{"terms": ["remote", "sensing", "review"], "is_oa": true}', refined: "remote sensing review open access" },
  ];

  return (
    <div style={{ flex: 1, overflow: "auto", padding: "20px 24px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <div style={{ width: 28, height: 28, borderRadius: 6, background: "var(--accent-red)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Icon name="admin" size={14} style={{ color: "white" }} />
        </div>
        <div>
          <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 17, fontWeight: 500, color: "var(--text)", lineHeight: 1.2 }}>Admin Dashboard</h2>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Token protected · admin@ducklibrary.example</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--border-light)", marginBottom: 20 }}>
        {["overview", "models", "curate", "logs"].map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ padding: "8px 16px", border: "none", background: "transparent", fontSize: 13, fontWeight: tab === t ? 500 : 400, color: tab === t ? "var(--accent-red)" : "var(--text-secondary)", cursor: "pointer", borderBottom: `2px solid ${tab === t ? "var(--accent-red)" : "transparent"}`, fontFamily: "var(--font-ui)", textTransform: "capitalize", transition: "color 0.15s" }}>
            {t}
          </button>
        ))}
      </div>

      {}
      {tab === "overview" && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 20 }}>
            {[
              { label: "Queries (30d)", value: "1,247", icon: "search", color: "var(--accent-red)" },
              { label: "User Refinements", value: "312 (25%)", icon: "edit", color: "var(--accent-amber)" },
              { label: "Est. Accuracy", value: "~75%", icon: "activity", color: "var(--accent-teal)" },
              { label: "Avg Latency", value: "487ms", icon: "cpu", color: "oklch(52% 0.14 280)" },
            ].map(({ label, value, icon, color }) => (
              <div key={label} style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8, padding: "12px 14px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <span style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</span>
                  <Icon name={icon} size={14} style={{ color }} />
                </div>
                <div style={{ fontSize: 20, fontWeight: 600, color: "var(--text)", fontVariantNumeric: "tabular-nums" }}>{value}</div>
              </div>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            {}
            <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8, padding: "14px 16px" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>Active Model</div>
              <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)", marginBottom: 4 }}>Semantic hybrid index</div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8 }}>Learned-sparse + dense retrieval · cross-encoder rerank</div>
              <div style={{ display: "flex", gap: 6 }}>
                <span style={{ fontSize: 11, padding: "2px 8px", background: "oklch(93% 0.05 145)", color: "oklch(42% 0.14 145)", borderRadius: 4, fontWeight: 500 }}>82% accuracy</span>
                <span style={{ fontSize: 11, padding: "2px 8px", background: "var(--accent-teal-light)", color: "var(--accent-teal)", borderRadius: 4, fontWeight: 500 }}>Active</span>
              </div>
            </div>

            {}
            <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8, padding: "14px 16px" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>Improvement</div>
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--text)", marginBottom: 2 }}>RAG Examples</div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>234 curated pairs ready</div>
                <button style={{ fontSize: 11, padding: "4px 10px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 5, color: "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-ui)" }}>Review & Curate Queries</button>
              </div>
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 500, color: "var(--text)", marginBottom: 2 }}>Fine-Tune (requires GPU)</div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>487 training examples available</div>
                <button style={{ fontSize: 11, padding: "4px 10px", background: "var(--accent-red)", color: "white", border: "none", borderRadius: 5, cursor: "pointer", fontFamily: "var(--font-ui)", fontWeight: 500 }}>Start Fine-Tune Job</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {}
      {tab === "models" && (
        <div>
          <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8, overflow: "hidden", marginBottom: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "80px 1fr 80px 80px 80px 100px", padding: "8px 14px", background: "var(--bg)", borderBottom: "1px solid var(--border)" }}>
              {["Version", "Date", "Examples", "Accuracy", "Status", "Actions"].map(h => (
                <span key={h} style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{h}</span>
              ))}
            </div>
            {modelVersions.map((m, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "80px 1fr 80px 80px 80px 100px", padding: "10px 14px", borderBottom: i < modelVersions.length - 1 ? "1px solid var(--border-light)" : "none", alignItems: "center", background: m.status === "Active" ? "oklch(98% 0.008 145)" : "transparent" }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", fontFamily: "monospace" }}>{m.version}</span>
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{m.date}</span>
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{m.examples}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: m.status === "Active" ? "oklch(42% 0.14 145)" : "var(--text-secondary)" }}>{m.accuracy}</span>
                <span style={{ fontSize: 11, padding: "2px 7px", borderRadius: 4, background: m.status === "Active" ? "oklch(93% 0.05 145)" : m.status === "Fallback" ? "var(--accent-red-light)" : "var(--bg)", color: m.status === "Active" ? "oklch(42% 0.14 145)" : m.status === "Fallback" ? "var(--accent-red)" : "var(--text-muted)", fontWeight: 500, display: "inline-block" }}>{m.status}</span>
                <div style={{ display: "flex", gap: 4 }}>
                  {m.status !== "Active" && <button style={{ fontSize: 10, padding: "2px 7px", background: "var(--accent-red-light)", color: "var(--accent-red)", border: "none", borderRadius: 4, cursor: "pointer", fontFamily: "var(--font-ui)", fontWeight: 500 }}>Activate</button>}
                  <button style={{ fontSize: 10, padding: "2px 7px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 4, cursor: "pointer", fontFamily: "var(--font-ui)", color: "var(--text-secondary)" }}>Log</button>
                </div>
              </div>
            ))}
          </div>

          <div style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8, padding: "16px" }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)", marginBottom: 10 }}>Schedule Fine-Tuning</div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
              <select style={{ flex: 1, padding: "7px 10px", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12.5, color: "var(--text)", background: "var(--bg)", fontFamily: "var(--font-ui)", outline: "none" }}>
                <option>Every month</option><option>Every 2 weeks</option><option>Manual only</option>
              </select>
              <button style={{ padding: "7px 14px", background: "var(--accent-red)", color: "white", border: "none", borderRadius: 6, fontSize: 12.5, fontWeight: 500, cursor: "pointer", fontFamily: "var(--font-ui)", whiteSpace: "nowrap" }}>
                Run Now
              </button>
            </div>
            <p style={{ fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.5 }}>Last run: <strong>2026-02-15</strong> · accuracy 75% → 82% · duration 52 min on A100</p>
          </div>
        </div>
      )}

      {}
      {tab === "curate" && (
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
            <div>
              <p style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>Query Curation</p>
              <p style={{ fontSize: 12, color: "var(--text-muted)" }}>23 / 156 pending reviewed</p>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <select style={{ padding: "5px 10px", border: "1px solid var(--border)", borderRadius: 5, fontSize: 12, color: "var(--text)", background: "var(--bg-panel)", fontFamily: "var(--font-ui)", outline: "none" }}>
                <option>Refined only</option><option>All queries</option>
              </select>
              <select style={{ padding: "5px 10px", border: "1px solid var(--border)", borderRadius: 5, fontSize: 12, color: "var(--text)", background: "var(--bg-panel)", fontFamily: "var(--font-ui)", outline: "none" }}>
                <option>Last 7 days</option><option>Last 30 days</option>
              </select>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {pendingQueries.map((pq, i) => (
              <div key={i} style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: 8, padding: "14px 16px" }}>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>User query</div>
                <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)", marginBottom: 8 }}>"{pq.q}"</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>LLM Output</div>
                    <pre style={{ fontSize: 11, background: "var(--bg)", padding: "6px 8px", borderRadius: 5, color: "var(--text-secondary)", overflowX: "auto", margin: 0, border: "1px solid var(--border)" }}>{pq.llm_out}</pre>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>User Refined To</div>
                    <div style={{ fontSize: 12, background: "oklch(93% 0.05 145)", padding: "6px 8px", borderRadius: 5, color: "oklch(32% 0.10 145)", border: "1px solid oklch(84% 0.07 145)", fontStyle: "italic" }}>"{pq.refined}"</div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button style={{ flex: 1, padding: "6px 0", background: "oklch(93% 0.05 145)", color: "oklch(42% 0.14 145)", border: "1px solid oklch(84% 0.07 145)", borderRadius: 5, fontSize: 12, fontWeight: 500, cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", justifyContent: "center", gap: 4 }}>
                    <Icon name="check" size={12} /> Add to training
                  </button>
                  <button style={{ flex: 1, padding: "6px 0", background: "var(--bg)", color: "var(--text-muted)", border: "1px solid var(--border)", borderRadius: 5, fontSize: 12, cursor: "pointer", fontFamily: "var(--font-ui)" }}>
                    Skip
                  </button>
                  <button style={{ padding: "6px 12px", background: "var(--bg)", color: "var(--accent-amber)", border: "1px solid var(--accent-amber-light)", borderRadius: 5, fontSize: 12, cursor: "pointer", fontFamily: "var(--font-ui)", display: "flex", alignItems: "center", gap: 4 }}>
                    <Icon name="warning" size={12} /> Flag
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {}
      {tab === "logs" && (
        <div>
          <div style={{ background: "#0d1117", borderRadius: 8, padding: "14px 16px", fontFamily: "monospace", fontSize: 11.5, color: "#8b949e", lineHeight: 1.7, maxHeight: 480, overflow: "auto" }}>
            {[
              { time: "14:41:02", level: "INFO", msg: "Query parsed: 'machine learning drug discovery' → {terms: ['machine learning', 'drug discovery'], material_type: 'article'}", color: "#8b949e" },
              { time: "14:41:03", level: "INFO", msg: "OpenAlex: 50 results fetched in 312ms", color: "#8b949e" },
              { time: "14:41:03", level: "INFO", msg: "Semantic Scholar: SPECTER2 embeddings batch 50/50 in 487ms", color: "#8b949e" },
              { time: "14:41:03", level: "INFO", msg: "Access resolver: 12 OA, 23 Duck proxy, 8 Unpaywall, 7 DOI fallback", color: "#8b949e" },
              { time: "14:41:03", level: "INFO", msg: "Reranker: NDCG@10 pipeline complete in 2ms", color: "#8b949e" },
              { time: "14:41:04", level: "INFO", msg: "Returned 7 results to UI in 1.2s total", color: "#8b949e" },
              { time: "11:08:15", level: "WARN", msg: "Semantic Scholar rate limit hit (1 req/s), backing off 1.2s", color: "#d29922" },
              { time: "11:08:16", level: "INFO", msg: "Circuit breaker: semantic_scholar CLOSED (healthy)", color: "#8b949e" },
              { time: "11:00:00", level: "INFO", msg: "Solr registry refreshed: 764 records cached (~198KB)", color: "#3fb950" },
              { time: "10:45:33", level: "ERROR", msg: "Unpaywall: 10.1039/D3SC01234X not found — DOI fallback used", color: "#f85149" },
            ].map((log, i) => (
              <div key={i} style={{ display: "flex", gap: 10 }}>
                <span style={{ color: "#484f58", flexShrink: 0 }}>{log.time}</span>
                <span style={{ color: log.level === "ERROR" ? "#f85149" : log.level === "WARN" ? "#d29922" : "#3fb950", flexShrink: 0, width: 36 }}>{log.level}</span>
                <span style={{ color: log.color }}>{log.msg}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
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
      window.SFUApi.health().then((r) => {
        if (cancelled) return;
        setAiStatus(r.source === "live" ? "online" : "offline");
        setServerSequential(!!r.sequential);
        setServerDraftStream(!!r.draftStream);
        
      });
    }
    return () => { cancelled = true; };
  }, []);

  
  
  
  React.useEffect(() => {
    const onMsg = (e) => {
      if (e.data && typeof e.data.suiteScreen === "string") setScreen(e.data.suiteScreen);
    };
    window.addEventListener("message", onMsg);
    if (window.parent !== window) window.parent.postMessage({ suiteReady: "search" }, "*");
    return () => window.removeEventListener("message", onMsg);
  }, []);

  
  
  
  
  const [rerunReq, setRerunReq] = React.useState(null);
  const requestRerun = (q) => { setRerunReq({ q, n: Date.now() }); setScreen("search"); };
  React.useEffect(() => {
    const onRerun = (e) => { if (e.detail && e.detail.q) requestRerun(e.detail.q); };
    window.addEventListener("sfu-history-rerun", onRerun);
    const pending = window.SFUHistory && window.SFUHistory.takePending();
    if (pending) requestRerun(pending);
    return () => window.removeEventListener("sfu-history-rerun", onRerun);
  }, []);

  
  
  const [interfacePrefs, setInterfacePref] = window.SFUUI && window.SFUUI.useInterfacePrefs
    ? window.SFUUI.useInterfacePrefs()
    : React.useState(window.SFUUI && window.SFUUI.readInterfacePrefs ? window.SFUUI.readInterfacePrefs() : {});

  const toggleSave = (id) => {
    setSavedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const accent = { main: "oklch(52% 0.18 25)", light: "oklch(94% 0.04 25)", mid: "oklch(70% 0.10 25)" };

  
  
  
  const hiddenScreens = {};
  if (!interfacePrefs.savedHistoryNav) { hiddenScreens.saved = true; hiddenScreens.history = true; }
  if (!interfacePrefs.databasesTab) hiddenScreens.databases = true;
  if (!interfacePrefs.adminPanels) hiddenScreens.admin = true;
  
  
  if (hiddenScreens[screen]) {  }

  return (
    <>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        @keyframes sfu-skimmer { 0%, 100% { opacity: 0.55; } 50% { opacity: 0.9; } }
        :root {
          --accent-red: ${accent.main};
          --accent-red-light: ${accent.light};
          --accent-red-mid: ${accent.mid};
        }
      `}</style>
      <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
        <SuiteSidebar app="search" active={screen} onScreen={setScreen} hiddenScreens={hiddenScreens} interfacePrefs={interfacePrefs} />
        <main style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
          {screen === "search" && <SearchScreen savedIds={savedIds} toggleSave={toggleSave} setAiStatus={setAiStatus} interfacePrefs={interfacePrefs} sequential={serverSequential} draftStream={serverDraftStream} rerunReq={rerunReq} onRerunConsumed={() => setRerunReq(null)} />}
          {screen === "saved" && !hiddenScreens.saved && <SavedScreen savedIds={savedIds} toggleSave={toggleSave} />}
          {screen === "history" && !hiddenScreens.history && <HistoryScreen onRerun={requestRerun} />}
          {screen === "databases" && !hiddenScreens.databases && <DatabasesScreen />}
          {screen === "settings" && <SettingsScreen interfacePrefs={interfacePrefs} setInterfacePref={setInterfacePref} sequential={serverSequential} />}
          {screen === "admin" && !hiddenScreens.admin && <AdminScreen />}
          {}
          {hiddenScreens[screen] && screen !== "search" && screen !== "settings" && <SearchScreen savedIds={savedIds} toggleSave={toggleSave} setAiStatus={setAiStatus} interfacePrefs={interfacePrefs} sequential={serverSequential} draftStream={serverDraftStream} rerunReq={rerunReq} onRerunConsumed={() => setRerunReq(null)} />}
        </main>
      </div>
    </>
  );
};

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
