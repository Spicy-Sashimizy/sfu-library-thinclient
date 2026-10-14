#!/usr/bin/env python3
"""Build the FRESH judged query set the dense-leg ablation needs.

docs/DENSE_PARTITION_AND_ABLATION.md §7 pre-registered the ablation and named
its one remaining blocker: `data/eval_results/diverse_queries.json` has **zero
held-out topics** (§5 — the served 600k dense pool was built as "judged docs
(guaranteed) + distractors", 90.3% ground-truth coverage, 226x enrichment), so
an ablation run on it would re-measure the oracle rather than the leg.

This script produces the replacement, in four ordered stages. The ORDER is the
protocol — the topic draw is committed BEFORE anything is retrieved or judged,
so the draw cannot be tuned to the outcome:

  draw     120 NEW topics over the same 49-subject SFU spread as
           diverse_queries.json, each as a KEYWORD form + a NATURAL-LANGUAGE
           paraphrase (§4's only robust finding is that the dense effect is
           natural-language-shaped). Writes the topic table and stops.
  pool     TREC-style pooling. For each of the 240 query forms, ONE untimed
           retrieval with the FULL 3-leg config (dense ON) via
           `search_rrf_detailed`, recording each leg's top-50, the fused top-50
           and its `rrf_legs` provenance. The judged pool per TOPIC is
           bm25f ∪ splade ∪ dense ∪ fused over BOTH forms — i.e. every doc
           either future arm could surface. NOT the measured ablation run: no
           latency claim may be made from it.
  judge    Grade every pooled (topic, doc) pair 0-3 on topical relevance from
           title+abstract, same protocol as scripts/experiments/benchmark_llm_judge.py
           (grade >= 2 = relevant, gain 2^grade - 1, claude CLI subprocess
           backend). Judged on the NATURAL-LANGUAGE form of the topic. Cached
           and checkpointed — an interrupted run resumes for free.
  finalize Stratify each topic with the dense_pool_contamination.py rule
           (HELD-OUT = zero grade>=2 docs inside data/thinclient_index/dense/ids.json,
           the DECISION stratum; IN-POOL = at least one, reported for contrast
           only) and emit the eval_pipeline.py-shaped query file, the qrels,
           and the provenance summary.

CRITICAL ENV (verified 2026-08-17, this script hard-fails without it)
────────────────────────────────────────────────────────────────────
`retriever._seismic_backend` only falls back to the default E8 dv-v2 shard
manifest when `self.root == <repo>/data/thinclient_index` **as an absolute
path**. Passed a RELATIVE `--index-root data/thinclient_index` the equality
fails, no manifest is found, `SFU_SPLADE_BACKEND=seismic` raises, and the SPLADE
leg SILENTLY DEGRADES TO BM25F (measured here: bm25f∩splade@50 = 50, i.e. one
leg twice) — this is exactly what happened to the §8 smoke run. This script
resolves `--index-root` to an absolute path and then PROVES the leg is real by
asserting bm25f∩splade@50 is below `--splade-parity-max` on the probe query.

`SFU_DENSE_WARMCACHE=0` is forced: the warm cache would otherwise write
`dense/delta.sqlite` inside the read-only served index root during pooling.

Run:
  .venv/bin/python3 scripts/experiments/dense_ablation_queryset.py draw
  .venv/bin/python3 scripts/experiments/dense_ablation_queryset.py pool
  .venv/bin/python3 scripts/experiments/dense_ablation_queryset.py judge --workers 6
  .venv/bin/python3 scripts/experiments/dense_ablation_queryset.py finalize
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("dense_ablation_queryset")

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "data/eval_results"
DATE = "20260817"

TOPICS_FILE = EVAL / f"dense_ablation_topics_{DATE}.json"
POOL_FILE = EVAL / f"dense_ablation_pool_{DATE}.json"
DOCS_FILE = EVAL / f"dense_ablation_pool_docs_{DATE}.json"
JUDGE_CACHE = EVAL / f"dense_ablation_judge_cache_{DATE}.json"
QRELS_FILE = EVAL / f"dense_ablation_qrels_{DATE}.json"
QUERIES_FILE = EVAL / "dense_ablation_queries.json"
SUMMARY_FILE = EVAL / f"dense_ablation_queryset_{DATE}.json"

DENSE_IDS = REPO / "data/thinclient_index/dense/ids.json"
INDEX_ROOT = REPO / "data/thinclient_index"          # ABSOLUTE — see module docstring

RELEVANT_GRADE = 2          # same threshold as both recorded dense evals
JUDGE_KEY_LEN = 80          # eval_pipeline.JUDGE_KEY_LEN / benchmark_llm_judge._cache_key
POOL_DEPTH = 50             # per leg, and the fused list

JUDGE_MODEL = "claude-haiku-4-5-20251001"
JUDGE_SYSTEM = ("You are a relevance scoring API. Output ONLY valid JSON. "
                "No markdown fences, no prose, no explanation.")
JUDGE_SCALE = {3: "perfectly relevant (directly about the query)",
               2: "highly relevant (strongly related)",
               1: "marginally relevant (tangential)",
               0: "not relevant (unrelated)"}


# ── Stage 1: the draw ───────────────────────────────────────────────────────
# 120 topics over the SAME 49 SFU subjects as diverse_queries.json, with the
# same per-subject counts (5/4/3/2/1), and NO topic reused from it — the
# `draw` stage asserts disjointness against diverse_queries.json's judge_keys.
# Each entry: (subject, keyword form, natural-language paraphrase).

TOPIC_DRAW: list[tuple[str, str, str]] = [
    # ── Health Sciences (5) ──
    ("Health Sciences",
     "type 2 diabetes prevention lifestyle intervention primary care Canada",
     "What lifestyle interventions delivered in primary care actually prevent type 2 diabetes?"),
    ("Health Sciences",
     "hospital emergency department overcrowding wait times patient outcomes",
     "How does emergency department overcrowding affect patient wait times and outcomes?"),
    ("Health Sciences",
     "childhood vaccination coverage school immunization programs uptake",
     "What drives childhood vaccination coverage and uptake in school immunization programs?"),
    ("Health Sciences",
     "palliative care access rural communities end of life symptom management",
     "How can rural communities improve access to palliative and end-of-life symptom care?"),
    ("Health Sciences",
     "wearable device physical activity monitoring chronic disease self management",
     "Can wearable activity monitors help people self-manage a chronic disease?"),
    # ── Indigenous Studies (4) ──
    ("Indigenous Studies",
     "Indigenous data sovereignty OCAP principles research governance",
     "What are Indigenous data sovereignty principles and how do they govern research?"),
    ("Indigenous Studies",
     "urban Indigenous friendship centres community services identity",
     "What role do urban friendship centres play in supporting Indigenous community and identity?"),
    ("Indigenous Studies",
     "Indigenous food sovereignty traditional harvesting country foods nutrition",
     "How does harvesting traditional country foods support Indigenous food sovereignty and nutrition?"),
    ("Indigenous Studies",
     "Metis identity scrip land dispossession prairie history",
     "How did the scrip system and land dispossession shape Metis identity on the prairies?"),
    # ── Canadian Studies (4) ──
    ("Canadian Studies",
     "Quebec language policy Bill 101 French minority rights",
     "How has Quebec's language legislation shaped French and minority language rights?"),
    ("Canadian Studies",
     "Canadian Arctic sovereignty Northwest Passage shipping governance",
     "What are the sovereignty and governance disputes over shipping in the Northwest Passage?"),
    ("Canadian Studies",
     "Canadian universal pharmacare drug coverage policy debate",
     "What is the evidence and policy debate around universal pharmacare in Canada?"),
    ("Canadian Studies",
     "interprovincial trade barriers Canadian economic union regulation",
     "How do interprovincial trade barriers affect the Canadian economic union?"),
    # ── Criminology (4) ──
    ("Criminology",
     "bail reform pretrial detention remand population Canada",
     "How does bail reform change pretrial detention and remand populations?"),
    ("Criminology",
     "intimate partner violence risk assessment protective orders",
     "How well do risk assessment tools and protective orders prevent intimate partner violence?"),
    ("Criminology",
     "gang desistance youth intervention programs street involvement",
     "What programs actually help young people leave gangs and street involvement behind?"),
    ("Criminology",
     "wildlife crime illegal trafficking enforcement conservation criminology",
     "How is illegal wildlife trafficking enforced against, and what does conservation criminology say?"),
    # ── Interactive Arts & Technology (SIAT) (4) ──
    ("Interactive Arts & Technology (SIAT)",
     "haptic feedback tangible interface design user perception",
     "How does haptic feedback in a tangible interface change what the user perceives?"),
    ("Interactive Arts & Technology (SIAT)",
     "data physicalization tangible data representation public engagement",
     "Can physical, tangible representations of data improve public engagement and understanding?"),
    ("Interactive Arts & Technology (SIAT)",
     "serious games health behaviour change gamification design",
     "Do serious games and gamified designs really change health behaviour?"),
    ("Interactive Arts & Technology (SIAT)",
     "wearable computing textile interfaces embodied interaction design",
     "How are textiles and wearable computing used to design embodied interaction?"),
    # ── Biomedical Physiology and Kinesiology (BPK) (4) ──
    ("Biomedical Physiology and Kinesiology (BPK)",
     "concussion return to play protocol youth sport recovery",
     "How do return-to-play protocols after concussion in youth sport work, and do they help recovery?"),
    ("Biomedical Physiology and Kinesiology (BPK)",
     "high altitude hypoxia ventilatory acclimatization physiology",
     "How does human ventilation acclimatize to hypoxia at high altitude?"),
    ("Biomedical Physiology and Kinesiology (BPK)",
     "thermoregulation heat strain occupational workers hydration",
     "How do workers thermoregulate under occupational heat strain, and what does hydration do?"),
    ("Biomedical Physiology and Kinesiology (BPK)",
     "gait analysis prosthetic limb amputee walking energetics",
     "How does a prosthetic limb change an amputee's gait and the energy cost of walking?"),
    # ── Resource & Environmental Management (4) ──
    ("Resource & Environmental Management",
     "eelgrass seagrass habitat restoration coastal carbon sequestration",
     "How effective is eelgrass restoration for coastal habitat and carbon sequestration?"),
    ("Resource & Environmental Management",
     "caribou herd decline habitat disturbance boreal recovery planning",
     "Why are boreal caribou herds declining and what recovery planning addresses habitat disturbance?"),
    ("Resource & Environmental Management",
     "mine tailings dam failure water quality remediation monitoring",
     "What happens to water quality after a tailings dam failure and how is it remediated?"),
    ("Resource & Environmental Management",
     "marine protected area network design fisheries spillover effects",
     "How should marine protected area networks be designed, and do they produce fisheries spillover?"),
    # ── Finance (3) ──
    ("Finance",
     "cryptocurrency market volatility bitcoin price contagion spillover",
     "How does cryptocurrency volatility spill over into other financial markets?"),
    ("Finance",
     "household debt mortgage stress test housing finance Canada",
     "How have mortgage stress tests affected household debt and housing finance in Canada?"),
    ("Finance",
     "corporate bond liquidity credit spread market microstructure",
     "What drives corporate bond liquidity and credit spreads at the market microstructure level?"),
    # ── Political Science (3) ──
    ("Political Science",
     "electoral turnout youth voter mobilization campaign contact",
     "What kinds of campaign contact actually raise youth voter turnout?"),
    ("Political Science",
     "federal provincial fiscal transfers equalization intergovernmental relations",
     "How do equalization and fiscal transfers shape federal-provincial relations?"),
    ("Political Science",
     "foreign election interference disinformation state actors democracy",
     "How do foreign state actors interfere in elections through disinformation?"),
    # ── Communication (3) ──
    ("Communication",
     "podcast audiences intimacy parasocial relationship listeners",
     "Why do podcast listeners form intimate, parasocial relationships with hosts?"),
    ("Communication",
     "news deserts local journalism decline community information",
     "What happens to a community's information supply when local journalism collapses?"),
    ("Communication",
     "influencer marketing disclosure sponsored content consumer trust",
     "Does disclosing sponsored content change how much consumers trust influencer marketing?"),
    # ── Economics (3) ──
    ("Economics",
     "minimum wage employment effects small business labour demand",
     "What are the employment effects of minimum wage increases on small business labour demand?"),
    ("Economics",
     "immigration labour market wages native workers displacement",
     "Does immigration displace native-born workers or push down their wages?"),
    ("Economics",
     "carbon border adjustment mechanism trade competitiveness leakage",
     "How would a carbon border adjustment mechanism affect trade competitiveness and carbon leakage?"),
    # ── History (3) ──
    ("History",
     "Spanish influenza 1918 pandemic public health response cities",
     "How did cities respond to the 1918 Spanish influenza pandemic?"),
    ("History",
     "fur trade Hudson's Bay Company Indigenous labour exchange networks",
     "What role did Indigenous labour and exchange networks play in the fur trade?"),
    ("History",
     "women's suffrage movement provincial franchise campaigns Canada",
     "How did provincial campaigns win women the vote in Canada?"),
    # ── Computing Science (3) ──
    ("Computing Science",
     "compiler optimization loop vectorization SIMD code generation",
     "How do optimizing compilers vectorize loops into SIMD code?"),
    ("Computing Science",
     "approximate nearest neighbour search vector index billion scale",
     "How do approximate nearest neighbour indexes scale to billions of vectors?"),
    ("Computing Science",
     "static analysis memory safety vulnerability detection C programs",
     "How does static analysis detect memory safety vulnerabilities in C programs?"),
    # ── Education (3) ──
    ("Education",
     "teacher retention burnout attrition rural schools workforce",
     "Why do teachers burn out and leave rural schools?"),
    ("Education",
     "early literacy phonics instruction reading intervention primary grades",
     "How effective is phonics instruction as an early reading intervention in the primary grades?"),
    ("Education",
     "graduate student supervision mentorship doctoral completion attrition",
     "How does supervision and mentorship affect doctoral completion and attrition?"),
    # ── Psychology (3) ──
    ("Psychology",
     "sleep deprivation memory consolidation cognitive performance",
     "How does sleep deprivation impair memory consolidation and cognitive performance?"),
    ("Psychology",
     "loneliness social isolation mental health older adults intervention",
     "What interventions reduce loneliness and social isolation among older adults?"),
    ("Psychology",
     "implicit bias measurement predictive validity discrimination behaviour",
     "Do implicit bias measures actually predict discriminatory behaviour?"),
    # ── Gender, Sexuality, and Women's Studies (2) ──
    ("Gender, Sexuality, and Women's Studies",
     "transgender healthcare access gender affirming care barriers",
     "What barriers do transgender people face getting access to gender-affirming health care?"),
    ("Gender, Sexuality, and Women's Studies",
     "unpaid care work gender division household labour time use",
     "How is unpaid care work divided by gender within households?"),
    # ── Engineering Science (2) ──
    ("Engineering Science",
     "5G millimeter wave antenna array beamforming design",
     "How are millimetre-wave antenna arrays designed for 5G beamforming?"),
    ("Engineering Science",
     "additive manufacturing metal 3D printing fatigue defects microstructure",
     "How do defects and microstructure affect fatigue life in metal 3D printed parts?"),
    # ── Mechatronic Systems Engineering (2) ──
    ("Mechatronic Systems Engineering",
     "autonomous vehicle sensor fusion lidar camera perception",
     "How do autonomous vehicles fuse lidar and camera data for perception?"),
    ("Mechatronic Systems Engineering",
     "soft robotics pneumatic actuator compliant gripper design",
     "How are soft pneumatic actuators designed into compliant robotic grippers?"),
    # ── Sociology (2) ──
    ("Sociology",
     "religious participation secularization generational change belonging",
     "How has secularization changed religious participation and belonging across generations?"),
    ("Sociology",
     "neighbourhood effects concentrated disadvantage child outcomes",
     "How does growing up in a concentrated-disadvantage neighbourhood affect children's outcomes?"),
    # ── Philosophy (2) ──
    ("Philosophy",
     "free will moral responsibility determinism compatibilism",
     "Can moral responsibility survive determinism, as compatibilists claim?"),
    ("Philosophy",
     "philosophy of mind consciousness qualia explanatory gap",
     "What is the explanatory gap between physical processes and conscious experience?"),
    # ── Mathematics (2) ──
    ("Mathematics",
     "topological data analysis persistent homology point clouds",
     "How does persistent homology extract structure from point cloud data?"),
    ("Mathematics",
     "stochastic partial differential equations numerical approximation convergence",
     "How are stochastic partial differential equations approximated numerically, and do the schemes converge?"),
    # ── Physics (2) ──
    ("Physics",
     "gravitational wave detection black hole merger interferometer",
     "How do interferometers detect gravitational waves from black hole mergers?"),
    ("Physics",
     "topological insulator edge states spin orbit coupling materials",
     "What are the edge states of a topological insulator and how does spin-orbit coupling create them?"),
    # ── Chemistry (2) ──
    ("Chemistry",
     "lithium ion battery electrolyte degradation cathode interface",
     "What degrades the electrolyte and the cathode interface in a lithium-ion battery?"),
    ("Chemistry",
     "PFAS forever chemicals water treatment removal degradation",
     "How can PFAS forever chemicals be removed or degraded during water treatment?"),
    # ── Business Administration (2) ──
    ("Business Administration",
     "remote work hybrid arrangements productivity employee wellbeing",
     "How do hybrid and remote work arrangements affect productivity and employee wellbeing?"),
    ("Business Administration",
     "family business succession planning governance next generation",
     "How do family businesses plan succession and govern the handover to the next generation?"),
    # ── Labour Studies (2) ──
    ("Labour Studies",
     "migrant agricultural workers temporary foreign worker program conditions",
     "What working conditions do migrant agricultural workers face under temporary foreign worker programs?"),
    ("Labour Studies",
     "workplace automation job displacement reskilling worker adjustment",
     "How does workplace automation displace jobs, and what reskilling helps workers adjust?"),
    # ── Linguistics (2) ──
    ("Linguistics",
     "code switching bilingual speakers sociolinguistic variation",
     "Why do bilingual speakers code-switch, and how does it vary socially?"),
    ("Linguistics",
     "prosody intonation speech perception listener comprehension",
     "How do prosody and intonation shape the way listeners comprehend speech?"),
    # ── English - General (2) ──
    ("English - General",
     "modernist poetry fragmentation form early twentieth century",
     "How did early twentieth-century modernist poets use fragmentation of poetic form?"),
    ("English - General",
     "graphic novels comics studies narrative visual storytelling",
     "How do comics and graphic novels tell stories through visual narrative?"),
    # ── Film (2) ──
    ("Film",
     "film festival circuit curation programming world cinema",
     "How does festival programming and curation shape what counts as world cinema?"),
    ("Film",
     "sound design film music affect audience emotional response",
     "How do sound design and film music shape an audience's emotional response?"),
    # ── Geography (2) ──
    ("Geography",
     "glacier retreat mass balance monitoring mountain water supply",
     "How does glacier retreat, measured through mass balance, affect mountain water supply?"),
    ("Geography",
     "coastal erosion sea level rise shoreline retreat adaptation",
     "How are communities adapting to shoreline retreat from coastal erosion and sea level rise?"),
    # ── Gerontology (2) ──
    ("Gerontology",
     "falls prevention older adults balance training home hazards",
     "What prevents falls in older adults - balance training, or removing home hazards?"),
    ("Gerontology",
     "social prescribing older adults community programs wellbeing",
     "Does social prescribing to community programs improve older adults' wellbeing?"),
    # ── Anthropology (2) ──
    ("Anthropology",
     "ritual kinship exchange gift economies ethnography Melanesia",
     "How do gift economies and ritual exchange structure kinship in Melanesia?"),
    ("Anthropology",
     "migration transnational families remittances belonging ethnography",
     "How do transnational families sustain belonging across migration and remittances?"),
    # ── Archaeology (2) ──
    ("Archaeology",
     "radiocarbon dating chronology Bayesian modelling stratigraphy",
     "How is Bayesian modelling used with radiocarbon dates to build site chronologies?"),
    ("Archaeology",
     "ancient DNA population migration archaeogenetics prehistoric Europe",
     "What does ancient DNA reveal about prehistoric population migration in Europe?"),
    # ── International Studies (2) ──
    ("International Studies",
     "refugee resettlement burden sharing international protection regime",
     "How is responsibility for refugee resettlement shared under the international protection regime?"),
    ("International Studies",
     "economic sanctions effectiveness compliance target state behaviour",
     "Do economic sanctions actually change the behaviour of the states they target?"),
    # ── Latin American Studies (2) ──
    ("Latin American Studies",
     "Cuban revolution health system export medical diplomacy",
     "How does Cuba use medical diplomacy and health system exports as foreign policy?"),
    ("Latin American Studies",
     "Andean agrarian reform peasant movements land tenure",
     "How did agrarian reform and peasant movements reshape land tenure in the Andes?"),
    # ── Urban Studies (2) ──
    ("Urban Studies",
     "informal settlements upgrading tenure security global south cities",
     "How does upgrading informal settlements improve tenure security in global south cities?"),
    ("Urban Studies",
     "cycling infrastructure bike lanes mode shift urban mobility",
     "Does building bike lanes actually shift people onto bicycles?"),
    # ── Applied Legal Studies (2) ──
    ("Applied Legal Studies",
     "access to justice self represented litigants legal aid funding",
     "How do self-represented litigants and legal aid funding shape access to justice?"),
    ("Applied Legal Studies",
     "environmental litigation climate lawsuits state liability courts",
     "How are courts handling climate lawsuits and state liability for emissions?"),
    # ── Molecular Biology & Biochemistry (2) ──
    ("Molecular Biology & Biochemistry",
     "gut microbiome host immune interaction metabolite signalling",
     "How does the gut microbiome signal to the host immune system through metabolites?"),
    ("Molecular Biology & Biochemistry",
     "mRNA vaccine lipid nanoparticle delivery stability formulation",
     "How do lipid nanoparticles deliver mRNA vaccines, and what governs their stability?"),
    # ── Music (2) ──
    ("Music",
     "jazz improvisation performance analysis interaction ensemble",
     "How do jazz musicians interact with each other during ensemble improvisation?"),
    ("Music",
     "music streaming royalties artist income platform economics",
     "How do streaming platform economics determine what artists earn in royalties?"),
    # ── Public Policy (2) ──
    ("Public Policy",
     "childcare policy universal early learning affordability workforce",
     "How does universal early learning and childcare policy affect affordability and workforce participation?"),
    ("Public Policy",
     "public procurement innovation policy government purchasing outcomes",
     "Can government purchasing be used as an innovation policy lever?"),
    # ── Global Health (2) ──
    ("Global Health",
     "maternal mortality skilled birth attendance low resource settings",
     "How much does skilled birth attendance reduce maternal mortality in low-resource settings?"),
    ("Global Health",
     "neglected tropical disease mass drug administration elimination",
     "How effective is mass drug administration at eliminating neglected tropical diseases?"),
    # ── Sustainable Energy Engineering (SEE) (2) ──
    ("Sustainable Energy Engineering (SEE)",
     "solar photovoltaic degradation module reliability field performance",
     "Why do solar photovoltaic modules degrade, and how reliable are they in the field?"),
    ("Sustainable Energy Engineering (SEE)",
     "district heating waste heat recovery thermal network efficiency",
     "How does waste heat recovery improve the efficiency of a district heating network?"),
    # ── Accounting (2) ──
    ("Accounting",
     "auditor independence non-audit services fee dependence quality",
     "Do non-audit service fees compromise auditor independence and audit quality?"),
    ("Accounting",
     "revenue recognition standard IFRS 15 adoption financial reporting",
     "How did adopting IFRS 15 change revenue recognition in financial reporting?"),
    # ── Statistics & Actuarial Science (2) ──
    ("Statistics & Actuarial Science",
     "causal inference propensity score matching observational studies",
     "How is propensity score matching used for causal inference in observational studies?"),
    ("Statistics & Actuarial Science",
     "extreme value theory tail risk catastrophe insurance modelling",
     "How does extreme value theory model tail risk for catastrophe insurance?"),
    # ── Visual Arts (2) ──
    ("Visual Arts",
     "socially engaged art practice participation community collaboration",
     "What does socially engaged art practice mean for participation and community collaboration?"),
    ("Visual Arts",
     "conservation of contemporary art materials degradation museum practice",
     "How do museums conserve contemporary artworks whose materials are degrading?"),
    # ── Theatre (2) ──
    ("Theatre",
     "dramaturgy new play development workshop process",
     "How does dramaturgy shape the development of a new play through workshops?"),
    ("Theatre",
     "puppetry object theatre performance materiality audience",
     "How do puppetry and object theatre use materiality to engage an audience?"),
    # ── Publishing (2) ──
    ("Publishing",
     "audiobook market growth narration production publishing industry",
     "How is audiobook production and narration reshaping the publishing industry?"),
    ("Publishing",
     "peer review reform preprints open science scholarly communication",
     "How are preprints and open science reforming peer review and scholarly communication?"),
    # ── Sustainable Community Development (2) ──
    ("Sustainable Community Development",
     "community land trust affordable housing stewardship models",
     "How do community land trusts steward permanently affordable housing?"),
    ("Sustainable Community Development",
     "participatory budgeting civic engagement municipal decision making",
     "Does participatory budgeting actually increase civic engagement in municipal decisions?"),
    # ── Management & Organizational Studies (2) ──
    ("Management & Organizational Studies",
     "psychological safety team performance speaking up organizations",
     "How does psychological safety affect whether people speak up and how teams perform?"),
    ("Management & Organizational Studies",
     "corporate social responsibility greenwashing stakeholder perception",
     "How do stakeholders tell real corporate social responsibility from greenwashing?"),
    # ── Forensics (1) ──
    ("Forensics",
     "forensic entomology postmortem interval insect succession estimation",
     "How does forensic entomology use insect succession to estimate the postmortem interval?"),
]


def cmd_draw(args) -> None:
    """Write the topic table. NOTHING is retrieved or judged here — this file is
    committed BEFORE the pool/judge stages so the draw is on the record."""
    prior = {q["judge_key"] for q in
             json.loads((EVAL / "diverse_queries.json").read_text())}

    topics, seen = [], set()
    for subject, kw, nl in TOPIC_DRAW:
        if len(kw) > JUDGE_KEY_LEN:
            raise SystemExit(f"keyword form > {JUDGE_KEY_LEN} chars (judge_key "
                             f"would be truncated and stop matching): {kw!r}")
        if kw in seen:
            raise SystemExit(f"duplicate topic in the draw: {kw!r}")
        if kw in prior:
            raise SystemExit(f"topic reused from diverse_queries.json (the draw "
                             f"must be NEW — §7): {kw!r}")
        seen.add(kw)
        topics.append({"judge_key": kw, "subject": subject,
                       "keyword": kw, "natural": nl})

    subjects = sorted({t["subject"] for t in topics})
    out = {
        "drawn_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "what": ("the FRESH topic draw for the pre-registered dense-leg ablation "
                 "(docs/DENSE_PARTITION_AND_ABLATION.md §7). Committed BEFORE "
                 "any retrieval or judgment, so the draw is on the record."),
        "protocol": {
            "n_topics": len(topics),
            "forms_per_topic": ["keyword", "natural"],
            "n_query_records": 2 * len(topics),
            "subject_spread": ("the same 49 SFU subjects and the same per-subject "
                               "counts as data/eval_results/diverse_queries.json"),
            "disjoint_from": "data/eval_results/diverse_queries.json (asserted here)",
            "judge_key": "the keyword form (<= 80 chars, so it is never truncated)",
            "judged_later_on": ("the NATURAL-language form — §4's only robust "
                                "finding is that the dense effect is NL-shaped"),
        },
        "subjects": {s: sum(1 for t in topics if t["subject"] == s) for s in subjects},
        "topics": topics,
    }
    TOPICS_FILE.write_text(json.dumps(out, indent=2) + "\n")
    log.info("drew %d topics over %d subjects -> %s",
             len(topics), len(subjects), TOPICS_FILE)


# ── Stage 2: pooling retrieval ──────────────────────────────────────────────

def _query_records(topics: list[dict]) -> list[dict]:
    """The 2 forms per topic, in a stable order."""
    rows = []
    for t in topics:
        rows.append({"query": t["keyword"], "judge_key": t["judge_key"],
                     "query_type": "keyword", "subject": t["subject"]})
        rows.append({"query": t["natural"], "judge_key": t["judge_key"],
                     "query_type": "natural", "subject": t["subject"]})
    return rows


def cmd_pool(args) -> None:
    os.environ["SFU_DENSE_WARMCACHE"] = "0"      # never write into the served root
    sys.path.insert(0, str(REPO / "source"))
    from lib.thinclient.retriever import ThinClientRetriever

    root = Path(args.index_root).resolve()       # ABSOLUTE — see module docstring
    topics = json.loads(TOPICS_FILE.read_text())["topics"]
    rows = _query_records(topics)

    r = ThinClientRetriever(index_root=str(root), remote_abstracts=False)
    if not r.is_available():
        raise SystemExit(f"thin-client index at {root} not available")
    m = r.metrics()
    if not (m["dense_leg_enabled"] and m["dense_vectors"] > 0):
        raise SystemExit("dense leg is OFF — pooling must run the FULL 3-leg "
                         "config so both future arms' candidates are pooled")

    # ── PROVE the SPLADE leg is real before judging anything (§7 / WS-I) ──
    probe = r.search_rrf_detailed(args.probe_query, top_k=POOL_DEPTH,
                                  include_dense=True)
    overlap = len(set(probe["legs"]["bm25f"]) & set(probe["legs"]["splade"]))
    log.info("SPLADE reality probe: bm25f∩splade@%d = %d (max allowed %d)",
             POOL_DEPTH, overlap, args.splade_parity_max)
    if overlap > args.splade_parity_max:
        raise SystemExit(
            f"SPLADE leg looks like a BM25F fallback (bm25f∩splade@{POOL_DEPTH}"
            f" = {overlap}). The usual cause is a RELATIVE --index-root: the "
            f"default SEISMIC manifest is only selected when the retriever's "
            f"root equals the ABSOLUTE <repo>/data/thinclient_index. Fix the "
            f"env/root and re-run — do NOT judge a broken pool.")

    docs: dict[str, dict] = {}
    if DOCS_FILE.exists():
        docs = json.loads(DOCS_FILE.read_text())
    records: list[dict] = []
    if POOL_FILE.exists() and not args.restart:
        prev = json.loads(POOL_FILE.read_text())
        records = prev.get("queries", [])
    done = {rec["query"] for rec in records}

    def flush() -> None:
        POOL_FILE.write_text(json.dumps({
            "pooled_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "what": ("TREC-style pooling retrieval for the dense-leg ablation "
                     "query set. FULL 3-leg config (dense ON) so the pool "
                     "contains every candidate EITHER arm could surface."),
            "NOT_AN_ABLATION_RUN": (
                "untimed, single arm, dense ON, page cache never dropped, warm "
                "cache pinned off — the recorded lat_*_ms are incidental and "
                "MUST NOT be quoted as ablation latency."),
            "config": {
                "index_root": str(root),
                "pool_depth_per_leg": POOL_DEPTH,
                "dense_leg_enabled": m["dense_leg_enabled"],
                "dense_vectors": m["dense_vectors"],
                "splade_backend": r._splade_backend,
                "splade_probe": {"query": args.probe_query,
                                 "bm25f_splade_overlap@50": overlap},
                "env": {v: os.environ.get(v) for v in
                        ("SFU_DENSE_LEG", "SFU_DENSE_WARMCACHE",
                         "SFU_SPLADE_BACKEND", "SFU_SEISMIC_SHARD_MANIFEST",
                         "SFU_SEISMIC_STAGE_DIR", "SFU_SEISMIC_FEDERATION")},
            },
            "queries": records,
        }, indent=2) + "\n")
        DOCS_FILE.write_text(json.dumps(docs, indent=2) + "\n")

    for i, rec in enumerate(rows):
        if rec["query"] in done:
            continue
        det = r.search_rrf_detailed(rec["query"], top_k=POOL_DEPTH,
                                    include_dense=True)
        fused = [d["openalex_id"] for d in det["results"]]
        row = dict(rec)
        for leg in ("bm25f", "splade", "dense"):
            if leg in det["legs"]:
                row[leg] = det["legs"][leg]
                row[f"lat_{leg}_ms"] = det["leg_latency_ms"][leg]
        row["rrf"] = fused
        row["rrf_legs"] = [d["rrf_legs"] for d in det["results"]]
        pool = list(dict.fromkeys(
            [d for leg in ("bm25f", "splade", "dense")
             for d in det["legs"].get(leg, [])] + fused))
        row["pool"] = pool
        records.append(row)

        # Hydrate title+abstract for anything new in the pool.
        need = [d for d in pool if d not in docs]
        if need:
            meta = r._meta_rows(need)
            abstracts = r.fetch_abstracts(need)
            for did in need:
                mrow = meta.get(did)
                docs[did] = {"title": (mrow[1] if mrow else "") or "",
                             "abstract": abstracts.get(did, "") or ""}
        if (i + 1) % 10 == 0:
            log.info("  %d/%d query forms pooled (%d unique docs)",
                     i + 1, len(rows), len(docs))
            flush()
    flush()
    sizes = [len(x["pool"]) for x in records]
    log.info("pooled %d query forms; per-query pool mean %.1f; %d unique docs -> %s",
             len(records), sum(sizes) / max(1, len(sizes)), len(docs), POOL_FILE)


# ── Stage 2b: abstract backfill ─────────────────────────────────────────────

def cmd_hydrate(args) -> None:
    """Backfill abstracts the local sidecars did not carry, from the OpenAlex
    API (same inverted-index reconstruction the retriever's
    `_fetch_remote_abstracts` uses).

    WHY: 58.1% of the 25,614 pooled docs had no local abstract (measured
    2026-08-17). That is NOT a dense-leg bias — the per-leg title-only rates are
    bm25f 64.1% / splade 52.0% / dense 57.2%, i.e. the lexical legs are hit at
    least as hard — but judging three quarters of a pool on titles alone is a
    weaker gradebook than the protocol deserves. Docs still missing an abstract
    after this stage are judged on title and flagged `title_only` in the qrels."""
    import requests
    sys.path.insert(0, str(REPO / "source"))
    from lib.thinclient.retriever import _invert_abstract

    docs = json.loads(DOCS_FILE.read_text())
    missing = [d for d, v in docs.items() if not v.get("abstract")]
    log.info("backfill: %d/%d pooled docs have no local abstract",
             len(missing), len(docs))
    session = requests.Session()
    filled = 0
    for i in range(0, len(missing), args.batch):
        chunk = missing[i:i + args.batch]
        params = {"filter": "openalex_id:" + "|".join(chunk),
                  "per-page": len(chunk),
                  "select": "id,abstract_inverted_index",
                  "mailto": os.environ.get("OPENALEX_MAILTO", "<contact>")}
        key = os.environ.get("OPENALEX_API_KEY", "").strip()
        if key:
            params["api_key"] = key
        for attempt in range(3):
            try:
                resp = session.get("https://api.openalex.org/works", params=params,
                                   headers={"User-Agent": "SFULibraryMCP-Eval/1.0"},
                                   timeout=40)
                if resp.status_code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                for w in resp.json().get("results", []):
                    wid = (w.get("id") or "").rsplit("/", 1)[-1]
                    inv = w.get("abstract_inverted_index")
                    if wid in docs and inv:
                        docs[wid]["abstract"] = _invert_abstract(inv)
                        filled += 1
                break
            except Exception as exc:
                if attempt == 2:
                    log.warning("backfill chunk failed: %s", exc)
                time.sleep(2 * (attempt + 1))
        time.sleep(0.15)
        if (i // args.batch + 1) % 20 == 0:
            log.info("  %d/%d requested, %d filled", i + len(chunk), len(missing), filled)
            DOCS_FILE.write_text(json.dumps(docs, indent=2) + "\n")
    DOCS_FILE.write_text(json.dumps(docs, indent=2) + "\n")
    still = sum(1 for v in docs.values() if not v.get("abstract"))
    log.info("backfill done: +%d abstracts; %d/%d (%.1f%%) still title-only",
             filled, still, len(docs), 100 * still / max(1, len(docs)))


# ── Stage 3: the judge (protocol from benchmark_llm_judge.py) ───────────────

_cache_lock = threading.Lock()


def _cache_key(judge_key: str, oid: str) -> str:
    """Same shape as benchmark_llm_judge._cache_key / eval_pipeline's
    `key.rsplit('||', 1)` reader, so this cache is a drop-in --judge-cache."""
    return f"{judge_key[:JUDGE_KEY_LEN]}||{oid}"


def _judge_prompt(nl_query: str, papers: list[dict]) -> str:
    lines = [f'Score each paper 0-3 for relevance to: "{nl_query}"\n',
             "3=perfectly relevant  2=highly relevant  1=marginal  0=unrelated\n"]
    for p in papers:
        lines.append(f'[{p["id"]}]\nTitle: {(p["title"] or "")[:200]}')
        if p["abstract"]:
            lines.append(f'Abstract: {p["abstract"][:400]}')
        lines.append("")
    lines.append('Reply ONLY with JSON: {"<id>": score, ...}')
    return "\n".join(lines)


PROMPT_TEMPLATE_HASH = hashlib.sha256(
    (JUDGE_SYSTEM + "\n" + _judge_prompt("<QUERY>", [
        {"id": "<ID>", "title": "<TITLE>", "abstract": "<ABSTRACT>"}])
     ).encode()).hexdigest()[:16]


def _call_claude(prompt: str, timeout: int = 120) -> str:
    res = subprocess.run(
        ["claude", "-p", "--model", JUDGE_MODEL, "--output-format", "text",
         "--system-prompt", JUDGE_SYSTEM, "--no-session-persistence"],
        input=prompt, capture_output=True, text=True, timeout=timeout)
    return res.stdout.strip()


def _parse_scores(text: str) -> dict[str, int]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        raw = json.loads(match.group())
    except Exception:
        return {}
    out = {}
    for k, v in raw.items():
        try:
            out[str(k)] = max(0, min(3, int(v)))
        except Exception:
            continue
    return out


def _judge_batch(nl_query: str, papers: list[dict]) -> dict[str, int]:
    """Judge one batch. A reply is only ACCEPTED if at least one returned key is
    an id we actually asked about.

    Why the id check exists (incident 2026-08-18): a reply that parses as JSON
    but whose keys match nothing in the batch used to be accepted as a success.
    Every paper then fell through `scores.get(id, 0)` to grade 0 and NOTHING was
    logged — a silent all-zero. A transient service window mid-run wrote exactly
    that for 55 consecutive topics (a contiguous block of the draw order, which
    is what exposed it as an outage rather than a content result). Unmatched keys
    are now a FAILURE: retried, then split to solo calls, and finally surfaced by
    the topic-level all-zero guard in `cmd_judge`."""
    if not papers:
        return {}
    want = {p["id"] for p in papers}
    prompt = _judge_prompt(nl_query, papers)
    for attempt in range(3):
        try:
            scores = _parse_scores(_call_claude(prompt))
            matched = set(scores) & want
            # Require a MAJORITY of the batch to come back. A reply that names
            # only a stray id would otherwise be accepted and silently zero the
            # other 11 papers.
            if scores and len(matched) * 2 >= len(want):
                return scores
            if scores:
                log.warning("judge reply matched %d/%d batch ids (attempt %d) "
                            "— keys=%s", len(matched), len(want), attempt + 1,
                            list(scores)[:3])
        except subprocess.TimeoutExpired:
            log.warning("judge timeout (attempt %d)", attempt + 1)
        except Exception as exc:
            log.warning("judge failed (attempt %d): %s", attempt + 1, exc)
        time.sleep(1.5 * (attempt + 1))
    return {}


def cmd_judge(args) -> None:
    topics = {t["judge_key"]: t for t in
              json.loads(TOPICS_FILE.read_text())["topics"]}
    pool = json.loads(POOL_FILE.read_text())["queries"]
    docs = json.loads(DOCS_FILE.read_text())

    # Pool per TOPIC = union over BOTH query forms (judgments are reused across
    # forms by judge_key, exactly as diverse_queries.json does).
    per_topic: dict[str, list[str]] = {}
    for row in pool:
        seen = per_topic.setdefault(row["judge_key"], [])
        for did in row["pool"]:
            if did not in seen:
                seen.append(did)

    cache: dict[str, int] = {}
    if JUDGE_CACHE.exists():
        cache = json.loads(JUDGE_CACHE.read_text())

    if args.repair:
        # Purge every topic whose ENTIRE pool graded 0 so it is judged again.
        # A real 200-doc pool from a live 3-leg retrieval always contains
        # something relevant; an all-zero topic is an outage signature, not a
        # result (see `_judge_batch`). Idempotent: a topic that comes back
        # all-zero twice is reported by the guard below rather than looping.
        by_topic: dict[str, list[str]] = {}
        for key in cache:
            by_topic.setdefault(key.rpartition("||")[0], []).append(key)
        purged = [jk for jk, keys in by_topic.items()
                  if keys and max(cache[k] for k in keys) == 0]
        for jk in purged:
            for k in by_topic[jk]:
                del cache[k]
        log.warning("repair: purged %d all-zero topics (%d pairs) for re-judging",
                    len(purged), sum(len(by_topic[jk]) for jk in purged))

    todo = [(jk, [d for d in dids if _cache_key(jk, d) not in cache])
            for jk, dids in per_topic.items()]
    todo = [(jk, dids) for jk, dids in todo if dids]
    n_new = sum(len(d) for d in (x[1] for x in todo))
    log.info("judge: %d topics, %d pooled pairs, %d cached, %d to judge "
             "(model=%s, batch=%d, workers=%d)",
             len(per_topic), sum(len(v) for v in per_topic.values()),
             len(cache), n_new, JUDGE_MODEL, args.batch_size, args.workers)
    if args.dry_run:
        return

    def judge_pass(jk: str, nl: str, dids: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in range(0, len(dids), args.batch_size):
            batch = [{"id": d, "title": docs.get(d, {}).get("title", ""),
                      "abstract": docs.get(d, {}).get("abstract", "")}
                     for d in dids[i:i + args.batch_size]]
            scores = _judge_batch(nl, batch)
            missed = [p for p in batch if p["id"] not in scores]
            if missed and len(missed) < len(batch):
                for p in missed:
                    scores.update(_judge_batch(nl, [p]))
            for p in batch:
                out[p["id"]] = int(scores.get(p["id"], 0))
        return out

    def judge_topic(item) -> tuple[str, int]:
        jk, dids = item
        nl = topics[jk]["natural"]
        graded = judge_pass(jk, nl, dids)
        # An entire topic grading 0 across a live 3-leg pool is an outage
        # signature, not a result (incident 2026-08-18: two service windows wrote
        # exactly that for 55 and then 25 consecutive topics). Retry the whole
        # topic ONCE before accepting it.
        if graded and max(graded.values()) == 0:
            log.warning("all-zero pass on %r (%d docs) — retrying the topic once",
                        jk[:50], len(graded))
            time.sleep(5)
            retry = judge_pass(jk, nl, dids)
            if retry and max(retry.values()) > 0:
                graded = retry
        got = len(graded)
        with _cache_lock:
            for did, g in graded.items():
                cache[_cache_key(jk, did)] = g
        with _cache_lock:                      # checkpoint per topic
            grades = [cache[_cache_key(jk, d)] for d in per_topic[jk]
                      if _cache_key(jk, d) in cache]
            if grades and max(grades) == 0:
                log.warning("ALL-ZERO topic %r over %d pooled docs — treat as a "
                            "judging failure, not a result; re-run with --repair",
                            jk[:50], len(grades))
            JUDGE_CACHE.write_text(json.dumps(cache, indent=2))
        return jk, got

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for fut in concurrent.futures.as_completed(
                [ex.submit(judge_topic, it) for it in todo]):
            try:
                jk, got = fut.result()
            except Exception as exc:
                log.warning("topic judging failed: %s", exc)
                continue
            done += 1
            if done % 5 == 0:
                log.info("  judged %d/%d topics", done, len(todo))
    JUDGE_CACHE.write_text(json.dumps(cache, indent=2))
    log.info("judge cache: %d pairs -> %s", len(cache), JUDGE_CACHE)


# ── Stage 4: stratify + emit ────────────────────────────────────────────────

def _coverage_bands(qrels: dict) -> dict:
    """How much of each topic's ground truth sits inside the served 600k dense
    pool. The binary HELD-OUT/IN-POOL split collapses this to `== 0`; the bands
    show what the split is hiding. Topics with no relevant doc are excluded."""
    cov = [q["dense_pool_coverage"] for q in qrels.values()
           if q["dense_pool_coverage"] is not None]
    cov.sort()
    bands = {"==0 (strict HELD-OUT)": sum(1 for c in cov if c == 0),
             "0 < c <= 0.05": sum(1 for c in cov if 0 < c <= 0.05),
             "0.05 < c <= 0.10": sum(1 for c in cov if 0.05 < c <= 0.10),
             "0.10 < c <= 0.25": sum(1 for c in cov if 0.10 < c <= 0.25),
             "0.25 < c <= 0.50": sum(1 for c in cov if 0.25 < c <= 0.50),
             "c > 0.50": sum(1 for c in cov if c > 0.50)}
    n = len(cov)
    return {"n_topics_with_ground_truth": n,
            "bands": bands,
            "median": round(cov[n // 2], 4) if n else None,
            "mean": round(sum(cov) / n, 4) if n else None,
            "comparison": ("the CONTAMINATED standard set (diverse_queries.json) "
                           "measured 90.3% of relevant docs inside this same pool "
                           "with 0 topics at zero and 50/120 FULLY covered "
                           "(dense_pool_contamination_20260817.json)")}


def cmd_finalize(args) -> None:
    meta = json.loads(TOPICS_FILE.read_text())
    topics = meta["topics"]
    pool = json.loads(POOL_FILE.read_text())
    docs = json.loads(DOCS_FILE.read_text())
    cache = json.loads(JUDGE_CACHE.read_text())
    dense_ids = set(json.loads(DENSE_IDS.read_text()))

    graded: dict[str, dict[str, int]] = {}
    for key, grade in cache.items():
        jk, _, did = key.rpartition("||")
        graded.setdefault(jk, {})[did] = int(grade)

    per_topic_pool: dict[str, set[str]] = {}
    for row in pool["queries"]:
        per_topic_pool.setdefault(row["judge_key"], set()).update(row["pool"])

    # dense_pool_contamination.py's rule, applied per topic.
    strata: dict[str, str] = {}
    qrels = {}
    grade_hist = {0: 0, 1: 0, 2: 0, 3: 0}
    n_rel_total = n_rel_in_pool = 0
    no_abstract = 0
    for t in topics:
        jk = t["judge_key"]
        gb = graded.get(jk, {})
        rel = {d for d, g in gb.items() if g >= RELEVANT_GRADE}
        rel_in = rel & dense_ids
        n_rel_total += len(rel)
        n_rel_in_pool += len(rel_in)
        for g in gb.values():
            grade_hist[g] = grade_hist.get(g, 0) + 1
        if not rel:
            stratum = "NO-GT"          # nothing relevant judged at all
        elif rel_in:
            stratum = "IN-POOL"        # contrast only — never production benefit
        else:
            stratum = "HELD-OUT"       # THE DECISION STRATUM (§7)
        strata[jk] = stratum
        entries = []
        for did in sorted(per_topic_pool.get(jk, ())):
            g = gb.get(did, 0)
            has_abs = bool(docs.get(did, {}).get("abstract"))
            no_abstract += 0 if has_abs else 1
            entries.append({"openalex_id": did, "grade": g,
                            "gain": 2 ** g - 1,
                            "relevant": g >= RELEVANT_GRADE,
                            "in_dense_pool": did in dense_ids,
                            "title_only": not has_abs})
        qrels[jk] = {"subject": t["subject"], "natural": t["natural"],
                     "stratum": stratum, "pool_size": len(entries),
                     "n_relevant": len(rel), "n_relevant_in_dense_pool": len(rel_in),
                     "dense_pool_coverage": round(len(rel_in) / len(rel), 4) if rel else None,
                     "docs": entries}

    # eval_pipeline.py --queries shape.
    queries = []
    for t in topics:
        for form in ("keyword", "natural"):
            queries.append({
                "paraphrase": t[form],
                "original_query": t["keyword"],
                "judge_key": t["judge_key"],
                "query_type": form,
                "subject": t["subject"],
                "stratum": strata[t["judge_key"]],
            })
    QUERIES_FILE.write_text(json.dumps(queries, indent=2) + "\n")
    QRELS_FILE.write_text(json.dumps({
        "what": ("judgments for the fresh dense-ablation query set. grade 0-3 "
                 "topical relevance; relevant = grade >= 2; gain = 2^grade - 1."),
        "judge": f"{JUDGE_MODEL} via claude CLI subprocess",
        "judged_on": "the NATURAL-language form of each topic",
        "relevant_grade_threshold": RELEVANT_GRADE,
        "topics": qrels,
    }, indent=2) + "\n")

    counts = {s: sum(1 for v in strata.values() if v == s)
              for s in ("HELD-OUT", "IN-POOL", "NO-GT")}
    pool_sizes = [len(v) for v in per_topic_pool.values()]
    per_form = [len(row["pool"]) for row in pool["queries"]]
    summary = {
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dates": {
            "drawn": meta["drawn_utc"],
            "pooled": pool["pooled_utc"],
            "judged_through": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "note": ("the draw and the pooling ran 2026-08-17 UTC; judging ran "
                     "2026-08-17 into 2026-08-18 UTC. File stems keep the "
                     "20260817 draw date."),
        },
        "what": ("the fresh judged query set for the pre-registered dense-leg "
                 "ablation (docs/DENSE_PARTITION_AND_ABLATION.md §7). "
                 "THE ABLATION ITSELF IS NOT RUN — these are query-set "
                 "construction statistics, never ablation results."),
        "topics": {
            "n_topics": len(topics),
            "n_query_records": len(queries),
            "forms_per_topic": ["keyword", "natural"],
            "n_subjects": len({t["subject"] for t in topics}),
            "disjoint_from_diverse_queries": True,
        },
        "strata": {
            "HELD-OUT_decision_stratum": counts["HELD-OUT"],
            "IN-POOL_contrast_only": counts["IN-POOL"],
            "NO-GT_no_relevant_doc_judged": counts["NO-GT"],
            "rule": ("dense_pool_contamination.py: HELD-OUT = zero grade>=2 docs "
                     "present in data/thinclient_index/dense/ids.json"),
            "coverage_distribution": _coverage_bands(qrels),
            "WARNING": (
                "the PRE-REGISTERED binary rule is degenerate on a pool that "
                "includes the dense leg's OWN top-50. §7 was written when the "
                "only judged docs came from bm25f/splade/rrf/openalex, so 'zero "
                "relevant docs in the pool' was reachable. Here ~100 dense-pool "
                "docs per topic are judged, and a semantic retriever over 600k "
                "academic papers almost always surfaces at least ONE relevant "
                "paper — so almost no topic scores a strict zero. The graded "
                "`coverage_distribution` above is the honest instrument; using "
                "it as the decision stratum is a CHANGE TO A PRE-REGISTERED "
                "PROTOCOL and must be signed off before the ablation runs, not "
                "chosen after seeing an arm."),
        },
        "pool": {
            "depth_per_leg": POOL_DEPTH,
            "legs_pooled": ["bm25f", "splade", "dense", "rrf(fused)"],
            "unique_docs_pooled": len(docs),
            "per_query_form_pool_mean": round(sum(per_form) / max(1, len(per_form)), 1),
            "per_topic_pool_mean": round(sum(pool_sizes) / max(1, len(pool_sizes)), 1),
            "per_topic_pool_min": min(pool_sizes) if pool_sizes else 0,
            "per_topic_pool_max": max(pool_sizes) if pool_sizes else 0,
            "splade_probe": pool["config"]["splade_probe"],
            "splade_leg_is_real": (
                "bm25f∩splade@50 mean over all 240 forms = "
                f"{round(sum(len(set(r['bm25f']) & set(r['splade'])) for r in pool['queries']) / len(pool['queries']), 2)}"
                " — matches thinclient_parity_seismic_e8dv2_20260817.json's 5.35, "
                "so the SEISMIC leg was genuinely serving (50 would mean a silent "
                "BM25F fallback)"),
            "dense_bm25f_overlap@50_mean": round(
                sum(len(set(r["dense"]) & set(r["bm25f"])) for r in pool["queries"]
                    if "dense" in r) / max(1, sum(1 for r in pool["queries"] if "dense" in r)), 3),
            "dense_splade_overlap@50_mean": round(
                sum(len(set(r["dense"]) & set(r["splade"])) for r in pool["queries"]
                    if "dense" in r) / max(1, sum(1 for r in pool["queries"] if "dense" in r)), 3),
            "retrieval_env": pool["config"]["env"],
        },
        "judgments": {
            "n_pairs": len(cache),
            "grade_histogram": {str(k): v for k, v in sorted(grade_hist.items())},
            "n_relevant_grade_ge_2": n_rel_total,
            "n_relevant_inside_served_dense_pool": n_rel_in_pool,
            "relevant_in_dense_pool_frac": round(
                n_rel_in_pool / n_rel_total, 4) if n_rel_total else 0.0,
            "judged_pairs_without_abstract_title_only": no_abstract,
            "pool_docs_title_only_after_backfill": sum(
                1 for v in docs.values() if not v.get("abstract")),
            "abstract_source": ("thin-client AbstractStore sidecars first "
                                "(remote_abstracts=False during pooling), then an "
                                "OpenAlex backfill for what the sidecars lacked "
                                "(`hydrate` stage): 58.1% of the 25,614 pooled docs "
                                "were title-only locally — evenly across legs "
                                "(bm25f 64.1% / splade 52.0% / dense 57.2%, so NOT "
                                "a dense-leg bias) — and the backfill took that to "
                                "11.0%"),
            "judge_model": JUDGE_MODEL,
            "judge_backend": "claude CLI subprocess (-p --output-format text)",
            "prompt_template_sha256_16": PROMPT_TEMPLATE_HASH,
            "relevance_scale": {str(k): v for k, v in JUDGE_SCALE.items()},
            "gain": "2^grade - 1",
            "judged_on": ("the NATURAL-language form of each topic; the cache key "
                          "is the KEYWORD form (= judge_key), which is how both "
                          "forms share one gradebook"),
        },
        "files": {
            "topic_draw": str(TOPICS_FILE.relative_to(REPO)),
            "pooling_record": str(POOL_FILE.relative_to(REPO)),
            "pool_doc_store": str(DOCS_FILE.relative_to(REPO)),
            "judge_cache": str(JUDGE_CACHE.relative_to(REPO)),
            "qrels": str(QRELS_FILE.relative_to(REPO)),
            "query_set": str(QUERIES_FILE.relative_to(REPO)),
            "builder": "scripts/experiments/dense_ablation_queryset.py",
        },
        "caveats": [
            "The pooling retrieval was UNTIMED and single-arm (dense ON). Its "
            "recorded lat_*_ms are incidental; NO latency claim may be made from "
            "this file.",
            "These are query-set statistics. The ablation (arms A/B) is NOT RUN.",
            "IN-POOL topics are reported for contrast only and must never be "
            "quoted as production benefit (§5).",
        ],
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in
                      ("topics", "strata", "pool", "judgments")}, indent=2))
    log.info("wrote %s, %s, %s", QUERIES_FILE, QRELS_FILE, SUMMARY_FILE)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("draw", help="write the topic table (commit before pooling)")

    sp = sub.add_parser("pool", help="TREC-style pooling retrieval, 3 legs")
    sp.add_argument("--index-root", default=str(INDEX_ROOT))
    sp.add_argument("--probe-query",
                    default="coral reef bleaching thermal stress recovery")
    sp.add_argument("--splade-parity-max", type=int, default=25,
                    help="abort if bm25f∩splade@50 exceeds this — a real SEISMIC "
                         "leg overlaps ~5 (thinclient_parity_* records 5.35); "
                         "50 means SPLADE silently fell back to BM25F")
    sp.add_argument("--restart", action="store_true")

    sh = sub.add_parser("hydrate", help="backfill missing abstracts from OpenAlex")
    sh.add_argument("--batch", type=int, default=50)

    sj = sub.add_parser("judge", help="LLM-judge the pooled pairs (resumable)")
    sj.add_argument("--workers", type=int, default=6)
    sj.add_argument("--batch-size", type=int, default=12)
    sj.add_argument("--dry-run", action="store_true")
    sj.add_argument("--repair", action="store_true",
                    help="purge all-zero topics from the cache and re-judge them "
                         "(an all-zero topic is an outage signature, not a result)")

    sub.add_parser("finalize", help="stratify + emit the query set, qrels, summary")

    args = p.parse_args()
    {"draw": cmd_draw, "pool": cmd_pool, "hydrate": cmd_hydrate,
     "judge": cmd_judge, "finalize": cmd_finalize}[args.cmd](args)


if __name__ == "__main__":
    main()
