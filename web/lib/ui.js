/* SFU Library Suite — shared UI helpers (plain JS, no JSX).
 * Demo-data indicator: a compact FIXED pill (top-right) that overlays the UI
 * WITHOUT reflowing it — so toggling demo mode never shifts the layout. */
(function () {
  const PILL_ID = "sfu-demo-pill";
  const STYLE_ID = "sfu-demo-pill-style";

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = [
      "#" + PILL_ID + "{position:fixed;top:10px;right:12px;z-index:2147483000;",
      "display:flex;align-items:center;gap:7px;max-width:60vw;",
      "padding:6px 11px;border-radius:999px;",
      "font-family:'DM Sans',system-ui,sans-serif;font-size:12px;font-weight:500;",
      "color:oklch(30% 0.10 75);background:oklch(96% 0.05 75);",
      "border:1px solid oklch(82% 0.10 75);box-shadow:0 2px 8px oklch(0% 0 0 / 0.12);",
      "pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
      "#" + PILL_ID + " .sfu-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;",
      "background:oklch(68% 0.16 60);animation:sfu-pulse 1.6s ease-in-out infinite;}",
      "#" + PILL_ID + " b{font-weight:600;}",
      "@keyframes sfu-pulse{0%,100%{opacity:1}50%{opacity:0.3}}",
      "@media (prefers-reduced-motion: reduce){#" + PILL_ID + " .sfu-dot{animation:none}}",
    ].join("");
    document.head.appendChild(s);
  }

  // show=true renders the pill; show=false removes it. Idempotent. No reflow.
  function setMockBanner(show, message) {
    ensureStyle();
    const existing = document.getElementById(PILL_ID);
    if (!show) { if (existing) existing.remove(); return; }
    const full = message || "Showing sample results — live backend unavailable.";
    if (existing) { existing.title = full; return; }
    const pill = document.createElement("div");
    pill.id = PILL_ID;
    pill.setAttribute("role", "status");
    pill.title = full; // full explanation on hover
    pill.innerHTML = '<span class="sfu-dot"></span><b>Demo data</b>';
    document.body.appendChild(pill);
  }

  function reflectSource() {
    const anyMock = Array.prototype.slice.call(arguments).some(r => r && r.source === "mock");
    setMockBanner(anyMock);
    return anyMock;
  }

  window.SFUUI = { setMockBanner: setMockBanner, reflectSource: reflectSource };

  // Suite-wide demo state: the shell broadcasts {suiteDemo:bool} (after probing
  // /health) so the pill is IDENTICAL across every app. Standalone (opened
  // directly, not in the shell), self-probe /health once.
  window.addEventListener("message", function (e) {
    if (e.data && typeof e.data.suiteDemo === "boolean") setMockBanner(e.data.suiteDemo);
  });
  if (window.parent === window && window.SFUApi && window.SFUApi.health) {
    window.SFUApi.health().then(function (r) { setMockBanner(r.source === "mock"); }).catch(function () {});
  }
})();
