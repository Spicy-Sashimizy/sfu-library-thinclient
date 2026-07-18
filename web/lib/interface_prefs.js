/* SFU Library Suite — bare-bones Interface preferences (spec §2 Tier 2).
 * Plain JS (no JSX); loaded before each app's compiled script so window.SFUUI
 * exposes useInterfacePrefs (a React hook callback you call) plus helpers.
 *
 * Progressive disclosure: the default screen is Tier-0 minimal (search box,
 * results list, one status line). Everything else is one interaction away
 * (Tier-1 filters expander, per-result detail) or a Settings → "Interface"
 * toggle (Tier-2), persisted in localStorage so it survives reload.
 *
 * INTEGRITY FLOOR (never toggleable / never hidden): the demo-data honesty
 * banner, degraded notices, and the backend pill. Reliability signals are not
 * clutter. These have NO entry in PREF_DEFAULTS by design.
 */
(function () {
  var KEY = "sfu-interface-prefs";

  // Defaults are ALL OFF / comfortable (spec §2 toggle table) EXCEPT
  // savedHistoryNav (ON since 2026-07-18 — owner wants history always in
  // reach; still toggleable) and the integrity-floor items, which are
  // deliberately absent → unhideable.
  var PREF_DEFAULTS = {
    advancedFiltersOpen: false, // Tier-1 filters row always open (default: collapsed)
    savedHistoryNav: true,      // Saved & History nav (default: shown)
    databasesTab: false,       // Databases tab
    analyticsApp: false,        // Analytics app (suite nav)
    indexManagerApp: false,    // Index Manager app (suite nav)
    adminPanels: false,         // Admin/operator panels
    density: "comfortable"      // comfortable | compact
  };

  function read() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return Object.assign({}, PREF_DEFAULTS);
      var parsed = JSON.parse(raw);
      // Merge over defaults so new keys added later fall back gracefully,
      // and any unknown/foreign keys are dropped.
      var out = {};
      Object.keys(PREF_DEFAULTS).forEach(function (k) {
        if (parsed && typeof parsed[k] === typeof PREF_DEFAULTS[k]) out[k] = parsed[k];
        else out[k] = PREF_DEFAULTS[k];
      });
      return out;
    } catch (e) { return Object.assign({}, PREF_DEFAULTS); }
  }

  function write(prefs) {
    try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) {}
    // Broadcast so the suite shell / other tabs keep hidden apps unmounted in
    // lockstep (spec §2 constraint: suite shell must NOT mount iframes for
    // toggled-off apps). The shell listens for this in suite.html.
    try { window.parent.postMessage({ suiteInterfacePrefs: prefs }, "*"); } catch (e) {}
  }

  // React hook: returns [prefs, setPref]. setPref(key, value) persists one key.
  // React must be loaded already (this module loads after react.production.min).
  function useInterfacePrefs() {
    var React = window.React;
    var s = React.useState(read);
    var prefs = s[0], setPrefs = s[1];
    var setPref = React.useCallback(function (key, value) {
      setPrefs(function (prev) {
        var next = Object.assign({}, prev);
        next[key] = value;
        write(next);
        return next;
      });
    }, []);
    // Re-sync if another tab/window changes prefs (e.g. the suite shell).
    React.useEffect(function () {
      var onStorage = function (e) { if (e.key === KEY) setPrefs(read()); };
      window.addEventListener("storage", onStorage);
      return function () { window.removeEventListener("storage", onStorage); };
    }, []);
    return [prefs, setPref];
  }

  // Non-hook helpers for the suite shell (plain JS, no React).
  window.SFUUI = window.SFUUI || {};
  window.SFUUI.INTERFACE_PREF_DEFAULTS = PREF_DEFAULTS;
  window.SFUUI.readInterfacePrefs = read;
  window.SFUUI.writeInterfacePrefs = write;
  window.SFUUI.useInterfacePrefs = useInterfacePrefs;
})();
