"""Static HTML for the /architecture explainer page (federated query trace).

Served by app.py at GET /architecture — no auth required; linked from
the waiting room so users can explore the system while the backend wakes.
"""

_BACK_BAR = """\
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
.arch-back{position:sticky;top:0;z-index:999;background:#0d1825;
border-bottom:1.5px solid #1a2d42;padding:10px 20px;display:flex;
align-items:center;gap:14px;font-family:ui-monospace,Menlo,monospace;font-size:11px}
.arch-back a{color:#38bdf8;text-decoration:none;font-weight:600;letter-spacing:.04em}
.arch-back a:hover{text-decoration:underline}
.arch-back .div{color:#1a2d42;margin:0 4px}
.arch-back .title{color:#5080a8}
</style>
</head><body style="margin:0;padding:0">
<div class="arch-back">
<a href="javascript:history.back()">&#8592; Back</a>
<span class="div">|</span>
<span class="title">Duck Library &mdash; Federated Query Trace</span>
</div>
"""

_CLOSE = "</body></html>"


_BODY = """
<title>Federated Query Trace</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;1,400&family=Inter:wght@300;400;500;600&display=swap">

<style>
:root {
  --bg:    #f0f6fc; --surf:  #ffffff; --surf2: #e8f1fa; --bd: #c6d8ec;
  --tx:    #0b1929; --tx2:   #4a6882; --tx3:   #8aaac8;
  --q:  #0369a1; --sp: #4338ca; --bm: #047857; --fu: #b45309; --re: #be185d; --ca: #0f766e;
  --sh-bg: #f3f8fd; --sh-bd: #cddcec; --sh-abg: #eef2ff; --sh-abd: #4f46e5; --sh-gl: rgba(79,70,229,.1);
  --bm-gl: rgba(4,120,87,.1); --fu-gl: rgba(180,83,9,.1); --re-gl: rgba(190,24,93,.1);
  --q-gl: rgba(3,105,161,.1); --ca-gl: rgba(15,118,110,.12); --ln: #cddcec;
  --warn: #b45309; --warn-bg: #fffbeb; --warn-bd: #fcd34d;
  --danger: #be185d; --safe: #047857;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#080e18; --surf:#0d1825; --surf2:#111e2e; --bd:#1a2d42;
    --tx:#d8e8f8; --tx2:#5080a8; --tx3:#2a4a68;
    --q:#38bdf8; --sp:#818cf8; --bm:#34d399; --fu:#fbbf24; --re:#fb7185; --ca:#2dd4bf;
    --sh-bg:#0d1825; --sh-bd:#1a2d42; --sh-abg:#13163a; --sh-abd:#818cf8; --sh-gl:rgba(129,140,248,.18);
    --bm-gl:rgba(52,211,153,.12); --fu-gl:rgba(251,191,36,.1); --re-gl:rgba(251,113,133,.1);
    --q-gl:rgba(56,189,248,.12); --ca-gl:rgba(45,212,191,.12); --ln:#1a2d42;
    --warn:#fbbf24; --warn-bg:#1c1200; --warn-bd:#854d0e; --danger:#fb7185; --safe:#34d399;
  }
}
:root[data-theme="dark"] {
  --bg:#080e18; --surf:#0d1825; --surf2:#111e2e; --bd:#1a2d42;
  --tx:#d8e8f8; --tx2:#5080a8; --tx3:#2a4a68;
  --q:#38bdf8; --sp:#818cf8; --bm:#34d399; --fu:#fbbf24; --re:#fb7185; --ca:#2dd4bf;
  --sh-bg:#0d1825; --sh-bd:#1a2d42; --sh-abg:#13163a; --sh-abd:#818cf8; --sh-gl:rgba(129,140,248,.18);
  --bm-gl:rgba(52,211,153,.12); --fu-gl:rgba(251,191,36,.1); --re-gl:rgba(251,113,133,.1);
  --q-gl:rgba(56,189,248,.12); --ca-gl:rgba(45,212,191,.12); --ln:#1a2d42;
  --warn:#fbbf24; --warn-bg:#1c1200; --warn-bd:#854d0e; --danger:#fb7185; --safe:#34d399;
}

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;padding:24px 18px 60px}

/* sysbar */
.sysbar{display:flex;align-items:center;gap:6px;font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--tx2);margin-bottom:24px;flex-wrap:wrap}
.live{width:6px;height:6px;border-radius:50%;background:var(--bm);flex-shrink:0;animation:blink 2.4s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
.div2{color:var(--tx3);margin:0 5px}
.sysbar strong{color:var(--tx);font-weight:500}

/* deploy profile card */
.profile-card{width:100%;max-width:960px;margin:0 auto 22px;background:var(--surf);border:1.5px solid var(--bd);border-radius:12px;overflow:hidden}
.profile-head{display:flex;align-items:center;gap:0;border-bottom:1.5px solid var(--bd)}
.scenario-btn{flex:1;padding:10px 0;font-family:'JetBrains Mono',monospace;font-size:10.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;background:transparent;border:none;color:var(--tx2);cursor:pointer;transition:background .15s,color .15s;border-right:1px solid var(--bd)}
.scenario-btn:last-child{border-right:none}
.scenario-btn.active{background:var(--surf2);color:var(--tx)}
.scenario-btn:hover:not(.active){background:var(--surf2)}

.profile-body{padding:14px 16px;display:grid;grid-template-columns:1fr auto;gap:12px;align-items:start}
.ram-section{display:flex;flex-direction:column;gap:8px}
.ram-label{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--tx2);letter-spacing:.07em;text-transform:uppercase;display:flex;justify-content:space-between}
.ram-label span{color:var(--tx);font-weight:600}
input[type=range]{width:100%;accent-color:var(--sp);cursor:pointer;height:18px}
.ram-zones{display:flex;height:4px;border-radius:2px;overflow:hidden;margin-top:2px}
.rz{flex:1}
.rz-danger{background:var(--danger);opacity:.5}
.rz-warn{background:var(--warn);opacity:.6}
.rz-ok{background:var(--safe);opacity:.5}

.profile-stats{display:flex;flex-direction:column;gap:6px;min-width:180px}
.pstat{display:flex;justify-content:space-between;gap:16px;font-family:'JetBrains Mono',monospace;font-size:10px}
.pstat-k{color:var(--tx2)}
.pstat-v{color:var(--tx);font-weight:600;font-variant-numeric:tabular-nums;text-align:right}
.pstat-v.warn{color:var(--warn)}
.pstat-v.danger{color:var(--danger)}
.pstat-v.ok{color:var(--safe)}
.profile-note{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tx3);margin-top:2px;line-height:1.5;grid-column:1/-1}

/* main pipeline */
.pipe{max-width:960px;margin:0 auto;display:flex;flex-direction:column;align-items:center}

/* query row */
.qrow{width:100%;display:flex;gap:8px;align-items:center}
.qinput{flex:1;font-family:'Inter',sans-serif;font-size:14px;background:var(--surf);border:1.5px solid var(--bd);border-radius:9px;padding:10px 14px;color:var(--tx);outline:none;transition:border-color .2s,box-shadow .2s}
.qinput:focus{border-color:var(--q);box-shadow:0 0 0 3px var(--q-gl)}
.qbtn{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;letter-spacing:.06em;background:var(--q);color:#fff;border:none;border-radius:9px;padding:10px 18px;cursor:pointer;transition:opacity .15s,transform .1s;white-space:nowrap}
.qbtn:hover{opacity:.88}
.qbtn:active{transform:scale(.97)}
.qbtn:disabled{opacity:.35;cursor:not-allowed}
.cache-toggle{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:600;letter-spacing:.05em;background:var(--surf2);color:var(--tx2);border:1.5px solid var(--bd);border-radius:9px;padding:10px 14px;cursor:pointer;transition:background .15s,color .15s,border-color .15s;white-space:nowrap;user-select:none}
.cache-toggle.on{background:var(--ca);color:#fff;border-color:var(--ca)}

/* arrows */
.arrow{width:1.5px;height:26px;background:var(--ln);position:relative;flex-shrink:0;transition:background .3s}
.arrow::after{content:'';position:absolute;bottom:-5px;left:50%;transform:translateX(-50%);border:5px solid transparent;border-top:6px solid var(--ln);border-bottom:none;transition:border-top-color .3s}
.arrow.lit{background:var(--q)}.arrow.lit::after{border-top-color:var(--q)}
.arrow.lit-sp{background:var(--sp)}.arrow.lit-sp::after{border-top-color:var(--sp)}
.arrow.lit-bm{background:var(--bm)}.arrow.lit-bm::after{border-top-color:var(--bm)}
.arrow.lit-fu{background:var(--fu)}.arrow.lit-fu::after{border-top-color:var(--fu)}
.arrow.lit-re{background:var(--re)}.arrow.lit-re::after{border-top-color:var(--re)}
.arrow.lit-ca{background:var(--ca)}.arrow.lit-ca::after{border-top-color:var(--ca)}

/* stages */
.stage{width:100%;background:var(--surf);border:1.5px solid var(--bd);border-radius:11px;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;transition:border-color .3s,box-shadow .3s,opacity .3s}
.stage.act-q{border-color:var(--q);box-shadow:0 0 0 3px var(--q-gl)}
.stage.act-ca{border-color:var(--ca);box-shadow:0 0 0 3px var(--ca-gl)}
.stage.act-fu{border-color:var(--fu);box-shadow:0 0 0 3px var(--fu-gl)}
.stage.act-re{border-color:var(--re);box-shadow:0 0 0 3px var(--re-gl)}
.stage.dimmed{opacity:.28}

.s-left{display:flex;flex-direction:column;gap:3px}
.s-eyebrow{font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--tx2)}
.s-name{font-size:14px;font-weight:600;color:var(--tx)}
.s-meta{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--tx3);line-height:1.65}
.s-lat{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--tx2);opacity:0;transition:opacity .3s;text-align:right}
.s-lat.show{opacity:1}
.s-hit{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;color:var(--ca);opacity:0;transition:opacity .3s;text-align:right}
.s-hit.show{opacity:1}

.tag{display:inline-block;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;letter-spacing:.07em;padding:2px 7px;border-radius:4px;color:#fff}
.tq{background:var(--q)}.tsp{background:var(--sp)}.tbm{background:var(--bm)}.tfu{background:var(--fu)}.tre{background:var(--re)}.tca{background:var(--ca)}

/* par label */
.par-label{width:100%;display:flex;align-items:center;gap:12px;font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--tx3);transition:opacity .3s}
.par-label.dimmed{opacity:.2}
.par-label::before,.par-label::after{content:'';flex:1;height:1px;background:var(--ln)}

/* split */
.split{width:100%;display:grid;grid-template-columns:3fr 2fr;gap:14px;align-items:start;transition:opacity .3s}
.split.dimmed{opacity:.2}

.leg{display:flex;flex-direction:column;align-items:center;gap:0}
.leg-head{width:100%;display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--surf2);border:1.5px solid var(--bd);border-radius:9px;transition:border-color .3s,box-shadow .3s}
.leg-head.act-sp{border-color:var(--sp);box-shadow:0 0 0 3px var(--sh-gl)}
.leg-head.act-bm{border-color:var(--bm);box-shadow:0 0 0 3px var(--bm-gl)}
.lh-icon{width:28px;height:28px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;flex-shrink:0;color:#fff}
.isp{background:var(--sp)}.ibm{background:var(--bm)}
.lh-info{flex:1;min-width:0}
.lh-name{font-size:12.5px;font-weight:600;color:var(--tx);line-height:1.2}
.lh-sub{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tx2);margin-top:1px}
.lh-lat{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--tx2);opacity:0;transition:opacity .3s;text-align:right}
.lh-lat.show{opacity:1}

/* shard grid */
.shard-grid{width:100%;display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}
.shard{background:var(--sh-bg);border:1.5px solid var(--sh-bd);border-radius:8px;padding:8px 9px;font-family:'JetBrains Mono',monospace;transition:background .25s,border-color .25s,box-shadow .25s,transform .2s;position:relative;overflow:hidden}
.shard::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--sh-abd);transform:scaleX(0);transform-origin:left;transition:transform .45s ease}
.shard.act{background:var(--sh-abg);border-color:var(--sh-abd);box-shadow:0 0 0 3px var(--sh-gl),0 2px 14px var(--sh-gl);transform:translateY(-2px)}
.shard.act::before{transform:scaleX(1)}
.sh-id{font-size:9.5px;font-weight:700;color:var(--sp);letter-spacing:.04em}
.sh-fmt{font-size:8px;color:var(--tx3);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sh-row{display:flex;justify-content:space-between;margin-top:6px}
.sh-sv{font-size:11px;font-weight:600;color:var(--tx);line-height:1.2}
.sh-sk{font-size:8px;color:var(--tx3);margin-top:1px}
.mmap-bars{display:flex;gap:1.5px;margin-top:6px;height:3px}
.mbar{flex:1;border-radius:1.5px;background:var(--sh-bd);transition:background .15s}
.shard.act .mbar{background:var(--sh-abd)}
.shard.act .mbar:nth-child(3n+1){opacity:.55}
.shard.act .mbar:nth-child(5n+2){opacity:.75}
.sh-result{margin-top:6px;font-size:9px;display:flex;justify-content:space-between;color:var(--sp);opacity:0;transition:opacity .3s}
.sh-result.show{opacity:1}

/* bm25 */
.bm25-box{width:100%;background:var(--sh-bg);border:1.5px solid var(--sh-bd);border-radius:8px;padding:13px;font-family:'JetBrains Mono',monospace;transition:border-color .25s,box-shadow .25s;margin-top:8px;position:relative;overflow:hidden}
.bm25-box::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--bm);transform:scaleX(0);transform-origin:left;transition:transform .4s ease}
.bm25-box.act{border-color:var(--bm);box-shadow:0 0 0 3px var(--bm-gl)}
.bm25-box.act::before{transform:scaleX(1)}
.bm25-id{font-size:10px;font-weight:700;color:var(--bm)}
.bm25-rows{margin-top:9px;display:flex;flex-direction:column;gap:5px;font-size:10px}
.bm25-row{display:flex;justify-content:space-between}
.bm25-k{color:var(--tx3)}.bm25-v{font-weight:500;color:var(--tx)}
.bm25-segs{display:flex;gap:1.5px;height:3px;margin-top:9px}
.bm25-seg{flex:1;border-radius:1.5px;background:var(--sh-bd);transition:background .2s}
.bm25-box.act .bm25-seg{background:var(--bm);opacity:.7}
.bm25-result{margin-top:8px;font-size:9px;color:var(--bm);opacity:0;transition:opacity .3s}
.bm25-result.show{opacity:1}

/* merge */
.merge-wrap{width:100%;display:flex;flex-direction:column;align-items:center;gap:0}
.merge-arms{width:100%;display:flex;justify-content:space-between;padding:0 40px;position:relative;transition:opacity .3s}
.merge-arms.dimmed{opacity:.2}
.merge-arms::before{content:'';position:absolute;bottom:0;left:40px;right:40px;height:1.5px;background:var(--ln);transition:background .3s}
.merge-arms.lit::before{background:var(--fu)}
.arm{width:1.5px;height:22px;background:var(--ln);transition:background .3s}
.merge-arms.lit .arm{background:var(--fu)}

/* seq scan indicator */
.seq-bar{width:100%;height:2px;background:var(--ln);border-radius:1px;margin-top:8px;overflow:hidden;position:relative;opacity:0;transition:opacity .3s}
.seq-bar.show{opacity:1}
.seq-fill{position:absolute;top:0;left:0;height:100%;background:var(--sp);border-radius:1px;width:0%;transition:width .1s linear}

/* timing */
.timing-strip{width:100%;opacity:0;transition:opacity .4s;margin-bottom:4px}
.timing-strip.show{opacity:1}
.timing-label{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tx3);margin-bottom:5px;letter-spacing:.07em;text-transform:uppercase}
.timing-bar{display:flex;height:8px;border-radius:4px;overflow:hidden}
.tseg{height:100%;font-family:'JetBrains Mono',monospace;font-size:7px;color:rgba(255,255,255,.85);font-weight:600;display:flex;align-items:center;justify-content:center;white-space:nowrap;overflow:hidden}
.ts-q{background:var(--q)}.ts-sp{background:var(--sp)}.ts-bm{background:var(--bm)}.ts-fu{background:var(--fu)}.ts-re{background:var(--re)}.ts-ca{background:var(--ca)}
.timing-legend{display:flex;gap:14px;margin-top:7px;flex-wrap:wrap}
.tl-item{display:flex;align-items:center;gap:5px;font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tx2)}
.tl-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}

/* results */
.results-panel{width:100%;background:var(--surf);border:1.5px solid var(--bd);border-radius:11px;overflow:hidden;opacity:0;transform:translateY(10px);transition:opacity .45s,transform .45s}
.results-panel.show{opacity:1;transform:translateY(0)}
.rp-head{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;background:var(--surf2);border-bottom:1.5px solid var(--bd)}
.rp-title{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--tx2)}
.rp-timing{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--tx2)}
.rp-timing .val{color:var(--tx);font-weight:600}
.rp-source{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tx3)}
.result-row{display:flex;gap:12px;padding:10px 16px;border-bottom:1px solid var(--ln);transition:background .15s}
.result-row:last-child{border-bottom:none}
.result-row:hover{background:var(--surf2)}
.rk{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--tx3);min-width:18px;padding-top:2px;flex-shrink:0;font-variant-numeric:tabular-nums}
.rt{font-size:13px;font-weight:500;color:var(--tx);line-height:1.45}
.rm{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--tx2);margin-top:3px}
.rm .oa{color:var(--bm)}
.score{float:right;font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tx3);padding-top:3px;font-variant-numeric:tabular-nums}

.gap-sm{height:10px;flex-shrink:0}.gap-md{height:16px;flex-shrink:0}

@media(max-width:640px){
  .shard-grid{grid-template-columns:repeat(2,1fr)}
  .split{grid-template-columns:1fr}
  body{padding:16px 12px 48px}
  .profile-body{grid-template-columns:1fr}
}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition-duration:0ms!important}}

/* ── top view tab bar ─────────────────────────────────────────────────────── */
.view-tabs{max-width:960px;margin:0 auto 20px;display:flex;gap:6px}
.vtab{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;padding:8px 16px;border-radius:8px;border:1.5px solid var(--bd);background:var(--surf);color:var(--tx2);cursor:pointer;transition:background .15s,color .15s,border-color .15s}
.vtab.active{background:var(--surf2);color:var(--tx);border-color:var(--sp)}
.vtab:hover:not(.active){background:var(--surf2)}

/* ── references tab ─────────────────────────────────────────────────────── */
.refs-wrap{max-width:960px;margin:0 auto;padding-bottom:60px}
.refs-head{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--tx2);margin:24px 0 12px;padding-bottom:8px;border-bottom:1.5px solid var(--bd)}
.refs-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}
.ref-card{display:flex;gap:12px;background:var(--surf);border:1.5px solid var(--bd);border-radius:11px;padding:14px;text-decoration:none;color:inherit;transition:border-color .2s,box-shadow .2s,transform .15s;align-items:flex-start}
.ref-card:not(.no-link):hover{border-color:var(--sp);box-shadow:0 0 0 3px var(--sh-gl);transform:translateY(-2px)}
.ref-card.no-link{cursor:default}
.rc-icon{width:36px;height:36px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;color:#fff;flex-shrink:0;letter-spacing:.03em}
.rc-body{flex:1;min-width:0}
.rc-name{font-size:13px;font-weight:600;color:var(--tx);line-height:1.3;margin-bottom:2px}
.rc-url{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--tx3);margin-bottom:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ref-card:not(.no-link) .rc-url{color:var(--sp)}
.rc-desc{font-size:11.5px;color:var(--tx2);line-height:1.6;margin-bottom:8px}
.rc-tags{display:flex;flex-wrap:wrap;gap:5px}
.rt-tag{font-family:'JetBrains Mono',monospace;font-size:8.5px;font-weight:600;padding:2px 7px;border-radius:4px;background:var(--surf2);border:1px solid var(--bd);color:var(--tx2);letter-spacing:.04em}
@media(max-width:640px){.refs-grid{grid-template-columns:1fr}}
</style>

<!-- top-level view tabs -->
<div class="view-tabs">
  <button class="vtab active" onclick="switchView('pipeline')">⚡ Pipeline Trace</button>
  <button class="vtab" onclick="switchView('refs')">📚 References</button>
</div>

<div id="view-pipeline">
<div class="sysbar">
  <span class="live"></span>
  <span class="div2">·</span>
  <strong>150,000,000</strong>&nbsp;docs
  <span class="div2">·</span>
  SEISMIC 8-shard E8&nbsp;dv-v2 mmap
  <span class="div2">·</span>
  25.2&nbsp;GB RSS
  <span class="div2">·</span>
  warm p50&nbsp;~65&nbsp;ms
  <span class="div2">·</span>
  demo.vancitylandscaper.com
</div>

<!-- Deploy profile card -->
<div class="profile-card">
  <div class="profile-head">
    <button class="scenario-btn active" data-s="server" onclick="setScenario('server')">⬛ Server</button>
    <button class="scenario-btn" data-s="mobile" onclick="setScenario('mobile')">📱 Mobile</button>
    <button class="scenario-btn" data-s="thumbdrive" onclick="setScenario('thumbdrive')">💾 Thumb Drive</button>
  </div>
  <div class="profile-body">
    <div class="ram-section">
      <div class="ram-label">
        Host RAM
        <span id="ram-disp">32 GB</span>
      </div>
      <input type="range" id="ram-slider" min="4" max="64" value="32" step="2" oninput="onRamSlider()">
      <div class="ram-zones" id="ram-zones-bar">
        <div class="rz rz-danger" style="flex:8"></div>
        <div class="rz rz-warn"   style="flex:8"></div>
        <div class="rz rz-ok"     style="flex:44"></div>
      </div>
      <div id="ram-zones-labels" style="display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:8.5px;color:var(--tx3);margin-top:2px">
        <span>4 GB</span><span>severe paging</span><span>marginal</span><span>✓ comfortable (≥20 GB)</span><span>64 GB</span>
      </div>
    </div>
    <div class="profile-stats">
      <div class="pstat"><span class="pstat-k">federation</span><span class="pstat-v" id="p-mode">parallel</span></div>
      <div class="pstat"><span class="pstat-k">corpus</span><span class="pstat-v" id="p-corpus">full 150M</span></div>
      <div class="pstat"><span class="pstat-k">warm p50</span><span class="pstat-v ok" id="p-warm">64 ms</span></div>
      <div class="pstat"><span class="pstat-k">cold p50</span><span class="pstat-v ok" id="p-cold-p50">630 ms</span></div>
      <div class="pstat"><span class="pstat-k">cold p95</span><span class="pstat-v ok" id="p-cold">1,324 ms</span></div>
      <div class="pstat"><span class="pstat-k">storage</span><span class="pstat-v" id="p-storage">NVMe · 3 GB/s</span></div>
    </div>
    <div class="profile-note" id="p-note"></div>
    <div id="mobile-disclaimer" style="display:none;grid-column:1/-1;font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--warn);background:var(--warn-bg);border:1px solid var(--warn-bd);border-radius:6px;padding:8px 10px;line-height:1.6;margin-top:4px">
      ⚠ <strong>Hypothetical / untested.</strong> The SEISMIC stack has never been deployed on a phone. This scenario is an educational estimate based on server benchmarks scaled to the SocSci subset (~19M docs). Phone RAM tiers shown: 4 GB (budget), 6–8 GB (mid-range), 12–16 GB (flagship). Hot working set for subset: ~1.8 GB — fits in all tiers. CPU encode speed and NVMe throughput are extrapolated, not measured.
    </div>
  </div>
</div>

<!-- Pipeline -->
<div class="pipe">
  <!-- query bar -->
  <div class="qrow">
    <input class="qinput" id="qinput" type="text" value="large language model reasoning" autocomplete="off" spellcheck="false">
    <button class="cache-toggle" id="ctoggle" onclick="toggleCache()">CACHE HIT: OFF</button>
    <button class="qbtn" id="qbtn" onclick="runQuery()">RUN QUERY →</button>
  </div>

  <div class="arrow" id="a0"></div>

  <!-- result cache stage -->
  <div class="stage" id="cache-stage">
    <div class="s-left">
      <div class="s-eyebrow"><span class="tag tca">RESULT CACHE</span></div>
      <div class="s-name">Read-through cache</div>
    </div>
    <div style="text-align:right">
      <div class="s-meta">256-entry LRU · 6 h TTL<br>versioned key · miss → full pipeline</div>
      <div class="s-hit" id="cache-hit-label">HIT → 3.7 ms</div>
      <div class="s-lat" id="cache-miss-label">MISS</div>
    </div>
  </div>

  <div class="arrow" id="a1"></div>

  <!-- query encoder -->
  <div class="stage" id="enc">
    <div class="s-left">
      <div class="s-eyebrow"><span class="tag tq">QUERY ENCODER</span></div>
      <div class="s-name">SPLADE sparse vector</div>
    </div>
    <div style="text-align:right">
      <div class="s-meta">prithivida/Splade_PP_en_v1<br>fused ONNX · vocab dim 30,522</div>
      <div class="s-lat" id="enc-lat">~20 ms</div>
    </div>
  </div>

  <div class="gap-sm"></div>
  <div class="par-label" id="par-label" style="--mode-label:'parallel retrieval'">parallel retrieval</div>
  <div class="gap-sm"></div>

  <!-- two legs -->
  <div class="split" id="split">
    <!-- SEISMIC -->
    <div class="leg">
      <div class="leg-head" id="sp-head">
        <div class="lh-icon isp">SP</div>
        <div class="lh-info">
          <div class="lh-name">SEISMIC sparse SPLADE</div>
          <div class="lh-sub" id="seismic-sub">8-shard federated mmap · E8 dv-v2</div>
        </div>
        <div class="lh-lat" id="sp-lat"></div>
      </div>
      <div class="seq-bar" id="seq-bar"><div class="seq-fill" id="seq-fill"></div></div>
      <div class="shard-grid" id="shard-grid"></div>
    </div>
    <!-- BM25F -->
    <div class="leg">
      <div class="leg-head" id="bm-head">
        <div class="lh-icon ibm">BM</div>
        <div class="lh-info">
          <div class="lh-name">BM25F lexical</div>
          <div class="lh-sub">tantivy 0.26 · title³ + abstract</div>
        </div>
        <div class="lh-lat" id="bm-lat"></div>
      </div>
      <div class="bm25-box" id="bm25">
        <div class="bm25-id">tantivy.index</div>
        <div class="bm25-rows">
          <div class="bm25-row"><span class="bm25-k">index size</span><span class="bm25-v">77.8 MB</span></div>
          <div class="bm25-row"><span class="bm25-k">fields</span><span class="bm25-v">title^3 · abstract</span></div>
          <div class="bm25-row"><span class="bm25-k">positions</span><span class="bm25-v">off (freq only)</span></div>
          <div class="bm25-row"><span class="bm25-k">filters</span><span class="bm25-v">year · type · is_oa</span></div>
        </div>
        <div class="bm25-segs" id="bm25-segs"></div>
        <div class="bm25-result" id="bm25-result">→ 1,204 candidates · 4.1 ms</div>
      </div>
    </div>
  </div>

  <!-- merge -->
  <div class="gap-sm"></div>
  <div class="merge-wrap">
    <div class="merge-arms" id="merge-arms">
      <div class="arm"></div><div class="arm"></div>
    </div>
    <div class="arrow" id="a2"></div>
  </div>

  <!-- RRF -->
  <div class="stage" id="rrf">
    <div class="s-left">
      <div class="s-eyebrow"><span class="tag tfu">FUSION</span></div>
      <div class="s-name">Reciprocal Rank Fusion</div>
    </div>
    <div style="text-align:right">
      <div class="s-meta">k=60 · SPLADE + BM25F merged<br>top-100 candidates → reranker</div>
      <div class="s-lat" id="rrf-lat">2.4 ms</div>
    </div>
  </div>

  <div class="arrow" id="a3"></div>

  <!-- reranker - FIXED LABEL -->
  <div class="stage" id="rnk">
    <div class="s-left">
      <div class="s-eyebrow"><span class="tag tre">RERANKER</span></div>
      <div class="s-name">Cross-encoder rerank</div>
    </div>
    <div style="text-align:right">
      <div class="s-meta">cross-encoder-v1 · fine-tuned<br>top-20 pool · torch CPU</div>
      <div class="s-lat" id="rnk-lat">25.5 ms</div>
    </div>
  </div>

  <div class="arrow" id="a4"></div>

  <!-- timing strip -->
  <div class="timing-strip" id="timing-strip">
    <div class="timing-label" id="timing-label">query timeline</div>
    <div class="timing-bar" id="timing-bar"></div>
    <div class="timing-legend" id="timing-legend"></div>
  </div>

  <div class="gap-sm"></div>

  <!-- results -->
  <div class="results-panel" id="results-panel">
    <div class="rp-head">
      <div class="rp-title">top-10 results</div>
      <div style="display:flex;align-items:center;gap:14px">
        <div class="rp-source" id="rp-source"></div>
        <div class="rp-timing">total <span class="val" id="total-time">—</span></div>
      </div>
    </div>
    <div id="results-body"></div>
  </div>
</div>
</div><!-- #view-pipeline -->

<!-- ── References tab ───────────────────────────────────────────────────── -->
<div id="view-refs" style="display:none">
<div class="refs-wrap">

  <h2 class="refs-head">Repos &amp; Tools</h2>
  <div class="refs-grid">

    <a class="ref-card" href="https://github.com/quickwit-oss/tantivy" target="_blank" rel="noopener">
      <div class="rc-icon ibm">BM</div>
      <div class="rc-body">
        <div class="rc-name">tantivy</div>
        <div class="rc-url">github.com/quickwit-oss/tantivy</div>
        <div class="rc-desc">Rust full-text search engine library. Serves the BM25F lexical leg — title^3 + abstract, 77.8 MB index, positions disabled for speed, ~4 ms warm query time.</div>
        <div class="rc-tags"><span class="rt-tag">Rust</span><span class="rt-tag">BM25F</span><span class="rt-tag">inverted index</span></div>
      </div>
    </a>

    <a class="ref-card" href="https://huggingface.co/prithivida/Splade_PP_en_v1" target="_blank" rel="noopener">
      <div class="rc-icon isp">SP</div>
      <div class="rc-body">
        <div class="rc-name">prithivida/Splade_PP_en_v1</div>
        <div class="rc-url">huggingface.co/prithivida/Splade_PP_en_v1</div>
        <div class="rc-desc">SPLADE++ Efficient encoder. Maps queries to sparse BERT-vocabulary vectors (dim 30,522). Served via a fused ONNX graph (tokenizer + encoder merged) for ~20 ms CPU inference.</div>
        <div class="rc-tags"><span class="rt-tag">SPLADE++</span><span class="rt-tag">HuggingFace</span><span class="rt-tag">sparse retrieval</span></div>
      </div>
    </a>

    <a class="ref-card" href="https://onnxruntime.ai" target="_blank" rel="noopener">
      <div class="rc-icon" style="background:var(--q)">OX</div>
      <div class="rc-body">
        <div class="rc-name">ONNX Runtime</div>
        <div class="rc-url">onnxruntime.ai</div>
        <div class="rc-desc">Cross-platform ML inference engine. Runs the fused SPLADE encoder (splade_onnx_fused). The "fused" model merges the tokenizer graph and the transformer into one ONNX graph, eliminating a Python roundtrip.</div>
        <div class="rc-tags"><span class="rt-tag">ONNX</span><span class="rt-tag">CPU inference</span><span class="rt-tag">encoder serving</span></div>
      </div>
    </a>

    <a class="ref-card" href="https://pytorch.org" target="_blank" rel="noopener">
      <div class="rc-icon" style="background:var(--re)">PT</div>
      <div class="rc-body">
        <div class="rc-name">PyTorch</div>
        <div class="rc-url">pytorch.org</div>
        <div class="rc-desc">Deep learning framework. Serves the custom cross-encoder-v1 reranker — torch CPU inference on a batch of 20 candidates, ~25.5 ms. The model was fine-tuned on library relevance data.</div>
        <div class="rc-tags"><span class="rt-tag">Python</span><span class="rt-tag">CPU inference</span><span class="rt-tag">reranker</span></div>
      </div>
    </a>

  </div>

  <h2 class="refs-head">Algorithms &amp; Concepts</h2>
  <div class="refs-grid">

    <div class="ref-card no-link">
      <div class="rc-icon" style="background:var(--sp)">SC</div>
      <div class="rc-body">
        <div class="rc-name">SEISMIC</div>
        <div class="rc-url">sparse inverted-index retrieval algorithm</div>
        <div class="rc-desc">Approximate maximum inner product search (AMIPS) over SPLADE sparse vectors. Traverses the inverted index of per-doc SPLADE values in score order, early-exiting when the upper-bound contribution drops below the current top-k threshold.</div>
        <div class="rc-tags"><span class="rt-tag">sparse MIPS</span><span class="rt-tag">inverted index</span><span class="rt-tag">early exit</span></div>
        <div style="margin-top:9px;padding:8px 10px;background:var(--warn-bg);border:1px solid var(--warn-bd);border-radius:6px;font-family:'JetBrains Mono',monospace;font-size:8.5px;color:var(--warn);line-height:1.55">
          ⚠ Deployment differs: standard SEISMIC indexes the corpus as a single monolithic structure. This deployment horizontally shards the 150M docs across 8 independent mmap'd SEISMIC indexes (global_shard{0–7}of8), each queried in parallel. Sharding is not part of the original algorithm — it is an operational choice made here to fit the full corpus into host RAM incrementally and to parallelize traversal across CPU cores.
        </div>
      </div>
    </div>

    <a class="ref-card" href="https://arxiv.org/abs/2205.04733" target="_blank" rel="noopener">
      <div class="rc-icon isp">SP</div>
      <div class="rc-body">
        <div class="rc-name">SPLADE++ · Formal et al., 2022</div>
        <div class="rc-url">arxiv.org/abs/2205.04733</div>
        <div class="rc-desc">Sparse Lexical and Expansion model. Learns to produce sparse query and document vectors in the BERT vocabulary space. Enables semantic expansion — a query about "heart attack" will activate "cardiac" and "myocardial" — while remaining compatible with standard inverted-index retrieval.</div>
        <div class="rc-tags"><span class="rt-tag">neural sparse</span><span class="rt-tag">term expansion</span><span class="rt-tag">BERT vocab</span></div>
      </div>
    </a>

    <a class="ref-card" href="https://en.wikipedia.org/wiki/Okapi_BM25" target="_blank" rel="noopener">
      <div class="rc-icon ibm">BM</div>
      <div class="rc-body">
        <div class="rc-name">BM25 / BM25F</div>
        <div class="rc-url">en.wikipedia.org/wiki/Okapi_BM25</div>
        <div class="rc-desc">Probabilistic term-frequency retrieval model. BM25F extends it to multiple weighted fields — here title^3 + abstract. Fast, interpretable, no neural inference needed. Runs ~4 ms in tantivy with positions disabled (freq-only mode).</div>
        <div class="rc-tags"><span class="rt-tag">lexical</span><span class="rt-tag">TF-IDF family</span><span class="rt-tag">field weighting</span></div>
      </div>
    </a>

    <div class="ref-card no-link">
      <div class="rc-icon" style="background:var(--fu)">RRF</div>
      <div class="rc-body">
        <div class="rc-name">Reciprocal Rank Fusion (RRF)</div>
        <div class="rc-url">Cormack, Clarke, Buettcher — SIGIR 2009</div>
        <div class="rc-desc">Score-fusion formula: score = Σ 1/(k + rank_i). Merges result lists from SEISMIC and BM25F into one ranked list without needing calibrated scores. k=60 is the standard smoothing constant. Simple, robust, and surprisingly hard to beat in practice.</div>
        <div class="rc-tags"><span class="rt-tag">fusion</span><span class="rt-tag">k=60</span><span class="rt-tag">rank aggregation</span></div>
      </div>
    </div>

    <a class="ref-card" href="https://en.wikipedia.org/wiki/Memory-mapped_file" target="_blank" rel="noopener">
      <div class="rc-icon" style="background:var(--tx2)">MM</div>
      <div class="rc-body">
        <div class="rc-name">Memory-mapped files (mmap)</div>
        <div class="rc-url">en.wikipedia.org/wiki/Memory-mapped_file</div>
        <div class="rc-desc">OS mechanism mapping file bytes directly into virtual address space. The 8 shard files (~8.28 GB each on disk) are mmap'd at startup. The OS page cache manages residency — which is exactly why host RAM determines warm vs. cold latency (see the RAM slider in the Pipeline tab).</div>
        <div class="rc-tags"><span class="rt-tag">OS paging</span><span class="rt-tag">page cache</span><span class="rt-tag">zero-copy I/O</span></div>
      </div>
    </a>

    <div class="ref-card no-link">
      <div class="rc-icon" style="background:var(--re)">CE</div>
      <div class="rc-body">
        <div class="rc-name">Cross-encoder reranking</div>
        <div class="rc-url">cross-encoder-v1 · fine-tuned · top-20 pool</div>
        <div class="rc-desc">Reranking architecture that jointly encodes the query and a candidate document as a single input pair, enabling full cross-attention between both. More accurate than bi-encoders (which encode independently) but slower — used here only on the top-20 candidates from RRF.</div>
        <div class="rc-tags"><span class="rt-tag">pointwise rerank</span><span class="rt-tag">BERT pair encoding</span><span class="rt-tag">top-20 pool</span></div>
        <div style="margin-top:9px;padding:8px 10px;background:var(--warn-bg);border:1px solid var(--warn-bd);border-radius:6px;font-family:'JetBrains Mono',monospace;font-size:8.5px;color:var(--warn);line-height:1.55">
          ⚠ Model differs: the canonical base model for cross-encoders in this space is ms-marco (microsoft/ms-marco-MiniLM-L-*). This deployment uses cross-encoder-v1, a custom fine-tune trained specifically on library paper relevance data — not the ms-marco base. The ms-marco checkpoint is kept in reserve as the one-environment rollback option.
        </div>
      </div>
    </div>

    <div class="ref-card no-link">
      <div class="rc-icon" style="background:var(--ca)">DV</div>
      <div class="rc-body">
        <div class="rc-name">dv-v2 · dotvbyte / FixedU8Q</div>
        <div class="rc-url">E8 quantization format · internal</div>
        <div class="rc-desc">Custom quantization format for SEISMIC's per-document SPLADE value storage. Encodes each float SPLADE weight as a uint8 with a fixed per-doc scale factor (FixedU8Q), reducing the RSS from ~41.86 GB (float16) to ~25.23 GB (dv-v2) for the 150M-doc corpus.</div>
        <div class="rc-tags"><span class="rt-tag">uint8 quant</span><span class="rt-tag">41.86 → 25.23 GB</span><span class="rt-tag">mmap-friendly</span></div>
        <div style="margin-top:9px;padding:8px 10px;background:var(--warn-bg);border:1px solid var(--warn-bd);border-radius:6px;font-family:'JetBrains Mono',monospace;font-size:8.5px;color:var(--warn);line-height:1.55">
          ⚠ Not a standard format: dv-v2 / dotvbyte is an internal development. It is not part of any published SEISMIC or SPLADE specification. The "E8" prefix denotes the 8th compression experiment in this project's quantization series.
        </div>
      </div>
    </div>

  </div>
</div>
</div><!-- #view-refs -->

<script>
// ── shard data ───────────────────────────────────────────────────────────────
const SHARDS_FULL = [
  {id:0,docs:'18.80M',gb:'3.15',lat:61,cands:847},
  {id:1,docs:'18.80M',gb:'3.17',lat:72,cands:923},
  {id:2,docs:'18.80M',gb:'3.14',lat:55,cands:791},
  {id:3,docs:'18.80M',gb:'3.18',lat:78,cands:966},
  {id:4,docs:'18.80M',gb:'3.16',lat:63,cands:872},
  {id:5,docs:'18.80M',gb:'3.14',lat:58,cands:834},
  {id:6,docs:'18.80M',gb:'3.17',lat:70,cands:905},
  {id:7,docs:'18.80M',gb:'3.16',lat:65,cands:888},
];
const SHARDS_SUBSET = [
  {id:0,docs:'2.37M',gb:'0.53',lat:42,cands:108},
  {id:1,docs:'2.37M',gb:'0.54',lat:51,cands:134},
  {id:2,docs:'2.36M',gb:'0.53',lat:38,cands:97},
  {id:3,docs:'2.37M',gb:'0.54',lat:55,cands:142},
  {id:4,docs:'2.37M',gb:'0.53',lat:44,cands:117},
  {id:5,docs:'2.36M',gb:'0.53',lat:40,cands:105},
  {id:6,docs:'2.37M',gb:'0.54',lat:48,cands:128},
  {id:7,docs:'2.37M',gb:'0.53',lat:45,cands:121},
];

// ── results data ─────────────────────────────────────────────────────────────
const PAPERS = [
  {title:'Chain-of-Thought Prompting Elicits Reasoning in Large Language Models',meta:'Wei et al. · NeurIPS 2022',year:2022,oa:true,score:.9812},
  {title:'Large Language Models are Zero-Shot Reasoners',meta:'Kojima et al. · NeurIPS 2022',year:2022,oa:true,score:.9741},
  {title:'Self-Consistency Improves Chain of Thought Reasoning in Language Models',meta:'Wang et al. · ICLR 2023',year:2023,oa:false,score:.9688},
  {title:'ReAct: Synergizing Reasoning and Acting in Language Models',meta:'Yao et al. · ICLR 2023',year:2023,oa:true,score:.9601},
  {title:'Tree of Thoughts: Deliberate Problem Solving with Large Language Models',meta:'Yao et al. · NeurIPS 2023',year:2023,oa:true,score:.9534},
  {title:'Reasoning with Language Model Prompting: A Survey',meta:'Qiao et al. · ACL 2023',year:2023,oa:false,score:.9478},
  {title:'Program of Thoughts Prompting: Disentangling Computation from Reasoning',meta:'Chen et al. · TMLR 2023',year:2023,oa:true,score:.9392},
  {title:'Least-to-Most Prompting Enables Complex Reasoning in Large Language Models',meta:'Zhou et al. · ICLR 2023',year:2022,oa:false,score:.9321},
];

// ── state ─────────────────────────────────────────────────────────────────────
let scenario = 'server', ramGB = 32, cacheHit = false, running = false;

// ── scenario definitions ──────────────────────────────────────────────────────
const SCENARIOS = {
  server:     { ram:32, storage:'NVMe · 3 GB/s',           storageMBps:3000, corpus:'full 150M', shards:SHARDS_FULL },
  mobile:     { ram:8,  storage:'phone NVMe · 1.5 GB/s',   storageMBps:1500, corpus:'SocSci · ~19M docs', shards:SHARDS_SUBSET },
  thumbdrive: { ram:16, storage:'USB 3.0 · 150 MB/s',      storageMBps:150,  corpus:'SocSci · ~19M docs', shards:SHARDS_SUBSET },
};

// ── latency model ─────────────────────────────────────────────────────────────
// Server anchors from R1 RAM-ladder benchmark (2026-07-14, parallel E8 dv-v2 + E5 + F6, top_k=50).
// warmP50 = R1 pass3 (steady-state) + 45 ms overhead (encode 20 ms + RRF 2 ms + rerank 25 ms).
// coldP50 = R1 pass1 p50 + 45 ms.  coldP95 = R1 pass1 p95 + 45 ms.
// Hot working set at ≥24 GB: vmrss ~14.24 GB (not 25.23 GB — that is full-corpus dv-v2 mmap size).
const SERVER_ANCHORS = [
  //  [ram, warmP50, coldP50, coldP95, note]
  [ 4, 8500,  6000, 16000, '⚠ Not measured (below 6 GB floor) — estimated. Estimated severe paging; cannot serve reliably.'],
  [ 6, 4969,  4847, 10994, '⚠ Chronic paging. Hot set (~14.2 GB) is 2.4× RAM — pages evict faster than they load. Warm latency stays ~5 s every query; never converges across 3 passes. vmrss stabilises at 4.94 GB. Source: R1 measured 2026-07-14.'],
  [ 8, 2180,  3437,  7256, '⚠ Heavy paging. vmrss stabilises at ~7.1 GB; ~7 GB of the hot set stays evicted. Warm latency falls from 3.4 s to 2.1 s over 3 passes but never fully converges. Source: R1 measured 2026-07-14.'],
  [12,   67,  1900,  4634, 'Marginal — but surprisingly effective once converged. After ~3 full query passes (~120 queries) the hot set fits in 11.56 GB and warm p50 drops to 22 ms (SEISMIC) / ~67 ms total. Cold queries still 1.9 s. Source: R1 pass3 measured 2026-07-14.'],
  [16,  180,   987,  2221, 'Constrained. Converges in 2–3 passes to ~135 ms SEISMIC / ~180 ms total. Cold p50 ~1 s. Viable with a warm-up period. vmrss 12.93 GB. Source: R1 pass3 measured 2026-07-14.'],
  [20,  100,   780,  1700, 'Estimated (between 16 and 24 GB measured anchors) — not directly measured. Hot set approaching full residency.'],
  [24,   64,   630,  1324, '✓ Comfortable. Hot set (~14.2 GB) fully resident after 1 cold pass. Warm p50: 19 ms SEISMIC / ~64 ms total. Cold p95 ~1.3 s. vmrss 14.24 GB. Source: R1 pass3 measured 2026-07-14.'],
  [32,   63,   650,  1320, '✓ Optimal for this workload. Same performance as 24 GB (measured hot set = 14.2 GB). Extra RAM benefits other processes. Source: R1 pass3 measured 2026-07-14.'],
  [48,   63,   621,  1272, '✓ Excess — no further gain measured vs 32 GB. Source: R1 pass3 measured 2026-07-14.'],
  [64,   63,   610,  1260, 'Excess. Identical to 48 GB.'],
];

function anchorLerp(anchors, ram, col) {
  for (let i = 0; i < anchors.length - 1; i++) {
    const [a] = anchors[i], [b] = anchors[i+1];
    if (ram >= a && ram <= b) {
      const t = (ram - a) / (b - a);
      return Math.round(anchors[i][col] + (anchors[i+1][col] - anchors[i][col]) * t);
    }
  }
  return anchors[anchors.length-1][col];
}

function serverNote(ram) {
  for (let i = anchors.length - 1; i >= 0; i--) {
    if (ram >= SERVER_ANCHORS[i][0]) return SERVER_ANCHORS[i][4];
  }
  return SERVER_ANCHORS[0][4];
}

function computeProfile(ram, sc) {
  const cfg = SCENARIOS[sc];
  let warmP50, coldP50, coldP95, safe, note='', mode='parallel';

  if (sc === 'thumbdrive') {
    // USB 3.0 @ 150 MB/s. Subset hot set ~1.8 GB across 8 shards = ~225 MB/shard.
    // Cold: 225 MB / 150 MBps ≈ 1.5 s per shard; parallel across 8 → max shard is bottleneck.
    // Warm: once pages are in OS cache (16 GB RAM >> 1.8 GB subset), fast.
    warmP50 = 160;  // encode 50ms (est) + SEISMIC warm ~80ms (est) + rerank 30ms (est)
    coldP50 = 1900; // estimated cold load + pipeline
    coldP95 = 4200; // estimated cold P95 (USB variance)
    safe = false;
    note = 'Warm reads come from OS page cache (1.8 GB subset fits in 16 GB RAM). Cold is USB 3.0 I/O-bound: ~225 MB/shard / 150 MB/s ≈ 1.5 s/shard; all 8 shards in parallel. *est* — not measured on USB hardware.';
  } else if (sc === 'mobile') {
    // Subset hot set ~1.8 GB always fits in any phone RAM tier.
    // Phone CPU estimate: encode ~50 ms (slower than server 20 ms), SEISMIC ~25 ms, rerank ~30 ms.
    warmP50 = 105; coldP50 = 380; coldP95 = 650;
    safe = true;
    note = '⚠ Hypothetical — this scenario has never been officially tested on mobile hardware. Numbers are estimates extrapolated from server benchmarks scaled to the SocSci subset (~19M docs). The subset hot working set is ~1.8 GB, which fits in any modern phone RAM tier. Phone CPU is assumed ~2.5× slower than the 16-core server for encoding.';
  } else {
    // Server: anchor-based interpolation from R1 data
    const clamp = Math.max(4, Math.min(64, ram));
    warmP50 = anchorLerp(SERVER_ANCHORS, clamp, 1);
    coldP50 = anchorLerp(SERVER_ANCHORS, clamp, 2);
    coldP95 = anchorLerp(SERVER_ANCHORS, clamp, 3);
    // find note from nearest anchor below
    let noteText = SERVER_ANCHORS[0][4];
    for (let i = 0; i < SERVER_ANCHORS.length; i++) {
      if (clamp >= SERVER_ANCHORS[i][0]) noteText = SERVER_ANCHORS[i][4];
    }
    note = noteText;
    safe = clamp >= 20;
  }

  const fmt = ms => ms >= 1000 ? (ms/1000).toFixed(1)+' s' : ms+' ms';
  return { mode, warmP50, coldP50, coldP95, safe, corpus:cfg.corpus, storage:cfg.storage, note, fmt };
}

// ── render profile ────────────────────────────────────────────────────────────
function fmtMs(ms){ return ms>=1000 ? (ms/1000).toFixed(1)+' s' : ms+' ms'; }

function renderProfile() {
  const p = computeProfile(ramGB, scenario);
  const cfg = SCENARIOS[scenario];

  document.getElementById('ram-disp').textContent = ramGB+' GB';
  document.getElementById('p-mode').textContent = p.mode;
  document.getElementById('p-corpus').textContent = p.corpus;

  const pw = document.getElementById('p-warm');
  pw.textContent = fmtMs(p.warmP50);
  pw.className = 'pstat-v '+(p.safe?'ok': p.warmP50>1000?'danger':'warn');

  const pp50 = document.getElementById('p-cold-p50');
  if (pp50) {
    pp50.textContent = fmtMs(p.coldP50);
    pp50.className = 'pstat-v '+(p.safe?'ok': p.coldP50>3000?'danger':'warn');
  }

  const pc = document.getElementById('p-cold');
  pc.textContent = fmtMs(p.coldP95);
  pc.className = 'pstat-v '+(p.safe?'ok': p.coldP95>5000?'danger':'warn');

  document.getElementById('p-storage').textContent = p.storage;
  document.getElementById('p-note').textContent = p.note;

  // update seismic sub-label — always parallel (parallel/sequential is an ops choice, not RAM-driven)
  document.getElementById('seismic-sub').textContent = '8-shard parallel mmap · E8 dv-v2';
  document.getElementById('par-label').textContent = 'parallel retrieval';

  // show/hide phone disclaimer
  const disc = document.getElementById('mobile-disclaimer');
  if (disc) disc.style.display = scenario === 'mobile' ? 'block' : 'none';

  // rebuild shard cards (always parallel)
  buildShards(cfg.shards, false);
}

function buildShards(shards, isSeq) {
  const grid = document.getElementById('shard-grid');
  grid.innerHTML = '';
  shards.forEach(s => {
    const bars = Array.from({length:8},()=>'<div class="mbar"></div>').join('');
    const candStr = s.cands.toLocaleString();
    grid.innerHTML += `<div class="shard" id="sh${s.id}">
      <div class="sh-id">shard ${s.id}${isSeq?' →':''}</div>
      <div class="sh-fmt">…shard${s.id}of8.dotvbyte.e5.v2</div>
      <div class="sh-row">
        <div><div class="sh-sv">${s.docs}</div><div class="sh-sk">docs</div></div>
        <div style="text-align:right"><div class="sh-sv">${s.gb} GB</div><div class="sh-sk">dv-v2</div></div>
      </div>
      <div class="mmap-bars">${bars}</div>
      <div class="sh-result" id="shr${s.id}">
        <span>${candStr} cand</span><span style="color:var(--tx2)">${s.lat} ms</span>
      </div>
    </div>`;
  });
  // rebuild bm25 segs
  document.getElementById('bm25-segs').innerHTML =
    Array.from({length:18},()=>'<div class="bm25-seg"></div>').join('');
}

// ── init results ──────────────────────────────────────────────────────────────
function buildResults() {
  const rb = document.getElementById('results-body');
  rb.innerHTML = '';
  PAPERS.forEach((p,i) => {
    rb.innerHTML += `<div class="result-row">
      <div class="rk">${i+1}</div>
      <div style="flex:1;min-width:0">
        <div class="rt">${p.title}</div>
        <div class="rm">${p.meta} · <span class="rk">${p.year}</span>${p.oa?' · <span class="oa">OA</span>':''}</div>
      </div>
      <div class="score">${p.score.toFixed(4)}</div>
    </div>`;
  });
}

// ── controls ──────────────────────────────────────────────────────────────────
// Phone RAM stops: realistic device tiers (GB)
const PHONE_RAM_STOPS = [4, 6, 8, 12, 16];

function setScenario(s) {
  scenario = s;
  ramGB = SCENARIOS[s].ram;
  const sl = document.getElementById('ram-slider');
  if (s === 'mobile') {
    sl.min = 4; sl.max = 16; sl.step = 2;
    // snap to nearest phone stop
    ramGB = PHONE_RAM_STOPS.reduce((a,b) => Math.abs(b-ramGB)<Math.abs(a-ramGB)?b:a);
  } else {
    sl.min = 4; sl.max = 64; sl.step = 2;
  }
  sl.value = ramGB;
  document.querySelectorAll('.scenario-btn').forEach(b=>{
    b.classList.toggle('active', b.dataset.s===s);
  });
  // update zone bar for mobile vs server
  updateRamZones(s);
  renderProfile();
}

function snapToPhoneStop(v) {
  return PHONE_RAM_STOPS.reduce((a,b) => Math.abs(b-v)<Math.abs(a-v)?b:a);
}

function onRamSlider() {
  let v = +document.getElementById('ram-slider').value;
  if (scenario === 'mobile') v = snapToPhoneStop(v);
  ramGB = v;
  document.getElementById('ram-slider').value = v;
  renderProfile();
}

function updateRamZones(sc) {
  const zbar = document.getElementById('ram-zones-bar');
  const zlabels = document.getElementById('ram-zones-labels');
  if (!zbar || !zlabels) return;
  if (sc === 'mobile') {
    // Subset hot set ~1.8 GB — all phone RAM tiers are fine
    zbar.innerHTML = '<div class="rz rz-ok" style="flex:1"></div>';
    zlabels.innerHTML = '<span>4 GB</span><span>all tiers: hot set fits (~1.8 GB)</span><span>16 GB</span>';
  } else if (sc === 'thumbdrive') {
    zbar.innerHTML = '<div class="rz rz-warn" style="flex:1"></div>';
    zlabels.innerHTML = '<span>4 GB</span><span>OS cache helps warm; USB limits cold</span><span>64 GB</span>';
  } else {
    // Server: danger 4-12, warning 12-20, ok 20-64 (range 4-64 = 60 units)
    zbar.innerHTML = '<div class="rz rz-danger" style="flex:8"></div><div class="rz rz-warn" style="flex:8"></div><div class="rz rz-ok" style="flex:44"></div>';
    zlabels.innerHTML = '<span>4 GB</span><span>severe paging</span><span>marginal</span><span>✓ comfortable (≥20 GB)</span><span>64 GB</span>';
  }
}

function toggleCache() {
  cacheHit = !cacheHit;
  const btn = document.getElementById('ctoggle');
  btn.textContent = cacheHit ? 'CACHE HIT: ON' : 'CACHE HIT: OFF';
  btn.classList.toggle('on', cacheHit);
}

// ── helpers ───────────────────────────────────────────────────────────────────
function ac(id,...c){ const el=document.getElementById(id); if(el) c.forEach(x=>el.classList.add(x)); }
function rc(id,...c){ const el=document.getElementById(id); if(el) c.forEach(x=>el.classList.remove(x)); }
function T(ms,fn){ return setTimeout(fn,ms); }

function resetAll() {
  ['enc','rrf','rnk'].forEach(id=>{ const el=document.getElementById(id); if(el) el.className='stage'; });
  ['a0','a1','a2','a3','a4'].forEach(id=>{ const el=document.getElementById(id); if(el) el.className='arrow'; });
  const cstage=document.getElementById('cache-stage'); if(cstage) cstage.className='stage';
  ['sp-head','bm-head'].forEach(id=>{ const el=document.getElementById(id); if(el) el.className='leg-head'; });
  ['sp-lat','bm-lat','enc-lat','rrf-lat','rnk-lat'].forEach(id=>rc(id,'show'));
  rc('cache-hit-label','show'); rc('cache-miss-label','show');
  const bm=document.getElementById('bm25'); if(bm) bm.classList.remove('act');
  rc('bm25-result','show');
  rc('merge-arms','lit','dimmed');
  rc('results-panel','show'); rc('timing-strip','show');
  rc('seq-bar','show'); rc('par-label','dimmed'); rc('split','dimmed');
  document.getElementById('total-time').textContent='—';
  const shards = SCENARIOS[scenario].shards;
  shards.forEach(s=>{ rc('sh'+s.id,'act'); rc('shr'+s.id,'show'); });
}

function dimPipeline(dim) {
  ['enc','rrf','rnk'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.classList.toggle('dimmed',dim);
  });
  document.getElementById('par-label').classList.toggle('dimmed',dim);
  document.getElementById('split').classList.toggle('dimmed',dim);
  document.getElementById('merge-arms').classList.toggle('dimmed',dim);
}

// ── animation ─────────────────────────────────────────────────────────────────
function runQuery() {
  if (running) return;
  running = true;
  document.getElementById('qbtn').disabled = true;
  resetAll();
  // Fire real search in parallel with the animation
  _fetchRealSearch(document.getElementById('qinput').value.trim());

  const p = computeProfile(ramGB, scenario);
  const isSeq = false; // always parallel (mode is an ops choice, not RAM-driven)
  const shards = SCENARIOS[scenario].shards;

  if (cacheHit) {
    // ── CACHE HIT path ──────────────────────────────────────────────────────
    T(80,  ()=>{ ac('a0','lit-ca'); ac('cache-stage','act-ca'); });
    T(280, ()=>{ ac('cache-hit-label','show'); dimPipeline(true); });
    T(400, ()=>{ ac('a4','lit-ca'); });
    T(500, ()=>{
      ac('results-panel','show');
      document.getElementById('rp-source').textContent='served from cache';
      rollTime(100, 3.7, ()=>{});
    });
    T(600, ()=>{
      buildTimingBar([{label:'cache hit',pct:100,cls:'ts-ca',ms:'3.7 ms'}]);
    });
    T(800, ()=>{
      document.getElementById('qbtn').disabled=false;
      running=false;
    });
    return;
  }

  // ── CACHE MISS → full pipeline ─────────────────────────────────────────────
  T(80,  ()=>{ ac('a0','lit'); ac('cache-stage','act-q'); });
  T(250, ()=>{ ac('cache-miss-label','show'); });
  T(350, ()=>{ ac('a1','lit'); });
  T(430, ()=>{ ac('enc','act-q'); });
  T(620, ()=>{ ac('enc-lat','show'); });

  const legStart = 750;
  T(legStart, ()=>{
    ac('sp-head','act-sp'); ac('bm-head','act-bm');
  });

  // BM25F: fast regardless
  T(legStart+60,  ()=>{ ac('bm25','act'); });
  T(legStart+220, ()=>{ ac('bm25-result','show'); ac('bm-lat','show');
    document.getElementById('bm-lat').textContent = '4.1 ms'; });

  // SEISMIC: parallel or sequential
  if (!isSeq) {
    // parallel: all shards nearly-simultaneous
    const onsets   = [0,15,8,30,12,6,24,10];
    const completions = [440,510,390,550,460,420,500,450];
    shards.forEach((s,i)=>{
      T(legStart+80+onsets[i],        ()=>ac('sh'+s.id,'act'));
      T(legStart+80+completions[i],   ()=>ac('shr'+s.id,'show'));
    });
    const seismicDone = legStart + 80 + 580;

    // seismicMs = SEISMIC-traversal-only; warmP50 = total served (includes encode 20ms + RRF 2ms + rerank 25ms)
    const seismicMs = Math.max(1, p.warmP50 - 47);
    T(seismicDone,()=>{ ac('sp-lat','show');
      document.getElementById('sp-lat').textContent = fmtMs(seismicMs); });
    T(seismicDone+80,  ()=>{ ac('merge-arms','lit'); ac('a2','lit-fu'); });
    T(seismicDone+160, ()=>{ ac('rrf','act-fu'); });
    T(seismicDone+280, ()=>{ ac('rrf-lat','show'); ac('a3','lit-re'); });
    T(seismicDone+360, ()=>{ ac('rnk','act-re'); });
    T(seismicDone+540, ()=>{ ac('rnk-lat','show'); ac('a4','lit-re'); });
    T(seismicDone+620, ()=>{
      ac('timing-strip','show');
      const tot = p.warmP50 || 1;
      buildTimingBar([
        {label:'encode',pct:Math.round(20/tot*100),cls:'ts-q',ms:'~20 ms'},
        {label:'SPLADE 8-shard',pct:Math.round(seismicMs/tot*100),cls:'ts-sp',ms:fmtMs(seismicMs)},
        {label:'BM25F',pct:Math.round(4/tot*100),cls:'ts-bm',ms:'4 ms'},
        {label:'RRF',pct:Math.round(2/tot*100),cls:'ts-fu',ms:'2 ms'},
        {label:'rerank',pct:Math.round(25/tot*100),cls:'ts-re',ms:'~25 ms'},
      ]);
    });
    const totalMs = p.warmP50;
    T(seismicDone+700, ()=>{
      ac('results-panel','show');
      document.getElementById('rp-source').textContent='full pipeline · cache miss';
      rollTime(400, totalMs, ()=>{});
    });
    T(seismicDone+1200, ()=>{ document.getElementById('qbtn').disabled=false; running=false; });

  } else {
    // sequential branch kept for compatibility but isSeq is always false now
    const seismicMs2 = Math.max(1, p.warmP50 - 47);
    const seismicDone2 = legStart + 80 + 580;
    T(seismicDone2,()=>{ ac('sp-lat','show');
      document.getElementById('sp-lat').textContent = fmtMs(seismicMs2); });
    T(seismicDone2+80,  ()=>{ ac('merge-arms','lit'); ac('a2','lit-fu'); });
    T(seismicDone2+160, ()=>{ ac('rrf','act-fu'); });
    T(seismicDone2+280, ()=>{ ac('rrf-lat','show'); ac('a3','lit-re'); });
    T(seismicDone2+360, ()=>{ ac('rnk','act-re'); });
    T(seismicDone2+540, ()=>{ ac('rnk-lat','show'); ac('a4','lit-re'); });
    T(seismicDone2+620, ()=>{
      ac('timing-strip','show');
      buildTimingBar([
        {label:'SPLADE 8-shard',pct:70,cls:'ts-sp',ms:fmtMs(seismicMs2)},
        {label:'RRF',pct:2,cls:'ts-fu',ms:'2 ms'},
        {label:'rerank',pct:14,cls:'ts-re',ms:'~25 ms'},
      ]);
    });
    const totalMs2 = p.warmP50;
    T(seismicDone2+700, ()=>{
      ac('results-panel','show');
      document.getElementById('rp-source').textContent='full pipeline · cache miss';
      rollTime(500, totalMs2, ()=>{});
    });
    T(seismicDone+1400, ()=>{ document.getElementById('qbtn').disabled=false; running=false; });
  }
}

function buildTimingBar(segs) {
  const bar = document.getElementById('timing-bar');
  const leg = document.getElementById('timing-legend');
  bar.innerHTML = segs.map(s=>`<div class="tseg ${s.cls}" style="width:${s.pct}%">${s.label}</div>`).join('');
  leg.innerHTML = segs.map(s=>`<div class="tl-item"><span class="tl-dot" style="background:var(--${s.cls.slice(3)})"></span>${s.label} ${s.ms}</div>`).join('');
  // Fix the CSS var references (ts-sp → --sp, etc.)
  leg.querySelectorAll('.tl-dot').forEach((dot,i)=>{
    const cls = segs[i].cls; // e.g. 'ts-sp'
    const varName = '--'+cls.replace('ts-','');
    dot.style.background = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  });
}

function rollTime(duration, targetMs, cb) {
  const start = performance.now();
  const el = document.getElementById('total-time');
  function tick(ts) {
    const pct = Math.min((ts-start)/duration, 1);
    const val = Math.round(pct*targetMs);
    el.textContent = fmtMs(val);
    if (pct<1) requestAnimationFrame(tick); else { el.textContent=fmtMs(targetMs); cb(); }
  }
  requestAnimationFrame(tick);
}

// ── view switcher ─────────────────────────────────────────────────────────────
function switchView(v) {
  document.getElementById('view-pipeline').style.display = v === 'pipeline' ? '' : 'none';
  document.getElementById('view-refs').style.display     = v === 'refs'     ? '' : 'none';
  document.querySelectorAll('.vtab').forEach(b => {
    b.classList.toggle('active', b.textContent.toLowerCase().includes(v === 'pipeline' ? 'pipeline' : 'ref'));
  });
}

// ── real search ───────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function buildRealResults(results, totalMs) {
  const rb = document.getElementById('results-body');
  if (!rb || !results || !results.length) return;
  rb.innerHTML = results.slice(0,10).map((p,i) => {
    const auths = (p.authors||[]);
    const authorStr = auths.length
      ? escHtml(auths.slice(0,3).join(', ') + (auths.length>3?' et al.':''))
      : '';
    const venue = escHtml(p.source||'');
    const meta = [authorStr, venue, p.year].filter(Boolean).join(' · ');
    const oa = p.is_oa ? ' · <span class="oa">OA</span>' : '';
    return `<div class="result-row">
      <div class="rk">${i+1}</div>
      <div style="flex:1;min-width:0">
        <div class="rt">${escHtml(p.title||'(no title)')}</div>
        <div class="rm">${meta}${oa}</div>
      </div>
    </div>`;
  }).join('');
  // update header
  const src = document.getElementById('rp-source');
  if (src) src.textContent = 'live · ' + results.length + ' results';
  // update timing counter with real number
  if (totalMs) {
    const te = document.getElementById('total-time');
    if (te) te.textContent = fmtMs(Math.round(totalMs));
  }
}

// Kick off a real search in parallel with the animation.
// When the response arrives, swap in live results.
function _fetchRealSearch(query) {
  const t0 = performance.now();
  fetch('/arch-search', {
    method: 'POST',
    headers: {'content-type':'application/json'},
    body: JSON.stringify({query: query || 'large language model reasoning', limit: 10}),
    signal: AbortSignal.timeout(15000)
  })
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(data => {
    if (!data.results || !data.results.length) return;
    const dt = performance.now() - t0;
    const panel = document.getElementById('results-panel');
    const inject = () => {
      buildRealResults(data.results, dt);
      if (panel) panel.classList.add('show');
    };
    // If the panel is already visible, replace immediately; otherwise wait for
    // the animation to reveal it (poll for up to 5 s, then force it open).
    if (panel && panel.classList.contains('show')) {
      inject();
    } else {
      let tries = 0;
      const iv = setInterval(() => {
        const p2 = document.getElementById('results-panel');
        if ((p2 && p2.classList.contains('show')) || tries++ > 50) {
          clearInterval(iv); inject();
        }
      }, 100);
    }
  })
  .catch(() => {}); // real results unavailable — animation already playing, silent fallback
}

// ── init ──────────────────────────────────────────────────────────────────────
updateRamZones('server');
renderProfile();
buildResults();
</script>

"""

ARCHITECTURE_HTML = _BACK_BAR + _BODY + _CLOSE
