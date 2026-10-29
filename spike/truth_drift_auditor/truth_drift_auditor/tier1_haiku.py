"""Tier 1: Claude Haiku 5.5 through the Anthropic SDK — one structured verdict
per changed paragraph.

Design (docs/02_ARCHITECTURE.md): the SDK, not a headless Claude Code process,
because this call fires every few seconds and must be cheap, cacheable and
tool-less. Effort is pinned to "low" (Haiku 5.5 defaults to "medium"). The
system prompt is static and cache-controlled; the per-paragraph evidence is
not cacheable and is kept short.

Verdict semantics are kept apart on purpose: SUPPORTED, CONTRADICTED,
NO_EVIDENCE and NOT_CHECKABLE. "Not contradicted" is never promoted to
"supported" — on thin topics NO_EVIDENCE is the majority case and must stay
visible.

Structured output: ``output_config.format`` (json_schema). The installed SDK
in the thin-client venv is 0.102.0; if the keyword is unknown there the call
falls back to ``extra_body`` and finally to prompt-only JSON with a tolerant
parser. Refusals (``stop_reason == "refusal"``) return no verdicts rather than
raising — Haiku 5.5 has no server-side fallback.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .models import ClaimVerdict, Evidence, VERDICTS

SYSTEM_PROMPT = """You are an audit assistant embedded in a writing tool. The writer is drafting a document that must stay consistent with a fixed base of truth: a set of evidence passages retrieved from their reference corpus and, separately, a store of measured numbers.

For the paragraph you are given:
1. Split it into atomic factual claims. Skip opinions, plans, hedged speculation and transitions — mark those NOT_CHECKABLE only if they look like facts but cannot be checked.
2. For each claim, compare it ONLY against the evidence passages provided. Do not use outside knowledge.
3. Return one verdict per claim:
   - SUPPORTED: at least one passage states the same thing (cite its ids).
   - CONTRADICTED: at least one passage states something incompatible (cite its ids; explain the conflict in one sentence).
   - NO_EVIDENCE: no passage speaks to the claim. This is common and is not a failure.
   - NOT_CHECKABLE: not a verifiable factual claim.
4. "quote" must be copied verbatim from the paragraph (a contiguous substring) so the tool can highlight it.
5. Set escalate=true only when a CONTRADICTED verdict has confidence below 0.7, when two or more claims are CONTRADICTED, or when the paragraph as a whole seems to reframe the topic away from what the evidence describes (meaning drift). Explain briefly in escalate_reason.

Be terse. Confidence is your own 0-1 estimate."""

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "claim": {"type": "string"},
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "note": {"type": "string"},
                },
                "required": ["quote", "claim", "verdict", "evidence_ids", "confidence", "note"],
                "additionalProperties": False,
            },
        },
        "escalate": {"type": "boolean"},
        "escalate_reason": {"type": "string"},
    },
    "required": ["claims", "escalate", "escalate_reason"],
    "additionalProperties": False,
}


@dataclass
class Tier1Result:
    claims: list[ClaimVerdict]
    escalate: bool
    escalate_reason: str
    usage: dict
    refused: bool = False
    raw: str = ""


class VerdictClient(Protocol):
    def verdict(self, paragraph: str, evidence: list[Evidence], numeric_notes: list[str]) -> Tier1Result: ...


def build_user_message(paragraph: str, evidence: list[Evidence], numeric_notes: list[str]) -> str:
    ev_lines = []
    for e in evidence:
        ev_lines.append(f"[{e.id}] ({e.source}, score {e.score}) {e.text.strip()}")
    ev_block = "\n\n".join(ev_lines) if ev_lines else "(no evidence passages were retrieved for this paragraph)"
    num_block = "\n".join(f"- {n}" for n in numeric_notes) if numeric_notes else "- none"
    return (
        f"EVIDENCE PASSAGES:\n{ev_block}\n\n"
        f"DETERMINISTIC NUMERIC CHECK (already computed, for context):\n{num_block}\n\n"
        f"PARAGRAPH:\n\"\"\"\n{paragraph}\n\"\"\"\n\n"
        "Return the JSON object described in your instructions."
    )


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _locate(paragraph: str, quote: str) -> tuple[int, int] | None:
    if not quote:
        return None
    i = paragraph.find(quote)
    if i < 0:
        i = paragraph.lower().find(quote.lower())
    return (i, i + len(quote)) if i >= 0 else None


def parse_verdicts(paragraph: str, data: dict) -> list[ClaimVerdict]:
    out: list[ClaimVerdict] = []
    for c in data.get("claims", []) or []:
        verdict = str(c.get("verdict", "NO_EVIDENCE")).upper()
        if verdict not in VERDICTS:
            verdict = "NO_EVIDENCE"
        quote = str(c.get("quote", ""))
        out.append(ClaimVerdict(
            quote=quote, claim=str(c.get("claim", "")), verdict=verdict,
            evidence_ids=[str(x) for x in (c.get("evidence_ids") or [])],
            confidence=float(c.get("confidence") or 0.0), note=str(c.get("note", "")),
            span=_locate(paragraph, quote),
        ))
    return out


class HaikuVerdictClient:
    """Anthropic SDK implementation."""

    def __init__(self, model: str = "claude-haiku-5-5", max_tokens: int = 2048,
                 effort: str = "low", client=None):
        if client is None:
            import anthropic  # local import so offline tests never need the SDK
            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self._mode = "output_config"   # -> "extra_body" -> "prompt_only"

    def _create(self, messages: list[dict]):
        base = dict(
            model=self.model, max_tokens=self.max_tokens,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        )
        oc = {"effort": self.effort, "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}}
        if self._mode == "output_config":
            try:
                return self.client.messages.create(**base, output_config=oc)
            except TypeError:
                self._mode = "extra_body"
        if self._mode == "extra_body":
            try:
                return self.client.messages.create(**base, extra_body={"output_config": oc})
            except Exception as e:  # unknown-param 400 on an old API path
                if "output_config" not in str(e):
                    raise
                self._mode = "prompt_only"
        return self.client.messages.create(**base, extra_body={"output_config": {"effort": self.effort}})

    def verdict(self, paragraph: str, evidence: list[Evidence], numeric_notes: list[str]) -> Tier1Result:
        user = build_user_message(paragraph, evidence, numeric_notes)
        if self._mode == "prompt_only":
            user += "\n\nRespond with ONLY a JSON object: {\"claims\": [...], \"escalate\": bool, \"escalate_reason\": str}."
        resp = self._create([{"role": "user", "content": user}])
        usage = {}
        u = getattr(resp, "usage", None)
        if u is not None:
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                usage[k] = getattr(u, k, None)
        if getattr(resp, "stop_reason", None) == "refusal":
            return Tier1Result([], False, "", usage, refused=True)
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        try:
            data = _extract_json(text)
        except json.JSONDecodeError:
            return Tier1Result([], True, "tier1 returned unparseable output", usage, raw=text)
        return Tier1Result(
            claims=parse_verdicts(paragraph, data),
            escalate=bool(data.get("escalate", False)),
            escalate_reason=str(data.get("escalate_reason", "")),
            usage=usage, raw=text,
        )


class FakeVerdictClient:
    """Offline stand-in used by the tests and the demo: a claim is CONTRADICTED
    when a numeric note reports a mismatch, SUPPORTED when any evidence shares
    three content words with the paragraph, else NO_EVIDENCE."""

    def verdict(self, paragraph: str, evidence: list[Evidence], numeric_notes: list[str]) -> Tier1Result:
        words = {w.lower().strip(".,;:()") for w in paragraph.split() if len(w) > 4}
        mismatch = any("MISMATCH" in n for n in numeric_notes)
        best, best_overlap = None, 0
        for e in evidence:
            ew = {w.lower().strip(".,;:()") for w in e.text.split() if len(w) > 4}
            ov = len(words & ew)
            if ov > best_overlap:
                best, best_overlap = e, ov
        if mismatch:
            v, ids, conf = "CONTRADICTED", [best.id] if best else [], 0.9
        elif best is not None and best_overlap >= 3:
            v, ids, conf = "SUPPORTED", [best.id], 0.8
        else:
            v, ids, conf = "NO_EVIDENCE", [], 0.5
        sentence = paragraph.split(". ")[0]
        claim = ClaimVerdict(quote=sentence, claim=sentence, verdict=v, evidence_ids=ids,
                             confidence=conf, note="fake client", span=_locate(paragraph, sentence))
        return Tier1Result([claim], escalate=(v == "CONTRADICTED" and conf < 0.7),
                           escalate_reason="", usage={"fake": True})
