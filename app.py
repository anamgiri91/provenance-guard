"""
Provenance Guard — Flask app (Milestone 3)

Implemented:
  POST /submit   — full pipeline with Signal 1 (LLM) live; Signal 2 stubbed
  GET  /log      — returns structured audit log entries

Stubbed (filled in M4/M5):
  analyze_stylometrics()
  compute_confidence()
  generate_label()
  POST /appeal
  GET  /status/<id>
"""

import hashlib
import os
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit import get_log, init_db, insert_submission
from signals import classify_with_llm

app = Flask(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],  # only apply limits where decorated
)

# ---------------------------------------------------------------------------
# Stubs — replaced in M4 / M5
# ---------------------------------------------------------------------------

def analyze_stylometrics(text: str) -> dict:
    """M4 stub — returns None score so confidence engine uses LLM-only fallback."""
    return {
        "stylometric_score": None,
        "detail": {},
        "short_text_warning": False,
    }


def compute_confidence(llm_score, stylometric_score) -> dict:
    """
    M3 implementation: LLM-only fallback (spec §1 fallback table).
    Full weighted formula added in M4.
    """
    if llm_score is None and stylometric_score is None:
        return {"combined_score": 0.5, "verdict": "uncertain", "disagreement_flagged": False}

    if llm_score is not None and stylometric_score is None:
        # Only LLM available — cap at 0.65 per spec
        score = min(llm_score, 0.65)
        verdict = _score_to_verdict(score)
        return {"combined_score": round(score, 4), "verdict": verdict, "disagreement_flagged": False}

    # Full formula — used once M4 fills in stylometric_score
    combined = llm_score * 0.65 + stylometric_score * 0.35
    disagreement = abs(llm_score - stylometric_score) > 0.35
    if disagreement:
        combined = combined * 0.85 + 0.5 * 0.15
    verdict = _score_to_verdict(combined)
    return {
        "combined_score": round(combined, 4),
        "verdict": verdict,
        "disagreement_flagged": disagreement,
    }


def _score_to_verdict(score: float) -> str:
    """Spec threshold table."""
    if score <= 0.42:
        return "human"
    if score <= 0.72:
        return "uncertain"
    return "ai"


def generate_label(combined_score: float, verdict: str) -> str:
    """M3 stub — placeholder strings; verbatim spec labels added in M5."""
    if combined_score <= 0.28:
        return "✓ This content appears to be human-authored."
    if combined_score <= 0.42:
        return "~ Authorship unclear — likely human. (placeholder)"
    if combined_score <= 0.72:
        return "~ Authorship unclear. (placeholder)"
    if combined_score <= 0.87:
        return "~ Authorship unclear — some AI-like patterns detected. (placeholder)"
    return "⚠ This content shows strong indicators of AI generation. (placeholder)"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/submit")
@limiter.limit("30 per minute")
def submit():
    body = request.get_json(silent=True)
    if not body or not body.get("content"):
        return jsonify({"error": "Request body must include a non-empty 'content' field."}), 400

    raw_text = body["content"].strip()
    if not raw_text:
        return jsonify({"error": "'content' must not be blank."}), 400

    creator_id = body.get("creator_id", "")
    submission_id = str(uuid.uuid4())
    text_hash = hashlib.sha256(raw_text.encode()).hexdigest()

    # --- Signal 1: LLM classifier ---
    llm_result = classify_with_llm(raw_text)
    llm_score = llm_result["llm_score"]
    llm_reasoning = llm_result["reasoning"]

    # --- Signal 2: Stylometrics (stubbed in M3) ---
    stylo_result = analyze_stylometrics(raw_text)
    stylometric_score = stylo_result["stylometric_score"]
    short_text_warning = stylo_result["short_text_warning"]

    # --- Confidence engine ---
    confidence_result = compute_confidence(llm_score, stylometric_score)
    combined_score = confidence_result["combined_score"]
    verdict = confidence_result["verdict"]

    # --- Label ---
    label = generate_label(combined_score, verdict)

    # --- Audit log ---
    ts = insert_submission(
        submission_id=submission_id,
        creator_id=creator_id,
        text_hash=text_hash,
        verdict=verdict,
        confidence=combined_score,
        llm_score=llm_score,
        stylometric_score=stylometric_score,
        llm_reasoning=llm_reasoning,
        label=label,
        short_text_warning=short_text_warning,
    )

    return jsonify({
        "submission_id": submission_id,
        "verdict": verdict,
        "confidence": combined_score,
        "label": label,
        "signals": {
            "llm_score": llm_score,
            "llm_reasoning": llm_reasoning,
            "stylometric_score": stylometric_score,
            "stylometric_detail": stylo_result["detail"],
        },
        "short_text_warning": short_text_warning,
        "status": "classified",
        "timestamp": ts,
    })


@app.get("/log")
def log():
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    verdict_filter = request.args.get("verdict")
    entries = get_log(limit=limit, offset=offset, verdict_filter=verdict_filter)
    return jsonify({"count": len(entries), "entries": entries})


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"[provenance-guard] Starting on http://localhost:{port}")
    app.run(debug=True, port=port)