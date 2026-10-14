

const Icon = ({ name, size = 16, style = {} }) => {
  const I = {
    search: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="9" cy="9" r="6"/><path d="m16 16-3.5-3.5"/></svg>,
    bookmark: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 3h10v14l-5-3-5 3V3Z"/></svg>,
    history: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="10" cy="10" r="7"/><path d="M10 6v4l2.5 2.5"/></svg>,
    database: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="10" cy="5.5" rx="7" ry="2.5"/><path d="M3 5.5v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5v-4"/><path d="M3 9.5v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5v-4"/></svg>,
    chart: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 17h14"/><path d="M6 14V9M10 14V5M14 14v-6"/></svg>,
    settings: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="10" cy="10" r="2.5"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42"/></svg>,
    admin: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2L3 6v4c0 4.4 3.03 8.52 7 9.5 3.97-.98 7-5.1 7-9.5V6L10 2Z"/></svg>,
    server: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3.5" width="14" height="5.5" rx="1.2"/><rect x="3" y="11" width="14" height="5.5" rx="1.2"/><path d="M6 6.25h.01M6 13.75h.01"/></svg>,
    globe: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="10" cy="10" r="7.5"/><path d="M2.5 10h15M10 2.5c2 2.2 3 4.8 3 7.5s-1 5.3-3 7.5c-2-2.2-3-4.8-3-7.5s1-5.3 3-7.5Z"/></svg>,
    route: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="5" cy="15" r="2"/><circle cx="15" cy="5" r="2"/><path d="M7 15h5a3 3 0 0 0 3-3V7"/></svg>,
    clock: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="10" cy="10" r="7.5"/><path d="M10 5.5V10l3 2"/></svg>,
    scale: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M10 3v14M5 17h10M4 7l-2 5a3 3 0 0 0 6 0L6 7Zm10 0-2 5a3 3 0 0 0 6 0l-2-5ZM4 7l6-2 6 2"/></svg>,
    check: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m4 10.5 4 4 8-9"/></svg>,
    chevronDown: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 8 5 5 5-5"/></svg>,
    chevronRight: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m8 5 5 5-5 5"/></svg>,
    arrowLeft: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m10 5-5 5 5 5"/><path d="M5 10h11"/></svg>,
    info: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="10" cy="10" r="7"/><path d="M10 9v5M10 6.5v.5"/></svg>,
    wrench: <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14 5.5a3.5 3.5 0 0 1-4.6 3.3l-4 4a1.7 1.7 0 0 1-2.4-2.4l4-4A3.5 3.5 0 0 1 14.5 2l-2 2 1.5 1.5 2-2c.3.6.5 1.2.5 2Z"/></svg>,
  };
  return <span style={{ display: "inline-flex", alignItems: "center", ...style }}>{I[name] || null}</span>;
};

const fmtInt = (n) => (n == null || !Number.isFinite(Number(n)) ? "—" : Number(n).toLocaleString("en-US"));
const fmtMillions = (n) => (n == null ? "—" : (Number(n) / 1e6).toFixed(1) + "M");
const fmt3 = (x) => (x == null || !Number.isFinite(Number(x)) ? "—" : Number(x).toFixed(3));
const fmtDate = (s) => (s ? String(s).slice(0, 10) : null);
const pctOf = (part, total) => (total ? Math.round((part / total) * 1000) / 10 : 0);

const panelOf = (bundle, name) => {
  if (bundle === null) return { status: "loading" };
  const p = bundle && bundle.panels ? bundle.panels[name] : null;
  return p && typeof p === "object" ? p : { status: "missing" };
};

function liveFacts(shape, signal) {
  const ok = shape.status === "ok";
  const recency = signal.status === "ok" && Array.isArray(signal.axes)
    ? (signal.axes.find(a => a.signal === "recency") || {}).weight : null;
  const other = ok ? (shape.subjects || []).find(s => s.subject === "other") : null;
  return {
    ok,
    total: ok ? shape.total_docs : null,
    built: ok ? fmtDate(shape.built) : null,
    boundary: ok ? shape.era_boundary_year : null,
    nSections: ok ? shape.n_sections : null,
    nSubjects: ok ? shape.n_subjects : null,
    nEras: ok ? (shape.eras || []).length : null,
    otherDocs: other ? other.docs : null,
    otherPct: other && shape.total_docs ? pctOf(other.docs, shape.total_docs) : null,
    recency: recency != null ? recency : null,
    rrfK: ok ? shape.rrf_k : null,
  };
}

function buildDisclosures(f) {
  return [
    {
      id: 1, tone: "warn", icon: "database",
      title: "One source — and it has a shape",
      what: "Everything searchable comes from a single OpenAlex snapshot" + (f.built ? " (index built " + f.built + ")" : "") + ". OpenAlex is strong on journal articles and conference papers, and noticeably thin on books, theses, grey literature, humanities monographs, and non-English venues.",
      matters: "If a work isn't in that snapshot, no search here can surface it — no matter how you phrase the query.",
      todo: "For books and humanities, also use the library catalogue and subject databases.",
    },
    {
      id: 2, tone: "warn", icon: "globe",
      title: "Tuned for English",
      what: "The semantic model (a bert-base-uncased SPLADE encoder) and every section's vocabulary are English-only. Meaning-based matching effectively doesn't apply to other languages.",
      matters: "Scholarship in other languages — including Indigenous-language work and non-English-venue research — ranks lower or is missed entirely.",
      todo: "Search your key terms in the source language too, and lean on language-specific databases.",
    },
    {
      id: 3, tone: "warn", icon: "route",
      title: "One discipline per query",
      what: "The router assigns each query to a single subject bucket, in priority order. " + (f.otherDocs != null
        ? fmtInt(f.otherDocs) + " documents (" + f.otherPct + "% of the index) sit in the unrouted “other” bucket the router rarely reaches."
        : "Documents no subject vocabulary matched sit in an unrouted “other” bucket the router rarely reaches."),
      matters: "A cross-disciplinary topic gets sent to just one discipline's section — the other side of the topic is never searched.",
      todo: "Re-run under a different subject profile, or use “Widen search” on the coverage card attached to your results.",
    },
    {
      id: 4, tone: "warn", icon: "clock",
      title: "Recent by default",
      what: "The index is split by era" + (f.boundary ? " at the year " + f.boundary : "") + ". The default reader profile favours recent material, and the ranker adds a recency weight" + (f.recency != null ? " (" + f.recency + ")" : "") + " on top.",
      matters: "Older foundational and historical work ranks lower, and an active date filter can prune it from the search entirely.",
      todo: "Remove the date filter from the coverage card to bring older eras back into scope.",
    },
    {
      id: 5, tone: "good", icon: "scale",
      title: "Ranked by text, not by prestige",
      what: "Results are ordered purely by how well their text matches your query. Citation counts, journal impact, and author reputation play no part in ranking.",
      matters: "This avoids a rich-get-richer bias — but it also means a highly-cited landmark paper gets no automatic lift. Judge quality yourself.",
      todo: null,
      positive: true,
    },
  ];
}

const DisclosureCard = ({ d, n }) => {
  const tones = {
    warn: { bar: "var(--c-amber)", ic: "var(--c-amber-ink)", icbg: "var(--c-amber-soft)" },
    good: { bar: "var(--c-green)", ic: "oklch(42% 0.10 145)", icbg: "var(--c-green-soft)" },
  };
  const t = tones[d.tone];
  return (
    <section style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderLeft: `3px solid ${t.bar}`, borderRadius: "var(--radius-lg)", padding: "24px 28px", display: "flex", gap: 18, boxShadow: "var(--shadow-sm)" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <span style={{ width: 38, height: 38, borderRadius: 10, background: t.icbg, color: t.ic, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Icon name={d.icon} size={19} />
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-faint)" }}>{String(n).padStart(2, "0")}</span>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h3 style={{ fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 500, color: "var(--text)", marginBottom: 8, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {d.title}
          {d.positive && <span style={{ fontSize: 10.5, fontWeight: 500, letterSpacing: "0.06em", textTransform: "uppercase", padding: "2px 8px", borderRadius: 4, background: "var(--c-green-soft)", color: "oklch(42% 0.10 145)" }}>By design</span>}
        </h3>
        <p style={{ fontSize: 13.5, color: "var(--text-secondary)", lineHeight: 1.6, marginBottom: 12, maxWidth: "70ch" }}>{d.what}</p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }} className="disc-grid">
          <div style={{ padding: "11px 14px", background: "var(--bg-soft)", borderRadius: 8 }}>
            <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 4 }}>Why it matters</div>
            <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.55 }}>{d.matters}</p>
          </div>
          {d.todo && (
            <div style={{ padding: "11px 14px", background: "var(--c-teal-soft)", borderRadius: 8 }}>
              <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", color: "oklch(40% 0.10 200)", marginBottom: 4 }}>What to do</div>
              <p style={{ fontSize: 12.5, color: "oklch(34% 0.07 200)", lineHeight: 1.55 }}>{d.todo}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
};

const Panel = ({ icon, title, sub, children, name, state }) => (
  <section data-panel={name} data-state={state} style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: "var(--radius-lg)", padding: "22px 24px", display: "flex", flexDirection: "column", gap: 16, boxShadow: "var(--shadow-sm)", minWidth: 0 }}>
    <header style={{ display: "flex", gap: 11, alignItems: "flex-start" }}>
      <span style={{ width: 30, height: 30, borderRadius: 8, background: "var(--bg-soft)", color: "var(--text-secondary)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        <Icon name={icon} size={16} />
      </span>
      <div style={{ minWidth: 0 }}>
        <h3 style={{ fontFamily: "var(--font-serif)", fontSize: 16.5, fontWeight: 500, color: "var(--text)", lineHeight: 1.2 }}>{title}</h3>
        {sub && <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2, overflowWrap: "anywhere" }}>{sub}</p>}
      </div>
    </header>
    {children}
  </section>
);

const Notice = ({ tone = "neutral", children, testid }) => {
  const bg = tone === "warn" ? "var(--c-amber-soft)" : "var(--bg-soft)";
  return (
    <div data-testid={testid} style={{ display: "flex", gap: 10, padding: "11px 14px", background: bg, borderRadius: 8 }}>
      <Icon name="info" size={15} style={{ color: tone === "warn" ? "var(--c-amber-ink)" : "var(--text-muted)", flexShrink: 0, marginTop: 1 }} />
      <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.55, minWidth: 0, overflowWrap: "anywhere" }}>{children}</p>
    </div>
  );
};

const PanelFallback = ({ panel, minHeight = 0 }) => {
  if (panel.status === "loading") {
    return <div data-testid="sfu-panel-loading" aria-busy="true" style={{ minHeight, background: "var(--bg-soft)", borderRadius: 8 }} />;
  }
  if (panel.status === "missing") {
    return <Notice testid="sfu-panel-missing">Not in the analytics bundle served by this backend.</Notice>;
  }
  return <Notice testid="sfu-panel-stub">Not wired: {panel.reason || "no data source yet"}.</Notice>;
};

const Bars = ({ rows, valueLabel, labelWidth = 180 }) => {
  const max = Math.max(...rows.map(r => r.v), 0) || 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map(r => (
        <div key={r.key || r.name} style={{ display: "grid", gridTemplateColumns: `minmax(0, ${labelWidth}px) minmax(0, 1fr) 64px`, alignItems: "center", gap: 12 }}>
          <span title={r.name} style={{ fontSize: 12.5, color: "var(--text)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.name}</span>
          <div style={{ height: 12, background: "var(--bg-soft)", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ width: `${(r.v / max) * 100}%`, height: "100%", background: r.color || "var(--c-teal)", borderRadius: 4 }} />
          </div>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--text-secondary)", textAlign: "right" }}>{valueLabel(r)}</span>
        </div>
      ))}
    </div>
  );
};

const StackBar = ({ rows }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
    <div style={{ display: "flex", height: 38, borderRadius: 8, overflow: "hidden", border: "1px solid var(--border-light)" }}>
      {rows.map(r => (
        <div key={r.name} title={`${r.name}: ${r.pct}%`} style={{ width: `${r.pct}%`, background: r.color || "var(--c-teal)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          {r.pct >= 12 && <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 500, color: "white" }}>{r.pct}%</span>}
        </div>
      ))}
    </div>
    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      {rows.map(r => (
        <div key={r.name} style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 12.5 }}>
          <span style={{ width: 10, height: 10, borderRadius: 3, background: r.color || "var(--c-teal)", flexShrink: 0 }} />
          <span style={{ color: "var(--text)", flex: 1 }}>{r.name}</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--text-secondary)" }}>{r.detail} · {r.pct}%</span>
        </div>
      ))}
    </div>
  </div>
);

const SUBJECT_COLORS = ["oklch(72% 0.012 250)", "var(--c-amber)", "var(--c-red)", "var(--c-indigo)", "var(--c-teal)", "var(--c-violet)", "var(--c-green)"];

const ShapeSection = ({ shape }) => {
  const ok = shape.status === "ok";
  const subjects = ok ? (shape.subjects || []) : [];
  const eras = ok ? (shape.eras || []) : [];
  const total = ok ? shape.total_docs : 0;
  const b = ok ? shape.era_boundary_year : null;
  const eraName = (e) => e === "recent" ? (b ? b + " – present" : "recent") : e === "archive" ? (b ? "pre-" + b : "archive") : e;
  const eraRows = eras.map((e, i) => ({ name: eraName(e.era), pct: pctOf(e.docs, total), detail: fmtMillions(e.docs), color: e.era === "recent" ? "var(--c-teal)" : "oklch(72% 0.012 250)" }));
  const subjRows = subjects.map((s, i) => ({ key: s.subject, name: s.label || s.subject, v: s.docs, color: s.subject === "other" ? SUBJECT_COLORS[0] : SUBJECT_COLORS[1 + (i % (SUBJECT_COLORS.length - 1))] }));
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 16, marginBottom: 16, flexWrap: "wrap" }}>
        <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 21, fontWeight: 500, color: "var(--text)" }}>The shape of the index</h2>
        <span style={{ fontSize: 12, color: "var(--text-muted)", overflowWrap: "anywhere" }}>{ok ? `Section manifest ${shape.source}${shape.built ? " · built " + fmtDate(shape.built) : ""}` : "Section manifest"}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 18 }} className="dist-grid" data-panel="index_shape" data-state={shape.status}>
        <Panel icon="route" title="By subject bucket" sub="Documents per router bucket, both eras">
          {ok ? <Bars rows={subjRows} valueLabel={r => fmtMillions(r.v)} /> : <PanelFallback panel={shape} minHeight={150} />}
        </Panel>
        <Panel icon="clock" title="By era" sub={b ? `Split at the ${b} boundary` : "Split by publication era"}>
          {ok ? <StackBar rows={eraRows} /> : <PanelFallback panel={shape} minHeight={110} />}
        </Panel>
      </div>
    </div>
  );
};

const SubHead = ({ children }) => (
  <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 10 }}>{children}</div>
);

const tableCell = { padding: "6px 10px", borderBottom: "1px solid var(--border-light)", textAlign: "left", fontSize: 12, whiteSpace: "nowrap" };
const tableHead = { ...tableCell, fontSize: 10.5, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--text-muted)" };

const Table = ({ cols, rows, testid }) => (
  <div style={{ overflowX: "auto", maxWidth: "100%" }}>
    <table data-testid={testid} style={{ borderCollapse: "collapse", width: "100%" }}>
      <thead><tr>{cols.map(c => <th key={c.key} style={{ ...tableHead, textAlign: c.num ? "right" : "left" }}>{c.label}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>{cols.map(c => <td key={c.key} style={{ ...tableCell, textAlign: c.num ? "right" : "left", fontFamily: c.num ? "var(--font-mono)" : "inherit", color: "var(--text-secondary)" }}>{c.render ? c.render(r) : (r[c.key] == null ? "—" : String(r[c.key]))}</td>)}</tr>
        ))}
      </tbody>
    </table>
  </div>
);

const QualityPanel = ({ kpis }) => {
  const ok = kpis.status === "ok" && Array.isArray(kpis.methods) && kpis.methods.length > 0;
  const k = kpis.k || 10;
  return (
    <Panel name="kpis" state={kpis.status} icon="chart" title={`Retrieval quality · LLM-judged NDCG@${k}`}
      sub={ok ? `${fmtInt(kpis.eval_queries)} eval queries · ${fmtInt(kpis.judged_pairs)} judged pairs · ${fmtDate(kpis.timestamp) || "undated"} · ${kpis.source || ""}` : null}>
      {ok ? (
        <>
          <Table testid="sfu-kpi-methods" cols={[
            { key: "label", label: "Method", render: r => r.label + (r.method === kpis.best_method ? " ★" : "") },
            { key: "mean_ndcg", label: `NDCG@${k}`, num: true, render: r => fmt3(r.mean_ndcg) },
            { key: "mean_mrr", label: "MRR", num: true, render: r => fmt3(r.mean_mrr) },
            { key: "mean_p_at_k", label: `P@${k}`, num: true, render: r => fmt3(r.mean_p_at_k) },
          ]} rows={kpis.methods} />
          {kpis.judge && <p style={{ fontSize: 11.5, color: "var(--text-muted)", overflowWrap: "anywhere" }}>Judge: {kpis.judge}. ★ best mean NDCG.</p>}
        </>
      ) : <PanelFallback panel={kpis} minHeight={120} />}
    </Panel>
  );
};

const SubjectNdcgPanel = ({ panel, k }) => {
  const ok = panel.status === "ok" && Array.isArray(panel.subjects);
  const subjects = ok ? panel.subjects : [];
  const zeros = subjects.filter(s => !s.ndcg).length;
  return (
    <Panel name="ndcg_by_subject" state={panel.status} icon="chart" title={`NDCG@${k || 10} by subject`}
      sub={ok ? `Method ${panel.primary_method || "—"} · ${subjects.length} subjects, lowest first${zeros ? ` · ${zeros} at 0.000` : ""}` : null}>
      {ok ? (
        subjects.length ? (
          <div style={{ maxHeight: 280, overflowY: "auto", paddingRight: 4 }}>
            <Bars rows={subjects.map(s => ({ key: s.subject, name: s.subject, v: s.ndcg || 0, color: "var(--c-indigo)" }))} valueLabel={r => fmt3(r.v)} />
          </div>
        ) : <Notice>No per-subject breakdown in the benchmark file.</Notice>
      ) : <PanelFallback panel={panel} minHeight={120} />}
    </Panel>
  );
};

const SignalPanel = ({ panel }) => {
  const ok = panel.status === "ok" && Array.isArray(panel.axes);
  return (
    <Panel name="reranker_signal" state={panel.status} icon="scale" title="Ranking signals" sub={ok ? `Heuristic reranker weights (${panel.source || "weights"})` : null}>
      {ok ? <Bars labelWidth={160} rows={panel.axes.map(a => ({ key: a.signal, name: a.signal.replace(/_/g, " "), v: Number(a.weight) || 0, color: "var(--c-amber)" }))} valueLabel={r => String(r.v)} />
          : <PanelFallback panel={panel} minHeight={120} />}
    </Panel>
  );
};

const ModelsPanel = ({ panel }) => {
  const ok = panel.status === "ok" && Array.isArray(panel.versions);
  return (
    <Panel name="model_versions" state={panel.status} icon="server" title="Model versions" sub={ok ? `Registry updated ${panel.updated || "—"}` : null}>
      {ok ? (
        <Table testid="sfu-model-versions" cols={[
          { key: "component", label: "Component" },
          { key: "version", label: "Version" },
          { key: "date", label: "Date" },
          { key: "ndcg", label: "NDCG", num: true, render: r => r.ndcg == null ? "—" : fmt3(r.ndcg) },
          { key: "status", label: "Status" },
          { key: "available", label: "On disk", render: r => r.available == null ? "—" : (r.available ? "yes" : "no") },
        ]} rows={panel.versions} />
      ) : <PanelFallback panel={panel} minHeight={120} />}
    </Panel>
  );
};

const STUB_TITLES = {
  embedding_drift: { title: "Embedding drift", icon: "globe" },
  access_funnel: { title: "Access funnel", icon: "route" },
  oa_equity: { title: "Open-access equity", icon: "scale" },
};

const StubPanel = ({ name, panel }) => (
  <Panel name={name} state={panel.status} icon={STUB_TITLES[name].icon} title={STUB_TITLES[name].title}>
    {panel.status === "stub" || panel.status === "missing" || panel.status === "loading"
      ? <PanelFallback panel={panel} minHeight={40} />
      : <Notice>Status {String(panel.status)}: this page has no renderer for this panel's data yet.</Notice>}
  </Panel>
);

const sourceLabel = (s) => s === "gui" ? "search GUI sessions" : s === "server" ? "server-side impressions (MCP path)" : "no engagement rows yet";

const PositionBiasPanel = ({ panel }) => {
  const known = panel.status === "ok" || panel.status === "awaiting_click_data";
  const curve = known ? (panel.curve || []) : [];
  const shown = curve.filter(c => c.impressions || c.clicks);
  return (
    <Panel name="position_bias" state={panel.status} icon="chart" title="Position bias · P(click | rank)"
      sub={known ? `Counting ${sourceLabel(panel.source)} · ${fmtInt(panel.total_impressions)} impressions · ${fmtInt(panel.total_clicks)} clicks` : null}>
      {!known ? <PanelFallback panel={panel} minHeight={80} /> : (
        <>
          {panel.status === "awaiting_click_data" && (
            <Notice tone="warn" testid="sfu-awaiting-clicks">
              Awaiting click data: {fmtInt(panel.total_clicks)} of the {fmtInt(panel.min_clicks_required)} clicks needed before propensities are estimated. Rows below are raw counts only.
            </Notice>
          )}
          {shown.length ? (
            <Table testid="sfu-position-bias" cols={[
              { key: "rank", label: "Rank", num: true },
              { key: "impressions", label: "Impressions", num: true, render: r => fmtInt(r.impressions) },
              { key: "clicks", label: "Clicks", num: true, render: r => fmtInt(r.clicks) },
              { key: "click", label: "P(click)", num: true, render: r => fmt3(r.click) },
              { key: "propensity", label: "Propensity", num: true, render: r => r.propensity == null ? "—" : fmt3(r.propensity) },
            ]} rows={shown} />
          ) : <Notice>No impressions recorded yet. Searches made in the search app post them from first use.</Notice>}
          {panel.note && <p style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{panel.note}</p>}
        </>
      )}
    </Panel>
  );
};

const MAX_SESSIONS = 20;

const SessionReplayPanel = ({ panel }) => {
  const known = panel.status === "ok" || panel.status === "awaiting_click_data";
  const sessions = known ? (panel.sessions || []) : [];
  return (
    <Panel name="session_replay" state={panel.status} icon="history" title="Session replay"
      sub={known ? `Query → clicked result → actions, newest session first · ${sourceLabel(panel.source)}` : null}>
      {!known ? <PanelFallback panel={panel} minHeight={80} /> : sessions.length === 0 ? (
        <Notice tone="warn" testid="sfu-awaiting-sessions">Awaiting click data: no search sessions recorded yet.</Notice>
      ) : (
        <div data-testid="sfu-sessions" style={{ display: "flex", flexDirection: "column", gap: 12, maxHeight: 420, overflowY: "auto", paddingRight: 4 }}>
          {sessions.slice(0, MAX_SESSIONS).map(s => (
            <div key={s.session_id} data-session={s.session_id} style={{ border: "1px solid var(--border-light)", borderRadius: 8, padding: "10px 12px" }}>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 11.5, color: "var(--text-muted)", marginBottom: 6 }}>
                <span style={{ fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>{String(s.session_id).slice(0, 14)}</span>
                <span>{s.start ? String(s.start).replace("T", " ").slice(0, 16) : "—"}</span>
                <span>{s.n_queries} queries · {s.n_clicks} clicks · {s.n_actions} actions</span>
              </div>
              {(s.queries || []).map((q, qi) => (
                <div key={qi} style={{ marginBottom: 6 }}>
                  <div style={{ fontSize: 12.5, color: "var(--text)", overflowWrap: "anywhere" }}>
                    <Icon name="search" size={12} style={{ marginRight: 6, color: "var(--text-muted)" }} />
                    {q.query || "(no query text)"}
                    {q.refined_from && <span style={{ fontSize: 11, color: "var(--text-muted)" }}> · refined from “{q.refined_from}”</span>}
                  </div>
                  {(q.results || []).map((r, ri) => (
                    <div key={ri} style={{ marginLeft: 20, marginTop: 3, fontSize: 12, color: "var(--text-secondary)", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                      <span style={{ fontFamily: "var(--font-mono)" }}>#{r.rank == null ? "?" : r.rank}</span>
                      <span style={{ overflowWrap: "anywhere", minWidth: 0 }}>{r.doc_id || "(unknown doc)"}</span>
                      {(r.actions || []).map((a, ai) => (
                        <span key={ai} style={{ fontSize: 10.5, padding: "1px 6px", borderRadius: 4, background: "var(--c-teal-soft)", color: "oklch(34% 0.07 200)" }}>{a}</span>
                      ))}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ))}
          {sessions.length > MAX_SESSIONS && <p style={{ fontSize: 11.5, color: "var(--text-muted)" }}>{sessions.length - MAX_SESSIONS} older sessions not shown.</p>}
        </div>
      )}
    </Panel>
  );
};

const Collapsible = ({ icon, title, sub, testid, children }) => {
  const [open, setOpen] = React.useState(false);
  return (
    <section style={{ background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-sm)", overflow: "hidden" }}>
      <button data-testid={testid} aria-expanded={open} onClick={() => setOpen(o => !o)} style={{ width: "100%", display: "flex", alignItems: "center", gap: 13, padding: "18px 26px", border: "none", background: "transparent", textAlign: "left" }}>
        <span style={{ width: 32, height: 32, borderRadius: 8, background: "var(--bg-soft)", color: "var(--text-secondary)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <Icon name={icon} size={16} />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>{title}</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 1 }}>{sub}</div>
        </div>
        <Icon name={open ? "chevronDown" : "chevronRight"} size={16} style={{ color: "var(--text-muted)" }} />
      </button>
      {open && <div style={{ padding: "4px 26px 26px", display: "flex", flexDirection: "column", gap: 18 }}>{children}</div>}
    </section>
  );
};

const OperatorSection = ({ bundle, facts }) => {
  const kpis = panelOf(bundle, "kpis");
  return (
    <Collapsible testid="sfu-operator-toggle" icon="wrench" title="Operator & methodology" sub="Measured-quality metrics, ranking signals and model versions — for people maintaining or auditing the system.">
      <Notice tone="warn">
        These are engineering measurements, not a quality guarantee. A single NDCG figure says how well the ranker reproduced a labelled test set — it does <strong>not</strong> certify that any given search was complete or unbiased. The disclosures above are the honest answer to that question.
      </Notice>
      <QualityPanel kpis={kpis} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(280px, 100%), 1fr))", gap: 18 }}>
        <SubjectNdcgPanel panel={panelOf(bundle, "ndcg_by_subject")} k={kpis.k} />
        <SignalPanel panel={panelOf(bundle, "reranker_signal")} />
      </div>
      <ModelsPanel panel={panelOf(bundle, "model_versions")} />
      <div>
        <SubHead>Not wired yet</SubHead>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(240px, 100%), 1fr))", gap: 14 }}>
          {["embedding_drift", "access_funnel", "oa_equity"].map(n => <StubPanel key={n} name={n} panel={panelOf(bundle, n)} />)}
        </div>
      </div>
      <p style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.6, maxWidth: "78ch" }}>
        Retrieval legs are combined with Reciprocal Rank Fusion{facts.rrfK != null ? ` (k = ${facts.rrfK})` : ""}{facts.total != null ? ` over ${fmtInt(facts.total)} documents` : ""}.
        {facts.nSections != null ? ` The index is split into ${facts.nSections} sections (${facts.nSubjects} subject buckets × ${facts.nEras} eras${facts.boundary ? `, boundary ${facts.boundary}` : ""}).` : ""}
      </p>
    </Collapsible>
  );
};

const EngagementSection = ({ bundle }) => (
  <Collapsible testid="sfu-engagement-toggle" icon="history" title="Search engagement" sub="Click-through and session data posted by the search app — position bias and session replay.">
    <PositionBiasPanel panel={panelOf(bundle, "position_bias")} />
    <SessionReplayPanel panel={panelOf(bundle, "session_replay")} />
  </Collapsible>
);

const Facts = ({ facts, loading }) => {
  const v = (x) => loading ? "…" : x;
  const rows = [
    { label: "Documents", value: v(facts.total != null ? fmtInt(facts.total) : "—"), sub: facts.ok || loading ? "in the served index" : "index manifest unavailable" },
    { label: "Source", value: "OpenAlex", sub: v(facts.built ? "index built " + facts.built : "build date unavailable") },
    { label: "Sections", value: v(facts.nSections != null ? String(facts.nSections) : "—"), sub: v(facts.nSubjects != null ? `${facts.nSubjects} subjects × ${facts.nEras} eras` : "unavailable") },
    { label: "Era boundary", value: v(facts.boundary != null ? String(facts.boundary) : "—"), sub: "recent vs historical" },
  ];
  return (
    <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }} data-testid="sfu-facts">
      {rows.map(f => (
        <div key={f.label} style={{ flex: "1 1 200px", minWidth: 180, padding: "18px 22px", background: "var(--bg-panel)", border: "1px solid var(--border-light)", borderRadius: "var(--radius)", boxShadow: "var(--shadow-sm)" }}>
          <div style={{ fontSize: 11, fontWeight: 500, letterSpacing: "0.07em", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 7 }}>{f.label}</div>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 25, fontWeight: 500, color: "var(--text)", lineHeight: 1 }}>{f.value}</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 5, minHeight: 18 }}>{f.sub}</div>
        </div>
      ))}
    </div>
  );
};

const App = () => {
  const [bundle, setBundle] = React.useState(null);
  const [source, setSource] = React.useState(null);
  React.useEffect(() => {
    let cancelled = false;
    if (window.SFUApi && typeof window.SFUApi.analytics === "function") {
      window.SFUApi.analytics().then(res => {
        if (cancelled) return;
        setSource(res.source);
        setBundle(res && res.data && typeof res.data === "object" ? res.data : {});
      }).catch(() => { if (!cancelled) { setSource("mock"); setBundle({}); } });
    } else {
      setSource("mock");
      setBundle({});
    }
    return () => { cancelled = true; };
  }, []);
  const loading = bundle === null;
  const shape = panelOf(bundle, "index_shape");
  const facts = liveFacts(shape, panelOf(bundle, "reranker_signal"));
  const disclosures = buildDisclosures(facts);
  const goSearch = () => { if (window.parent !== window) window.parent.postMessage({ suiteNav: "search" }, "*"); else window.location.href = "search.html"; };
  return (
    <div style={{ display: "flex", height: "100%", minHeight: "100vh" }} data-screen-label="About this index" data-analytics-source={source || "pending"}>
      <SuiteSidebar app="analytics" active="analytics" />
      <main style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column", minWidth: 0 }}>
        <header style={{ padding: "32px 48px 28px", borderBottom: "1px solid var(--border-light)", background: "var(--bg-panel)" }}>
          <div style={{ fontSize: 11.5, fontWeight: 500, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-muted)", marginBottom: 8 }}>About this index</div>
          <h1 style={{ fontFamily: "var(--font-serif)", fontSize: 31, fontWeight: 500, color: "var(--text)", lineHeight: 1.15, marginBottom: 8, textWrap: "balance" }}>
            What the search reads from — and where it's thin
          </h1>
          <p style={{ fontSize: 14.5, color: "var(--text-secondary)", maxWidth: "72ch", lineHeight: 1.6 }}>
            Read this before treating a search as a complete picture of the literature. It describes the whole collection behind the search box — its single source, its language and discipline skew, and how it's split by era. The coverage card on each result set tells you which of these limits hit <em>your</em> specific search.
          </p>
          <button onClick={goSearch} style={{ marginTop: 18, display: "inline-flex", alignItems: "center", gap: 7, padding: "8px 14px", border: "1px solid var(--border)", borderRadius: 8, background: "var(--bg-panel)", fontSize: 13, color: "var(--text-secondary)" }}>
            <Icon name="arrowLeft" size={14} /> Back to search
          </button>
        </header>

        <div className="an-body" style={{ padding: "28px 48px 56px", display: "flex", flexDirection: "column", gap: 28, maxWidth: 1180, minWidth: 0 }}>
          <Facts facts={facts} loading={loading} />

          <div>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 16, marginBottom: 16, flexWrap: "wrap" }}>
              <h2 style={{ fontFamily: "var(--font-serif)", fontSize: 21, fontWeight: 500, color: "var(--text)" }}>Five things the collection won't tell you on its own</h2>
              <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Ordered by how easily they distort a literature review</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {disclosures.map((d, i) => <DisclosureCard key={d.id} d={d} n={i + 1} />)}
            </div>
          </div>

          <ShapeSection shape={shape} />

          <OperatorSection bundle={bundle} facts={facts} />
          <EngagementSection bundle={bundle} />

          <p style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", lineHeight: 1.6 }}>
            This page is linked from the <strong style={{ color: "var(--text-secondary)" }}>coverage card</strong> shown at the top of every result set.
          </p>
        </div>
      </main>
      <style>{`
        @media (max-width: 1024px) {
          .dist-grid { grid-template-columns: 1fr !important; }
          .disc-grid { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 640px) {
          .an-body { padding: 20px 16px 40px !important; }
        }
      `}</style>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
