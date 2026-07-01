# Provenance Guard

An AI authorship detection API for creative writing platforms. Creators submit text; the system returns a transparency label, confidence score, and appeal path. Built to be honest about uncertainty — a false positive (wrongly accusing a human) is treated as worse than a false negative.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Add your Groq API key to .env
echo "GROQ_API_KEY=your_key_here" > .env

# Start the server
PORT=5001 python app.py
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/submit` | Submit text for attribution analysis |
| `POST` | `/appeal` | Contest a classification decision |
| `GET` | `/status/<id>` | Get current verdict and appeal status |
| `GET` | `/log` | Retrieve structured audit log entries |

---

## Detection Signals

### Signal 1 — LLM Holistic Classifier (Groq `llama-3.3-70b-versatile`)

**What it measures:** Semantic and stylistic coherence — whether the text, read as a whole, reads as human-authored. The model attends to things like: does the metaphor feel chosen or generic? Does the voice have idiosyncrasy? Is the word choice surprising in a human way, or smooth and defensible in an AI way?

**Why it differs between human and AI writing:** Human writers make local decisions under constraints — a specific emotional state, a personal vocabulary, habits and tics. AI models generate text by predicting what text *should* look like, which produces writing that is coherent and competent but tends toward the center of the distribution. This shows up as a kind of smoothness — every transition is sensible, nothing is jarring.

**What it misses:** Skilled human writers who have internalized genre conventions — clean transitions, precise vocabulary, consistent voice — can be flagged as AI. The model is also biased toward dominant linguistic norms; non-native English writing that follows L1 syntax patterns may register as anomalous even when authentically human. AI prompted to write "messily" can sometimes fool this signal entirely.

**Output:** Float 0.0–1.0. `0.0` = confident human, `1.0` = confident AI. Weighted at **65%** in the combined score.

---

### Signal 2 — Stylometric Heuristics (pure Python)

**What it measures:** Statistical regularity in the surface structure of text across four sub-metrics:

| Metric | What it captures | Direction |
|--------|-----------------|-----------|
| Sentence length variance | Std dev of sentence lengths in words | Low variance → AI-like |
| Type-token ratio (TTR) | Unique words ÷ total words | High TTR → human-like |
| Punctuation density | Punctuation marks per word | Low density → AI-like |
| Average word length | Mean characters per word | Longer words → AI-like |

Each sub-metric is normalized to [0, 1] and averaged equally. TTR is excluded below 50 words (too noisy); the entire stylometric score is nulled below 20 words.

**Why it differs between human and AI writing:** AI models are optimized partly on fluency metrics that implicitly reward regularity. Human writers have unconscious habits — they repeat constructions, make punctuation errors, vary sentence length in ways driven by what they can think of in the moment rather than what would be optimal.

**What it misses:** Breaks down on short texts (a haiku is unclassifiable). Fails on intentionally constrained genres — a legal memo or academic abstract may score AI-like simply because the genre demands regularity. AI prompted to imitate casual style can produce high-variance scores that look human.

**Output:** Float 0.0–1.0. `0.0` = human-like profile, `1.0` = AI-like profile. Weighted at **35%** in the combined score.

---

## Confidence Scoring

### Combination Formula

```
combined_score = (llm_score × 0.65) + (stylometric_score × 0.35)
```

The LLM signal gets more weight because it captures semantic properties the heuristics cannot — vocabulary choice, tonal consistency, whether a metaphor feels genuinely chosen.

### Disagreement Penalty

If the two signals diverge by more than 0.35:

```
combined_score = combined_score × 0.85 + 0.5 × 0.15
```

This pulls the score toward 0.5 (genuine uncertainty) rather than letting the weighted average paper over a real disagreement between signals.

### Fallback Cases

| Condition | Behavior |
|-----------|----------|
| Both signals present | Full weighted formula |
| Only LLM available | `combined_score = llm_score`, capped at 0.65 |
| Only stylometric available | `combined_score = stylometric_score`, capped at 0.60 |
| Neither available | `combined_score = 0.5`, verdict forced to `uncertain` |

### Verdict Thresholds

| Score range | Verdict | Label variant |
|-------------|---------|---------------|
| 0.00 – 0.28 | `human` | High-confidence human |
| 0.29 – 0.42 | `human` | Lean-human (cautious label) |
| 0.43 – 0.72 | `uncertain` | Uncertain |
| 0.73 – 0.87 | `ai` | Lean-AI (cautious label) |
| 0.88 – 1.00 | `ai` | High-confidence AI |

The human band (0.00–0.42) is wider than the AI band (0.73–1.00) by design. The system needs a score of 0.88 to use confident AI language, but only 0.28 to use confident human language. This asymmetry reflects the core design principle: **a false positive is worse than a false negative on a creative platform.**

### Validation: Two Example Submissions

**High-confidence human** — casual ramen review, colloquial tone, high sentence variance:
```json
{
  "content": "ok so i finally tried that new ramen place downtown and honestly? underwhelming...",
  "llm_score": 0.2,
  "stylometric_score": 0.3507,
  "confidence": 0.2527,
  "verdict": "human"
}
```

**Higher-confidence AI** — formal AI-style paragraph, uniform structure, low variance:
```json
{
  "content": "Artificial intelligence represents a transformative paradigm shift...",
  "llm_score": 0.8,
  "stylometric_score": 0.6009,
  "confidence": 0.7303,
  "verdict": "ai"
}
```

The spread (0.25 vs 0.73) shows the scoring produces meaningful variation across clearly different inputs.

---

## Transparency Labels

All label text is returned verbatim in the `label` field of the `/submit` response. Labels are written for readers — not creators, not engineers.

### Variant A — High-Confidence Human (`score ≤ 0.28`)
```
✓ This content appears to be human-authored.

Our analysis found no strong indicators of AI generation. This label reflects our best assessment — not a guarantee.
```

### Variant B — Lean-Human / Uncertain (`score 0.29–0.42`)
```
~ Authorship unclear — likely human.

Our analysis found more human-like patterns than AI-like ones, but the evidence isn't strong enough for a confident assessment. Some human writing styles can resemble AI output. If you're the creator and believe this label is wrong, you can submit an appeal.
```

### Variant C — Uncertain / Inconclusive (`score 0.43–0.72`)
```
~ Authorship unclear.

Our analysis couldn't confidently determine whether this content was written by a human or generated by AI. This does not mean the content is AI-generated — it means our system is uncertain. If you're the creator and believe this label is inaccurate, you can submit an appeal.
```

### Variant D — Lean-AI / Uncertain (`score 0.73–0.87`)
```
~ Authorship unclear — some AI-like patterns detected.

Our analysis found patterns that appear more often in AI-generated content than in human writing, but we're not confident enough to make a definitive call. Some human writing — especially formal, polished, or conventionally structured work — can resemble AI output. If this is your original work, you can submit an appeal.
```

### Variant E — High-Confidence AI (`score ≥ 0.88`)
```
⚠ This content shows strong indicators of AI generation.

Our analysis found consistent patterns across multiple signals that are characteristic of AI-generated text. This label reflects our best assessment — it is not a guaranteed determination. If you believe this is incorrect, you can submit an appeal.
```

**Design notes:** No variant uses the word "detected" (implies certainty the system doesn't have). No variant says "AI-generated content" as a flat statement below 0.88. Every variant except A surfaces the appeal path.

---

## Appeals Workflow

Creators who dispute their classification submit to `POST /appeal` with their `submission_id` and written reasoning. The system:

1. Validates the submission exists (404 if not)
2. Rejects duplicate appeals for the same submission (409)
3. Writes a new audit log entry of type `appeal`
4. Flips the submission's status from `classified` → `under_review`
5. Returns a confirmation with `appeal_id` and human-readable message

No automatic re-classification occurs. A human moderator reviews via `GET /log`, which surfaces both the system's reasoning (signal scores, confidence, LLM reasoning text) and the creator's explanation together.

### Example Appeal Request
```bash
curl -s -X POST http://localhost:5001/appeal \
  -H "Content-Type: application/json" \
  -d '{
    "submission_id": "565b7fdb-cffd-423f-b1e5-a4c2f16bcca7",
    "creator_id": "test-user-1",
    "reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."
  }' | python -m json.tool
```

### Example Appeal Response
```json
{
  "appeal_id": "ce54803b-bbf7-47cd-af16-4ea63ee468c3",
  "message": "Your appeal has been received and logged. A human moderator will review the original decision alongside your explanation.",
  "status": "under_review",
  "submission_id": "565b7fdb-cffd-423f-b1e5-a4c2f16bcca7",
  "timestamp": "2026-06-30T15:02:26.159300+00:00"
}
```

---

## Rate Limiting

Applied to `POST /submit`:

```
10 requests per minute
100 requests per day
```

**Reasoning:** A writer submitting their own work — even a prolific one — is unlikely to exceed 10 submissions in a minute. That's faster than a human can read a response and decide to submit another piece. 100/day is generous for legitimate use while making bulk automated scraping expensive. Anything over 10/minute is almost certainly a script, not a person.

When the limit is hit, the API returns `429 Too Many Requests`. The text never enters the pipeline.

### Rate Limit Test Evidence

Sending 12 rapid requests — 2 more than the per-minute limit:

```
200
200
200
200
200
200
200
200
200
200
429
429
```

---

## Audit Log

Every submission writes a structured entry to SQLite. `GET /log` returns entries as JSON, joined with any appeal.

### Sample Entry (with appeal)
```json
{
  "submission_id": "565b7fdb-cffd-423f-b1e5-a4c2f16bcca7",
  "creator_id": "test-user-1",
  "timestamp": "2026-06-30T13:24:39.845361+00:00",
  "verdict": "human",
  "confidence": 0.2527,
  "llm_score": 0.2,
  "stylometric_score": 0.3507,
  "llm_reasoning": "The text's use of colloquial expressions, personal opinions, and casual tone suggest a high likelihood of human authorship.",
  "label": "✓ This content appears to be human-authored.",
  "status": "under_review",
  "short_text_warning": false,
  "appeal": {
    "appeal_id": "ce54803b-bbf7-47cd-af16-4ea63ee468c3",
    "creator_id": "test-user-1",
    "reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
    "timestamp": "2026-06-30T15:02:26.159300+00:00"
  }
}
```

---

## Known Limitations

### Formal or genre-constrained human writing will score as AI-like

During Milestone 4 testing, a passage about monetary policy and central bank interest rate decisions scored `confidence: 0.7663` with `verdict: ai` — despite being a plausible piece of human academic writing.

This happens because both signals measure *regularity*, not *intentionality*. The stylometric analyzer found low punctuation density (0.0465) and long average word length (5.93 characters) — both AI-like by the normalization formulas. The LLM classifier scored it 0.8 because formal academic prose lacks the idiosyncrasy it associates with human writing.

The system cannot distinguish intentional formalism from AI generation using text-only signals. A sonnet, a legal brief, and a structured how-to guide will all face this problem. The wide uncertain band (0.43–0.87) and the appeal path mitigate this — the system won't accuse a formally trained poet with high confidence — but it cannot fix the underlying blind spot without additional context (draft history, user track record, metadata).

### Very short texts are unreliable

Texts under 50 words produce meaningless TTR (a single repeated word changes the ratio dramatically) and sentence length variance computed from 2–3 data points. The system flags these with `short_text_warning: true` and nulls the stylometric score below 20 words, but the honest answer for an 8-word haiku is "we don't know." The system says that — but it can't do better without more text.

---

## Spec Reflection

### Where the spec helped

The disagreement penalty was the clearest example of the spec doing real design work before a line of code was written. Without it, the weighted average would paper over genuine signal disagreement — an LLM score of 0.85 and a stylometric score of 0.40 would combine to ~0.69 (`uncertain`), which *looks* reasonable but is actually masking the fact that two independent signals are pointing in opposite directions. The spec's decision to pull combined scores toward 0.5 in that case forced the system to be honest about what it didn't know, not just average away the uncertainty.

### Where implementation diverged

The spec calls for `creator_id` validation on appeals — only the creator who submitted the content should be able to appeal it. In practice this creates a friction problem: anonymous submissions (no `creator_id` at submit time) can't be appealed by anyone under strict validation. The implementation accepts any `creator_id` on appeals for anonymous submissions and flags them for human moderator judgment rather than blocking them outright. This is a deliberate divergence — the appeal path should be as frictionless as possible for creators who are systematically disadvantaged by the classifier (non-native speakers, formal writers), and blocking anonymous appeals to maintain strict identity validation gets the priorities backwards on a creative platform.

---

## AI Usage

### Instance 1 — Generating the Flask skeleton and Signal 1 function (Milestone 3)

**What I directed:** Provided the architecture diagram, the Signal 1 spec section (prompt design contract, output format, failure mode handling), and the `POST /submit` API contract. Asked for: a Flask app skeleton with the submit route stubbed, a `classify_with_llm()` function implementing the exact prompt contract, and placeholder stubs for the other pipeline components.

**What it produced:** A working Flask app with `classify_with_llm()` correctly calling Groq, parsing the JSON response, and returning `{"llm_score": None, "reasoning": None}` on any failure. The function signature and return shape matched the spec exactly.

**What I revised:** The generated code called `init_db()` only inside `if __name__ == "__main__"`, which caused a `sqlite3.OperationalError: no such table` when using Flask's test client (which bypasses that block). I moved `init_db()` to run inside `with app.app_context()` at module level so it always executes on import, regardless of how the app is loaded.

### Instance 2 — Generating the stylometric analyzer (Milestone 4)

**What I directed:** Provided the Signal 2 spec section with all four sub-metric normalization formulas, the short-text handling rules (TTR excluded below 50 words, entire score nulled below 20 words), and the exact variable names from the spec table.

**What it produced:** A `analyze_stylometrics()` function that computed all four sub-metrics with the correct normalization and returned the right output shape, including the `short_text_warning` flag.

**What I revised:** The generated sentence splitter used `re.split(r'[.!?]+', text)` which incorrectly split on decimal numbers and abbreviations (e.g. "U.S." became three fragments). I replaced it with a lookbehind-based splitter — `re.split(r'(?<=[.!?])\s+', text.strip())` — that only splits on punctuation followed by whitespace, which is more robust for the kinds of prose the system will see.

---

## Project Structure

```
provenance-guard/
├── app.py            # Flask app — all routes and pipeline orchestration
├── signals.py        # Signal 1: LLM classifier via Groq
├── stylometrics.py   # Signal 2: stylometric heuristics (pure Python)
├── audit.py          # SQLite audit logger
├── requirements.txt  # Dependencies
├── planning.md       # Architecture spec and design decisions
├── .env              # GROQ_API_KEY (not committed)
└── .gitignore
```

## Dependencies

```
flask
flask-limiter
groq
python-dotenv
```