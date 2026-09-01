
(function () {
  const BASE = ""; 
  
  
  
  
  
  const TIMEOUT_MS = 30000;

  function withTimeout(promise, ms) {
    let t;
    const timeout = new Promise((_, rej) => { t = setTimeout(() => rej(new Error("timeout")), ms); });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(t));
  }

  async function req(path, opts) {
    const res = await withTimeout(fetch(BASE + path, opts), TIMEOUT_MS);
    if (!res.ok) {
      
      
      
      
      
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

  
  
  const PAGE_SIZE = 10;
  const MAX_PAGES = 5;
  const MAX_RESULTS = PAGE_SIZE * MAX_PAGES;

  function clampPage(page) {
    const n = Math.floor(Number(page));
    if (!Number.isFinite(n) || n < 1) return 1;
    return Math.min(MAX_PAGES, n);
  }

  function pageLimit(page) {
    return Math.min(MAX_RESULTS, clampPage(page) * PAGE_SIZE);
  }

  function mergePages(prev, next) {
    const out = Array.isArray(prev) ? prev.slice() : [];
    const seen = new Set(out.map(r => r && r.id));
    (next || []).forEach(r => {
      if (!r || seen.has(r.id)) return;
      seen.add(r.id);
      out.push(r);
    });
    return out;
  }

  
  function buildSearchArgs(query, filters, page) {
    filters = filters || {};
    const args = { query: query, limit: pageLimit(page) };
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
    _online: null, 

    isOnline() { return this._online; },

    async health() {
      try {
        const data = await req("/health", { method: "GET" });
        this._online = true;
        
        
        
        
        
        return { data: data, source: "live", warm: data && data.warm !== undefined ? !!data.warm : true, sequential: !!(data && data.sequential) };
      } catch (e) {
        this._online = false;
        return { data: { status: "offline" }, source: "mock", warm: false, sequential: false };
      }
    },

    async search(query, filters, page) {
      const p = clampPage(page);
      const limit = pageLimit(p);
      try {
        const data = await req("/api/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildSearchArgs(query, filters, p)),
        });
        this._online = true;
        const raw = (data && data.results) || [];
        return {
          results: raw.map(normalizeResult),
          page: p,
          pageSize: PAGE_SIZE,
          hasMore: p < MAX_PAGES && raw.length >= limit,
          notes: (data && data.notes) || [],
          meta: (data && data.meta) || { count: raw.length },
          
          
          degraded: !!(data && data.degraded),
          degradedShards: (data && data.degraded_shards) || null,
          source: "live",
        };
      } catch (e) {
        
        
        if (e && e.status === 429 && Number.isFinite(e.retryAfter)) {
          return { source: "retry", retryAfter: e.retryAfter, page: p, pageSize: PAGE_SIZE, hasMore: false, results: [], notes: [], meta: { count: 0 } };
        }
        this._online = false;
        const all = (window.SFUMock && window.SFUMock.results) || [];
        const mock = all.slice(0, limit);
        return {
          results: mock,
          page: p,
          pageSize: PAGE_SIZE,
          hasMore: p < MAX_PAGES && all.length > mock.length,
          notes: [],
          meta: { count: all.length },
          source: "mock",
        };
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
      
      
      
      cancel();
      const norm = String(lastText).trim();
      if (!norm || norm.length < minLen) return { fired: false, reason: "short-input" };
      const t0 = _now();
      timer = _setTimeout(function () {
        timer = null;
        
        
        try {
          const p = speculate(lastText, filters);
          if (p && typeof p.catch === "function") p.catch(function () {  });
        } catch (e) {  }
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

  SFUApi.PAGE_SIZE = PAGE_SIZE;
  SFUApi.MAX_PAGES = MAX_PAGES;
  SFUApi.MAX_RESULTS = MAX_RESULTS;
  SFUApi.pageLimit = pageLimit;
  SFUApi.mergePages = mergePages;

  window.SFUApi = SFUApi;
  window.SFUApi.normalizeResult = normalizeResult;
})();
