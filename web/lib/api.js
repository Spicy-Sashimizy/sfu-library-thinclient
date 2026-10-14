
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

  function shapeLive(data, p, limit) {
    noteSource("live");
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
      preliminary: !!(data && data.preliminary),
      source: "live",
    };
  }

  function mockPage(p, limit) {
    noteSource("mock");
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

  function parseSSE(buffer) {
    const events = [];
    let rest = String(buffer || "").replace(/\r\n/g, "\n");
    let idx;
    while ((idx = rest.indexOf("\n\n")) >= 0) {
      const block = rest.slice(0, idx);
      rest = rest.slice(idx + 2);
      let event = "message";
      const data = [];
      block.split("\n").forEach(function (line) {
        if (line.indexOf("event:") === 0) event = line.slice(6).trim();
        else if (line.indexOf("data:") === 0) data.push(line.slice(5).replace(/^ /, ""));
      });
      if (data.length) events.push({ event: event, data: data.join("\n") });
    }
    return { events: events, rest: rest };
  }

  function topIds(list, k) {
    return (list || []).slice(0, k).map(function (r) { return r && r.id; }).filter(function (x) { return x != null; });
  }

  function reshuffleRate(draft, final, k) {
    k = k || 10;
    const d = topIds(draft, k);
    if (!d.length) return 0;
    const f = new Set(topIds(final, k));
    let missing = 0;
    d.forEach(function (id) { if (!f.has(id)) missing++; });
    return missing / d.length;
  }

  const ENGAGEMENT_KINDS = ["query", "impression", "result_click", "action"];
  const ENGAGEMENT_ACTION_TYPES = ["abstract", "tldr", "pdf", "citation", "zotero", "save"];
  const ENGAGEMENT_SESSION_KEY = "sfu_engagement_session_v1";
  const ENGAGEMENT_FLUSH_MS = 2000;
  const ENGAGEMENT_MAX_BATCH = 50;
  const ENGAGEMENT_MAX_QUEUE = 500;
  const ENGAGEMENT_TEXT_MAX = 300;

  let backendMode = "unknown";
  function noteSource(source) {
    if (source === "live" || source === "mock") backendMode = source;
  }

  function engagementDocId(r) {
    if (!r) return "";
    const doi = String(r.doi || "").replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
    return doi || String(r.openalex_id || r.id || "");
  }

  function shapeEngagementEvent(ev, nowIso) {
    if (!ev || typeof ev !== "object") return null;
    const sid = String(ev.session_id == null ? "" : ev.session_id).trim();
    const kind = String(ev.kind == null ? "" : ev.kind).trim();
    if (!sid || ENGAGEMENT_KINDS.indexOf(kind) < 0) return null;
    const out = { ts: String(ev.ts || nowIso || new Date().toISOString()), session_id: sid, kind: kind };
    if (ev.query != null) out.query = String(ev.query).slice(0, ENGAGEMENT_TEXT_MAX);
    if (ev.doc_id != null && ev.doc_id !== "") out.doc_id = String(ev.doc_id);
    if (ev.rank != null) {
      const n = Number(ev.rank);
      if (!Number.isInteger(n)) return null;
      out.rank = n;
    }
    if (kind === "action") {
      const at = String(ev.action_type == null ? "" : ev.action_type).trim();
      if (ENGAGEMENT_ACTION_TYPES.indexOf(at) < 0) return null;
      out.action_type = at;
    }
    if (ev.refined_from != null && ev.refined_from !== "") out.refined_from = String(ev.refined_from).slice(0, ENGAGEMENT_TEXT_MAX);
    return out;
  }

  function createEngagementQueue(opts) {
    opts = opts || {};
    const maxBatch = opts.maxBatch || ENGAGEMENT_MAX_BATCH;
    const maxQueue = opts.maxQueue || ENGAGEMENT_MAX_QUEUE;
    const delayMs = opts.delayMs != null ? opts.delayMs : ENGAGEMENT_FLUSH_MS;
    const send = typeof opts.send === "function" ? opts.send : function () {};
    const _setTimeout = opts.setTimeout || function (fn, ms) { return setTimeout(fn, ms); };
    const _clearTimeout = opts.clearTimeout || function (id) { return clearTimeout(id); };
    const _now = opts.now || function () { return new Date().toISOString(); };
    let queue = [];
    let timer = null;
    let dropped = 0;

    function clear() { if (timer != null) { _clearTimeout(timer); timer = null; } }
    function drain() {
      const batches = [];
      while (queue.length) batches.push({ events: queue.splice(0, maxBatch) });
      return batches;
    }
    function flush(reason) {
      clear();
      const batches = drain();
      batches.forEach(function (b) { try { send(b, reason || "timer"); } catch (e) {  } });
      return batches.length;
    }
    function push(ev) {
      const shaped = shapeEngagementEvent(ev, _now());
      if (!shaped) return false;
      if (queue.length >= maxQueue) { queue.shift(); dropped++; }
      queue.push(shaped);
      if (queue.length >= maxBatch) flush("full");
      else if (timer == null) timer = _setTimeout(function () { timer = null; flush("timer"); }, delayMs);
      return true;
    }
    return {
      push: push,
      flush: flush,
      drain: drain,
      get size() { return queue.length; },
      get pending() { return timer != null; },
      get dropped() { return dropped; },
    };
  }

  function randomId() {
    try {
      const c = window.crypto;
      if (c && typeof c.getRandomValues === "function") {
        const a = new Uint8Array(12);
        c.getRandomValues(a);
        return "g-" + Array.prototype.map.call(a, function (b) { return (b < 16 ? "0" : "") + b.toString(16); }).join("");
      }
    } catch (e) {  }
    return "g-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }

  let engagementSid = null;
  function engagementSessionId() {
    if (engagementSid) return engagementSid;
    let sid = null;
    try { sid = window.sessionStorage.getItem(ENGAGEMENT_SESSION_KEY); } catch (e) { sid = null; }
    if (!sid) {
      sid = randomId();
      try { window.sessionStorage.setItem(ENGAGEMENT_SESSION_KEY, sid); } catch (e) {  }
    }
    engagementSid = sid;
    return sid;
  }

  function postEngagement(batch, reason) {
    const body = JSON.stringify(batch);
    const url = BASE + "/engagement";
    if (reason === "pagehide") {
      try {
        if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function"
            && navigator.sendBeacon(url, new Blob([body], { type: "application/json" }))) return;
      } catch (e) {  }
    }
    try {
      const p = fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body, keepalive: true });
      if (p && typeof p.catch === "function") p.catch(function () {  });
    } catch (e) {  }
  }

  const engagementQueue = createEngagementQueue({ send: postEngagement });
  const engagementCtx = { query: null, lastQuery: null, shown: {}, impressed: {} };

  function track(ev) {
    try {
      if (backendMode !== "live") return false;
      ev.session_id = engagementSessionId();
      return engagementQueue.push(ev);
    } catch (e) {
      return false;
    }
  }

  const engagement = {
    KINDS: ENGAGEMENT_KINDS.slice(),
    ACTION_TYPES: ENGAGEMENT_ACTION_TYPES.slice(),
    docId: engagementDocId,
    sessionId: engagementSessionId,
    shapeEvent: shapeEngagementEvent,
    mode: function () { return backendMode; },
    query: function (q) {
      try {
        const text = String(q == null ? "" : q).trim();
        if (!text) return false;
        const prev = engagementCtx.lastQuery;
        engagementCtx.query = text;
        engagementCtx.lastQuery = text;
        engagementCtx.shown = {};
        engagementCtx.impressed = {};
        return track({ kind: "query", query: text, refined_from: prev && prev !== text ? prev : null });
      } catch (e) { return false; }
    },
    impressions: function (q, results) {
      let n = 0;
      try {
        const text = String(q == null ? (engagementCtx.query || "") : q).trim();
        (results || []).forEach(function (r, i) {
          if (!r) return;
          const docId = engagementDocId(r);
          engagementCtx.shown[r.id] = { rank: i + 1, doc_id: docId, query: text };
          const key = text + "\u0001" + docId;
          if (engagementCtx.impressed[key]) return;
          if (track({ kind: "impression", query: text, rank: i + 1, doc_id: docId })) {
            engagementCtx.impressed[key] = true;
            n++;
          }
        });
      } catch (e) {  }
      return n;
    },
    click: function (result) {
      try {
        const c = (result && engagementCtx.shown[result.id]) || null;
        return track({ kind: "result_click", query: c ? c.query : null, rank: c ? c.rank : null, doc_id: c ? c.doc_id : engagementDocId(result) });
      } catch (e) { return false; }
    },
    action: function (result, actionType) {
      try {
        if (ENGAGEMENT_ACTION_TYPES.indexOf(actionType) < 0) return false;
        const c = (result && engagementCtx.shown[result.id]) || null;
        return track({ kind: "action", action_type: actionType, query: c ? c.query : null, rank: c ? c.rank : null, doc_id: c ? c.doc_id : engagementDocId(result) });
      } catch (e) { return false; }
    },
    flush: function (reason) { try { return engagementQueue.flush(reason); } catch (e) { return 0; } },
    pending: function () { return engagementQueue.size; },
  };

  try {
    window.addEventListener("pagehide", function () { engagement.flush("pagehide"); });
  } catch (e) {  }

  const draftStats = { streams: 0, drafts: 0, finalOnly: 0, fallbacks: 0, swaps: 0, pinnedSwaps: 0, reshuffleN: 0, reshuffleSum: 0, lastReshuffle: null };

  function recordReshuffle(rate) {
    draftStats.reshuffleN++;
    draftStats.reshuffleSum += rate;
    draftStats.lastReshuffle = rate;
  }

  const SFUApi = {
    async health() {
      try {
        const data = await req("/health", { method: "GET" });
        
        
        
        
        
        noteSource("live");
        return { data: data, source: "live", warm: data && data.warm !== undefined ? !!data.warm : true, sequential: !!(data && data.sequential), draftStream: !!(data && data.search_draft_stream) && !(data && data.sequential) };
      } catch (e) {
        noteSource("mock");
        return { data: { status: "offline" }, source: "mock", warm: false, sequential: false, draftStream: false };
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
        return shapeLive(data, p, limit);
      } catch (e) {
        
        
        if (e && e.status === 429 && Number.isFinite(e.retryAfter)) {
          return { source: "retry", retryAfter: e.retryAfter, page: p, pageSize: PAGE_SIZE, hasMore: false, results: [], notes: [], meta: { count: 0 } };
        }
        return mockPage(p, limit);
      }
    },

    async searchStream(query, filters, page, onDraft) {
      const p = clampPage(page);
      const limit = pageLimit(p);
      draftStats.streams++;
      let res;
      try {
        res = await withTimeout(fetch(BASE + "/api/search_stream", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
          body: JSON.stringify(buildSearchArgs(query, filters, p)),
        }), TIMEOUT_MS);
      } catch (e) {
        res = null;
      }
      if (res && res.status === 429) {
        const ra = res.headers && res.headers.get ? res.headers.get("Retry-After") : null;
        let secs = 3;
        if (ra) { const n = parseInt(ra, 10); if (Number.isFinite(n)) secs = Math.max(1, Math.min(60, n)); }
        return { source: "retry", retryAfter: secs, page: p, pageSize: PAGE_SIZE, hasMore: false, results: [], notes: [], meta: { count: 0 } };
      }
      if (!res || !res.ok || !res.body || typeof res.body.getReader !== "function") {
        draftStats.fallbacks++;
        return this.search(query, filters, p);
      }
      let sawDraft = false;
      const run = async function () {
        const reader = res.body.getReader();
        const dec = typeof TextDecoder !== "undefined" ? new TextDecoder() : null;
        let buf = "";
        for (;;) {
          const chunk = await reader.read();
          if (chunk.done) break;
          const v = chunk.value;
          buf += typeof v === "string" ? v : (dec ? dec.decode(v, { stream: true }) : String(v));
          const parsed = parseSSE(buf);
          buf = parsed.rest;
          for (let i = 0; i < parsed.events.length; i++) {
            const ev = parsed.events[i];
            if (ev.event === "draft") {
              sawDraft = true;
              draftStats.drafts++;
              if (typeof onDraft === "function") {
                try { onDraft(shapeLive(JSON.parse(ev.data), p, limit)); } catch (e) {  }
              }
            } else if (ev.event === "final") {
              try { reader.cancel && reader.cancel(); } catch (e) {  }
              return JSON.parse(ev.data);
            } else if (ev.event === "error") {
              throw new Error("stream error");
            }
          }
        }
        throw new Error("stream ended without final");
      };
      try {
        const data = await withTimeout(run(), TIMEOUT_MS);
        if (!sawDraft) draftStats.finalOnly++;
        const out = shapeLive(data, p, limit);
        out.hadDraft = sawDraft;
        return out;
      } catch (e) {
        const out = mockPage(p, limit);
        out.hadDraft = sawDraft;
        return out;
      }
    },

    async analytics(panel) {
      try {
        const q = panel ? ("?panel=" + encodeURIComponent(panel)) : "";
        const data = await req("/analytics" + q, { method: "GET" });
        return { data: data, source: "live" };
      } catch (e) {
        return { data: (window.SFUMock && window.SFUMock.analytics) || {}, source: "mock" };
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

  SFUApi.createDraftSwapController = function (opts) {
    opts = opts || {};
    const idleMs = opts.idleMs != null ? opts.idleMs : 1200;
    const apply = typeof opts.apply === "function" ? opts.apply : function () {};
    const isSelecting = typeof opts.isSelecting === "function" ? opts.isSelecting : function () { return false; };
    const _setTimeout = opts.setTimeout || function (fn, ms) { return setTimeout(fn, ms); };
    const _clearTimeout = opts.clearTimeout || function (id) { return clearTimeout(id); };
    const _now = opts.now || (function () { return Date.now(); });
    let displayed = [];
    let draftList = null;
    let finalList = null;
    let hovered = null;
    let lastActivity = -Infinity;
    let timer = null;
    let state = "idle";
    let reshuffle = null;

    function clear() { if (timer != null) { _clearTimeout(timer); timer = null; } }
    function schedule(ms) {
      clear();
      timer = _setTimeout(function () { timer = null; trySwap(); }, Math.max(0, ms));
    }
    function indexOfId(list, id) {
      for (let i = 0; i < list.length; i++) if (list[i] && list[i].id === id) return i;
      return -1;
    }
    function trySwap() {
      if (!finalList || (state !== "draft" && state !== "pinned")) return;
      const quiet = _now() - lastActivity;
      if (quiet < idleMs) { schedule(idleMs - quiet); return; }
      if (isSelecting()) { lastActivity = _now(); schedule(idleMs); return; }
      let next = finalList;
      let pinned = null;
      if (hovered != null) {
        const cur = indexOfId(displayed, hovered);
        if (cur >= 0) {
          const fi = indexOfId(finalList, hovered);
          if (fi < 0) return;
          if (fi !== cur) {
            next = finalList.filter(function (_, i) { return i !== fi; });
            next.splice(Math.min(cur, next.length), 0, finalList[fi]);
            pinned = hovered;
          }
        }
      }
      const fromDraft = state === "draft";
      displayed = next;
      state = pinned != null ? "pinned" : "final";
      if (fromDraft) { draftStats.swaps++; if (pinned != null) draftStats.pinnedSwaps++; }
      apply(next.slice(), { state: state, pinned: pinned, reshuffle: reshuffle });
    }

    return {
      showDraft: function (list) {
        clear();
        draftList = (list || []).slice();
        displayed = draftList;
        finalList = null;
        reshuffle = null;
        state = "draft";
        apply(displayed.slice(), { state: "draft", pinned: null, reshuffle: null });
      },
      offerFinal: function (list) {
        finalList = (list || []).slice();
        if (state === "idle" || state === "final") {
          clear();
          displayed = finalList;
          state = "final";
          apply(finalList.slice(), { state: "final", pinned: null, reshuffle: null });
          return;
        }
        if (reshuffle == null && draftList) {
          reshuffle = reshuffleRate(draftList, finalList, 10);
          recordReshuffle(reshuffle);
        }
        trySwap();
      },
      noteActivity: function () {
        lastActivity = _now();
        if (finalList && (state === "draft" || state === "pinned")) schedule(idleMs);
      },
      setHovered: function (id) {
        hovered = id == null ? null : id;
        lastActivity = _now();
        if (finalList && (state === "draft" || state === "pinned")) schedule(idleMs);
      },
      cancel: function () { clear(); state = "idle"; finalList = null; draftList = null; },
      get state() { return state; },
      get reshuffle() { return reshuffle; },
      get _pending() { return timer != null; },
    };
  };

  SFUApi.draftStreamStats = function () {
    const out = {};
    Object.keys(draftStats).forEach(function (k) { out[k] = draftStats[k]; });
    out.reshuffleMean = draftStats.reshuffleN ? draftStats.reshuffleSum / draftStats.reshuffleN : null;
    return out;
  };
  SFUApi.engagement = engagement;
  SFUApi.createEngagementQueue = createEngagementQueue;
  SFUApi.reshuffleRate = reshuffleRate;
  SFUApi.parseSSE = parseSSE;

  SFUApi.PAGE_SIZE = PAGE_SIZE;
  SFUApi.MAX_PAGES = MAX_PAGES;
  SFUApi.MAX_RESULTS = MAX_RESULTS;
  SFUApi.pageLimit = pageLimit;
  SFUApi.mergePages = mergePages;

  window.SFUApi = SFUApi;
})();
