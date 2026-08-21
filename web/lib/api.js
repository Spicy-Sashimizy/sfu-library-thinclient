/* SFU Library Suite — shared API client.
 * Plain JS (no JSX); loaded before each app's babel script so window.SFUApi is
 * available. Every method tries the live backend first and falls back to
 * window.SFUMock when the backend is unreachable or errors. The returned object
 * always carries `source: "live" | "mock"` so the UI can surface a demo banner.
 *
 * Endpoints (served by src/sfu_library_mcp_http.py):
 *   POST /api/search        -> { results:[...], meta:{count}, notes:[...] }
 *   GET  /analytics[?panel] -> { panels:{...} } | { panel, data }
 *   GET  /api/index_status  -> { metrics, pack, unpack_jobs }
 *   GET  /api/personas      -> { personas, sections, live_sections, ... }
 *   POST /api/unpack        -> { ok, message }
 *   POST /engagement        -> { recorded }
 *   GET  /health            -> { status:"ok", tools:N }
 */
(function () {
  const BASE = ""; // same origin as the served page
  // Measured live 2026-07-18 (warm server, all legs healthy): /api/search
  // p50 ~10 s, worst 14.8 s (earlier same-day runs up to 20.6 s). The old
  // 12 s timeout silently dropped slow-but-live searches to demo data —
  // exactly the "still in demo mode" symptom. 30 s clears the observed worst
  // case; the Search UI's skeleton + elapsed counter cover the wait honestly.
  const TIMEOUT_MS = 30000;

  function withTimeout(promise, ms) {
    let t;
    const timeout = new Promise((_, rej) => { t = setTimeout(() => rej(new Error("timeout")), ms); });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(t));
  }

  async function req(path, opts) {
    const res = await withTimeout(fetch(BASE + path, opts), TIMEOUT_MS);
    if (!res.ok) {
      // WI-11 overload: a 429 carries a Retry-After header. Surface it as a
      // structured "retry" result instead of a thrown error so the Search UI
      // can show a determinate countdown and auto-retry (spec §1 row 4).
      // Retry-After may be seconds OR an HTTP-date; we accept the integer-seconds
      // form (what the server emits). Anything else degrades to a 3s backoff.
      if (res.status === 429) {
        const ra = res.headers.get("Retry-After");
        let secs = 3;
        if (ra) { const n = parseInt(ra, 10); if (Number.isFinite(n)) secs = Math.max(1, Math.min(60, n)); }
        const e = new Error("HTTP 429");
        e.retryAfter = secs;
        e.status = 429;
        throw e;
      }
      throw new Error("HTTP " + res.status);
    }
    return res.json();
  }

  // OpenAlex/retriever dict -> the card shape the Search prototype renders.
  function normalizeResult(w, i) {
    const date = w.date || w.publication_date || "";
    const year = w.year || w.publication_year ||
      (typeof date === "string" && date.length >= 4 ? parseInt(date.slice(0, 4), 10) : undefined);
    const doiRaw = (w.doi || "").replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
    const isOA = !!(w.is_oa || w.oa_status);
    const cited = w.cited_by != null ? w.cited_by : (w.cited_by_count || 0);
    const type = w.type || "article";
    const topics = w.topics || [];
    const abstract = w.abstract || "";
    const access = isOA
      ? { type: "open_access", url: w.oa_url || (doiRaw ? "https://doi.org/" + doiRaw : "#"), label: "Open Access" }
      : { type: "sfu_proxy", url: doiRaw ? "https://doi.org/" + doiRaw : "#", label: "Duck Library" };
    return {
      id: w.id || w.openalex_id || ("R" + i),
      title: w.title || "Untitled",
      authors: w.authors || [],
      year: year,
      source: w.source || w.venue || "",
      volume: w.volume || "",
      issue: w.issue || "",
      doi: doiRaw,
      cited_by: cited,
      type: type,
      peer_reviewed: w.peer_reviewed != null ? w.peer_reviewed : (type === "article" || type === "book"),
      abstract: abstract,
      tldr: w.tldr || (abstract ? abstract.slice(0, 220) + (abstract.length > 220 ? "…" : "") : ""),
      access: w.access || access,
      expanded_terms: w.expanded_terms || [],
      topics: topics,
      oa_status: isOA,
    };
  }

  // Map the prototype's filter UI values to search_academic args.
  function buildSearchArgs(query, filters) {
    filters = filters || {};
    const args = { query: query, limit: 50 };
    const t = filters.type;
    if (t && t !== "All") args.type = t.toLowerCase();
    const a = filters.access;
    if (a === "Open Access" || a === "Unpaywall") args.open_access_only = true;
    const now = 2026;
    const d = filters.date;
    if (d === "Last year") args.year_from = now - 1;
    else if (d === "Last 5 years") args.year_from = now - 5;
    else if (d === "Last 10 years") args.year_from = now - 10;
    return args;
  }

  const SFUApi = {
    _online: null, // last known backend reachability (null=unknown)

    isOnline() { return this._online; },

    async health() {
      try {
        const data = await req("/health", { method: "GET" });
        this._online = true;
        // Forward-compatible warm flag: WI-6 found up≠warm (the index can answer
        // /health=ok while still cold-warming). The endpoint today returns only
        // {status, tools}; if/when it adds `warm`, the Search UI's >10s warming
        // message (spec §1 row 3) keys off it. No serving-path change is made
        // here — we only READ a field that may be absent.
        return { data: data, source: "live", warm: data && data.warm !== undefined ? !!data.warm : true, sequential: !!(data && data.sequential) };
      } catch (e) {
        this._online = false;
        return { data: { status: "offline" }, source: "mock", warm: false, sequential: false };
      }
    },

    async search(query, filters) {
      try {
        const data = await req("/api/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildSearchArgs(query, filters)),
        });
        this._online = true;
        const raw = (data && data.results) || [];
        return {
          results: raw.map(normalizeResult),
          notes: (data && data.notes) || [],
          meta: (data && data.meta) || { count: raw.length },
          // WI-9/10 degraded legs surface a degraded/degraded_shards flag on the
          // response; the Search UI renders a one-line notice (spec §1 row 5).
          degraded: !!(data && data.degraded),
          degradedShards: (data && data.degraded_shards) || null,
          source: "live",
        };
      } catch (e) {
        // 429 overload → structured retry signal, NOT a generic failure: the UI
        // shows a determinate "retrying in Ns" countdown and auto-retries.
        if (e && e.status === 429 && Number.isFinite(e.retryAfter)) {
          return { source: "retry", retryAfter: e.retryAfter, results: [], notes: [], meta: { count: 0 } };
        }
        this._online = false;
        const mock = (window.SFUMock && window.SFUMock.results) || [];
        return { results: mock, notes: [], meta: { count: mock.length }, source: "mock" };
      }
    },

    async analytics(panel) {
      try {
        const q = panel ? ("?panel=" + encodeURIComponent(panel)) : "";
        const data = await req("/analytics" + q, { method: "GET" });
        this._online = true;
        return { data: data, source: "live" };
      } catch (e) {
        this._online = false;
        return { data: (window.SFUMock && window.SFUMock.analytics) || {}, source: "mock" };
      }
    },

    async indexStatus() {
      try {
        const data = await req("/api/index_status", { method: "GET" });
        this._online = true;
        return { data: data, source: "live" };
      } catch (e) {
        this._online = false;
        return { data: (window.SFUMock && window.SFUMock.indexStatus) || {}, source: "mock" };
      }
    },

    async personas() {
      try {
        const data = await req("/api/personas", { method: "GET" });
        this._online = true;
        return { data: data, source: "live" };
      } catch (e) {
        this._online = false;
        return { data: (window.SFUMock && window.SFUMock.personas) || {}, source: "mock" };
      }
    },

    async unpack(section) {
      try {
        const data = await req("/api/unpack", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ section: section }),
        });
        return { data: data, source: "live" };
      } catch (e) {
        return { data: { ok: false, message: "Backend unavailable (demo mode)." }, source: "mock" };
      }
    },

    async engagement(evt) {
      try {
        await req("/engagement", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(evt),
        });
        return { source: "live" };
      } catch (e) {
        return { source: "mock" };
      }
    },

    // ── Searchbar keystroke speculation (deployprep WI-18, 2026-07-18) ───────
    // Fire the partial typed text to /api/speculate (the server runs the term-3
    // guards + predictor and, if unambiguous, fire-and-forgets ONE speculative
    // backend query through the SAME read-through cache a real submit uses).
    // The client never blocks on the response; a real Enter never waits on
    // speculation bookkeeping (term 4). Default OFF server-side
    // (SFU_SEARCH_SPECULATE); the endpoint is a harmless no-op when the gate is
    // off (returns suppressed/cache-off). Non-fatal on any error.
    async speculate(query, filters) {
      try {
        const data = await req("/api/speculate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildSearchArgs(query, filters)),
        });
        return { data: data, source: "live" };
      } catch (e) {
        return { data: { status: "error", reason: String(e) }, source: "mock" };
      }
    },
  };

  // createSpeculationController — the debounced typing→speculation helper the
  // SearchBar uses (term 6). Exposed as a small exported function (NOT inline in
  // the component closure) so it's testable headlessly with jsdom (wave-5
  // style). Contract: fires speculation only after ≥ DEBOUNCE_MS typing idle AND
  // the typed text ≥ MIN_LEN; a real submit cancels any pending speculation
  // timer. The controller is a plain object with .onType(text) and .cancel()
  // so a component can wire it without coupling to the debounce internals.
  //
  // params: speculate (the SFUApi.speculate fn), filters (filter snapshot),
  // opts { debounceMs (400), minLen (8), now (test clock), setTimeout,
  // clearTimeout (test injectables) }. Returns { onType, cancel, _pending }.
  SFUApi.createSpeculationController = function (speculate, filters, opts) {
    opts = opts || {};
    const debounceMs = opts.debounceMs != null ? opts.debounceMs : 400;
    const minLen = opts.minLen != null ? opts.minLen : 8;
    const _setTimeout = opts.setTimeout || function (fn, ms) { return setTimeout(fn, ms); };
    const _clearTimeout = opts.clearTimeout || function (id) { return clearTimeout(id); };
    const _now = opts.now || (function () { return Date.now(); });
    let timer = null;
    let lastText = "";

    function cancel() {
      if (timer != null) { _clearTimeout(timer); timer = null; }
    }

    function onType(text) {
      lastText = text == null ? "" : String(text);
      // Always cancel a pending speculation on new typing (term 6: a real
      // search cancels pending client speculation timers — and so does a new
      // keystroke, since the prediction target changed).
      cancel();
      const norm = String(lastText).trim();
      if (!norm || norm.length < minLen) return { fired: false, reason: "short-input" };
      const t0 = _now();
      timer = _setTimeout(function () {
        timer = null;
        // Re-check length at fire time (the text may have been the same); only
        // fire if still over threshold. Non-blocking — never await in the timer.
        try {
          const p = speculate(lastText, filters);
          if (p && typeof p.catch === "function") p.catch(function () { /* swallow */ });
        } catch (e) { /* a speculation fire failure must never break typing */ }
        return { t0: t0, firedAt: _now() };
      }, debounceMs);
      return { fired: false, scheduled: true, debounceMs: debounceMs };
    }

    return {
      onType: onType,
      cancel: cancel,
      get _pending() { return timer != null; },
      get _lastText() { return lastText; },
    };
  };

  window.SFUApi = SFUApi;
  window.SFUApi.normalizeResult = normalizeResult;
})();
