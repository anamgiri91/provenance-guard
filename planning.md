# Provenance Guard — Project Planning

## Table of Contents
1. [Architecture Narrative](#architecture-narrative)
2. [Detection Signals](#detection-signals)
3. [The False Positive Problem](#the-false-positive-problem)
4. [API Surface](#api-surface)
5. [Architecture Diagram](#architecture-diagram)

---

## Architecture Narrative

A creator pastes their poem or short story excerpt into the platform and hits "submit." Here is every system component that text touches, in order, and what each one does.

### 1. Rate Limiter
Before anything else, the submission endpoint checks whether this client (identified by IP address) has exceeded the allowed number of requests in the current window. If they have, the request is rejected immediately with a `429 Too Many Requests` error. The text never enters the pipeline. This protects the system from flooding — both accidental (a buggy client retrying) and intentional (an adversary trying to game classifications at scale).

### 2. Submission Endpoint (`POST /submit`)
Flask receives the request, validates that it contains text, and assigns the submission a unique ID. This ID will follow the content through every subsequent component and appear in every log entry. The endpoint is the contract boundary: everything outside it is the platform's problem, everything inside it is ours.

### 3. Signal 1 — LLM Classifier (Groq)
The raw text is sent to `llama-3.3-70b-versatile` with a carefully constructed prompt asking it to assess whether the writing reads as human-authored or AI-generated, and to return a structured score. This signal captures *semantic and stylistic coherence* — things like whether the text has the kind of idiosyncratic phrasing, unexpected word choices, tonal inconsistency, or emotional specificity that characterizes human writing versus the smooth, well-organized, slightly generic quality of most AI output. The LLM returns a probability-like score (0.0 = almost certainly human, 1.0 = almost certainly AI) along with brief reasoning.

### 4. Signal 2 — Stylometric Analyzer (pure Python)
The same raw text is passed through a statistical analysis module that computes measurable structural properties: sentence length variance, type-token ratio (vocabulary diversity), punctuation density, and average word length. This signal captures *statistical regularity* — AI writing tends to be more uniform across all these dimensions; human writing is messier, more variable, and less consistent. This module returns its own score (0.0–1.0) along with the raw computed metrics.

### 5. Confidence Scoring Engine
Both signal scores are combined into a single confidence score and a final attribution verdict. This is not just an average — the combination logic handles disagreement between signals thoughtfully. If one signal says AI and the other says human, the output reflects genuine uncertainty rather than splitting the difference blindly. The engine outputs: a verdict (`human`, `ai`, or `uncertain`), a confidence score (0.0–1.0), and both underlying signal scores for transparency.

### 6. Transparency Label Generator
The verdict and confidence score are translated into the plain-English label a reader will actually see. This component maps numerical confidence onto language a non-technical person can understand. It produces one of three label variants, with the exact wording determined by where the confidence score falls.

### 7. Audit Logger
Every attribution decision — submission ID, timestamp, raw text hash (not the text itself, for privacy), both signal scores, combined confidence, verdict, and label — is written to a structured log (SQLite). This record is immutable: it captures what the system decided, when, and why, so that any future appeal has ground truth to compare against.

### 8. Response
The submission endpoint returns a structured JSON response containing the submission ID, verdict, confidence score, transparency label text, and the individual signal scores. The platform uses this response to display the label to readers.

### Appeal Flow
When a creator disputes their classification, they submit to `POST /appeal` with their submission ID and written reasoning. The appeal endpoint looks up the original audit log entry, appends the appeal (timestamp, creator's reasoning, original decision) as a new log entry, and updates the content's status from `classified` to `under_review`. The system does not automatically re-classify — a human moderator reviews. The response confirms the appeal was received and logged.

---

## Detection Signals

### Signal 1: LLM-Based Holistic Classification

**What property it measures:**
Semantic and stylistic coherence — whether the text, read as a whole, has the qualities of human-authored writing. The LLM attends to things like: does the metaphor feel chosen or generic? Does the voice have idiosyncrasy? Is the emotional register consistent with the subject in an *interesting* rather than *expected* way? Does anything surprise?

**Why this property differs between human and AI writing:**
Human writers make local decisions under constraints — they're writing from a specific emotional state, with a specific vocabulary, with habits and tics and preferences. AI models generate text by predicting what text *should* look like, which produces writing that is coherent and competent but tends to lack genuine surprise. The model has seen so much writing that it gravitates toward the center of the distribution. This shows up as a kind of smoothness — every transition is sensible, every word choice is defensible, nothing is jarring or strange in the way human writing often is.

**Blind spots:**
This signal is most dangerous when humans write *well* and conventionally. A skilled writer who has internalized the conventions of their genre — clear transitions, precise vocabulary, consistent voice — can produce text that a holistic classifier will flag as AI. Conversely, AI prompted to write "messily" or "like a human" can sometimes fool this signal. The LLM classifier also inherits whatever biases the underlying model has about what "human writing" looks like — it may be systematically biased against certain cultural styles, dialects, or non-Western rhetorical traditions that it has less training data for.

---

### Signal 2: Stylometric Heuristics

**What property it measures:**
Statistical regularity in the surface structure of the text. Specifically:

| Metric | What it captures |
|---|---|
| **Sentence length variance** | Standard deviation of sentence lengths in words. Low variance = suspiciously uniform. |
| **Type-token ratio (TTR)** | Unique words ÷ total words. Measures vocabulary diversity. |
| **Punctuation density** | Punctuation marks per word. AI text tends to use punctuation correctly and consistently. |
| **Average word length** | AI tends toward slightly longer, more formal words on average. |

**Why this property differs between human and AI writing:**
AI models are optimized partly on fluency and coherence metrics that implicitly reward regularity. Human writers have unconscious habits — they fall into rhythms, repeat constructions, make punctuation errors, use short punchy sentences and then suddenly one very long one for effect, and vary word choice in ways that are driven by what they can think of in the moment rather than what would be optimal. This creates statistical signatures. AI writing is more like sampling from a very smooth distribution; human writing is noisier.

**Blind spots:**
This signal breaks down badly on short texts. With fewer than ~200 words, the statistical measures are too noisy to be meaningful — a three-sentence poem is going to produce meaningless TTR and sentence length variance regardless of authorship. It also fails on texts that are intentionally stylistically constrained: a formal legal memo or a tightly structured academic abstract might score as "AI-like" simply because the genre demands regularity. Conversely, AI prompted to imitate a casual or experimental style can produce high variance scores that look human. This signal measures surface statistics, not intent.

---

## The False Positive Problem

### The Scenario
A poet submits a carefully crafted, formally structured sonnet. Her style is precise and controlled — consistent meter, clean diction, no punctuation irregularities. She has written this way for twenty years.

- The LLM classifier finds the writing too smooth and competent → scores **0.72** (AI-leaning)
- The stylometric analyzer finds low sentence length variance and clean punctuation → scores **0.68** (AI-leaning)
- Combined confidence: **0.70** that this is AI-generated

### What the Confidence Score Does
0.70 is not 0.95. The system must not speak with the same conviction it would at 0.92. The confidence score gates label language directly — a 0.70 produces noticeably more hedged language than a 0.90. This is a deliberate design choice, not a fallback.

### What the Label Says
At 0.70 confidence, the system does **not** say "This content was generated by AI." It says something closer to:

> *"Our analysis suggests this content may have been AI-assisted. We're not certain — some human writing shares these characteristics. If this is your original work, you can submit an appeal below."*

The label names the uncertainty and surfaces the appeal path in the same breath.

### The Asymmetry Principle
A false positive (labeling a human's work as AI-generated) is worse than a false negative on a creative platform. This asymmetry is baked into the confidence thresholds:

- The "uncertain" band is **wide**: roughly **0.35–0.72**
- The bar for calling something AI is higher than the bar for calling it human
- At any score below 0.72, the label defaults to cautious language regardless of the nominal verdict

### The Appeal Flow for This Creator
She sees the label, disagrees, and submits an appeal via `POST /appeal`. She writes: *"I have written formal sonnets for twenty years. My MFA thesis is in formalist poetry. This is my work."*

The system:
1. Logs her appeal alongside the original audit entry
2. Flips content status from `classified` → `under_review`
3. Returns a confirmation with her appeal ID

A human moderator can now see both the system's reasoning (signal scores, confidence of 0.70) and her explanation, and make a judgment. The system never claimed certainty — the label already acknowledged it wasn't sure — so the appeal path is clearly appropriate and the workflow is there to receive it.

### Design Implications from This Scenario
- Wide "uncertain" band (0.35–0.72) rather than a narrow one
- Label language that is explicitly non-accusatory even at high confidence
- The appeal path must be visible and frictionless inside the label itself — not buried in settings
- Confidence thresholds are asymmetric: lean toward human when uncertain

---

## API Surface

### `POST /submit`

**Purpose:** Accept a piece of text for attribution analysis.

**Rate limited:** Yes

**Request body:**
```json
{
  "content": "string (required) — the text to be analyzed",
  "creator_id": "string (optional) — platform user identifier"
}
```

**Response:**
```json
{
  "submission_id": "string — unique ID for this submission",
  "verdict": "human | ai | uncertain",
  "confidence": 0.0,
  "label": "string — the exact transparency label text shown to readers",
  "signals": {
    "llm_score": 0.0,
    "stylometric_score": 0.0,
    "stylometric_detail": {
      "sentence_variance": 0.0,
      "ttr": 0.0,
      "punct_density": 0.0,
      "avg_word_length": 0.0
    }
  },
  "status": "classified",
  "timestamp": "ISO 8601"
}
```

---

### `POST /appeal`

**Purpose:** Allow a creator to contest a classification.

**Request body:**
```json
{
  "submission_id": "string (required)",
  "creator_id": "string (required)",
  "reasoning": "string (required) — creator's explanation"
}
```

**Response:**
```json
{
  "appeal_id": "string",
  "submission_id": "string",
  "status": "under_review",
  "message": "string — confirmation to display to creator",
  "timestamp": "ISO 8601"
}
```

---

### `GET /status/<submission_id>`

**Purpose:** Retrieve the current classification and status for a submission.

**Response:**
```json
{
  "submission_id": "string",
  "verdict": "human | ai | uncertain",
  "confidence": 0.0,
  "label": "string",
  "status": "classified | under_review | reviewed",
  "appeal": {}
}
```

---

### `GET /log`

**Purpose:** Retrieve structured audit log entries for review or grading.

**Query params:** `limit`, `offset`, `verdict`

**Response:** Array of audit log entries. Each entry contains:
```json
{
  "submission_id": "string",
  "timestamp": "ISO 8601",
  "verdict": "human | ai | uncertain",
  "confidence": 0.0,
  "llm_score": 0.0,
  "stylometric_score": 0.0,
  "label": "string",
  "appeal": {}
}
```

---

## Architecture

### Submission Flow

```
SUBMISSION FLOW
══════════════════════════════════════════════════════════════════

Client
  │
  │  POST /submit  {content, creator_id}
  ▼
┌─────────────────┐
│   Rate Limiter  │──── 429 Too Many Requests ──────────────────▶ Client
└────────┬────────┘         (if limit exceeded)
         │
         │  raw text
         ▼
┌─────────────────────┐
│  Submission Handler │  assigns submission_id, validates input
└──────────┬──────────┘
           │
     raw text + id
     ┌─────┴──────┐
     │            │
     ▼            ▼
┌─────────┐  ┌──────────────────┐
│  Groq   │  │  Stylometric     │
│  LLM    │  │  Analyzer        │
│Classif. │  │  (pure Python)   │
└────┬────┘  └────────┬─────────┘
     │                │
  llm_score        stylometric_score
  (0.0–1.0)        + raw metrics
     │                │
     └────────┬────────┘
              │
              ▼
┌──────────────────────────┐
│   Confidence Scoring     │
│   Engine                 │
│                          │
│  combined_score,         │
│  verdict                 │
│  (human/ai/uncertain)    │
└────────────┬─────────────┘
             │
     verdict + confidence
             │
             ▼
┌──────────────────────────┐
│  Transparency Label      │
│  Generator               │
│                          │
│  → label text string     │
└────────────┬─────────────┘
             │
    full decision record
             │
             ▼
┌──────────────────────────┐
│      Audit Logger        │
│  (SQLite)                │
│                          │
│  writes: id, timestamp,  │
│  scores, verdict, label  │
└────────────┬─────────────┘
             │
    structured JSON response
             │
             ▼
          Client
  {submission_id, verdict, confidence,
   label, signals, status, timestamp}
```

### Appeal Flow

```
APPEAL FLOW
══════════════════════════════════════════════════════════════════

Client
  │
  │  POST /appeal  {submission_id, creator_id, reasoning}
  ▼
┌─────────────────────┐
│  Appeal Endpoint    │
│                     │
│  looks up original  │
│  audit record by    │
│  submission_id      │
└──────────┬──────────┘
           │
    original record + appeal data
           │
           ▼
┌──────────────────────────┐
│      Audit Logger        │
│                          │
│  appends appeal entry:   │
│  appeal_id, timestamp,   │
│  reasoning,              │
│  original verdict        │
│                          │
│  updates status:         │
│  classified →            │
│  under_review            │
└────────────┬─────────────┘
             │
    confirmation response
             │
             ▼
          Client
  {appeal_id, submission_id,
   status: "under_review", message,
   timestamp}
```

---

## Milestone 2 Spec

> These five sections are the implementation contract. Every design decision that affects code lives here. Vague answers here produce vague code in Milestones 3–5 — so each answer is specific enough that a function signature or threshold constant could be derived directly from it.

---

### 1. Detection Signals — Output Format & Combination Logic

#### Signal 1: LLM Classifier (Groq `llama-3.3-70b-versatile`)

**Output format:** A float between 0.0 and 1.0, where:
- `0.0` = the model is highly confident this is human-authored
- `1.0` = the model is highly confident this is AI-generated

The prompt instructs the model to return **only** a JSON object in this exact shape:

```json
{
  "ai_probability": 0.82,
  "reasoning": "one sentence explanation"
}
```

The `ai_probability` field is extracted and used directly as `llm_score`. The `reasoning` field is stored in the audit log for human reviewers but does not affect scoring.

**Prompt design contract:** The system prompt tells the model: "You are an authorship analyst. Assess whether the following text was written by a human or generated by an AI. Return only a JSON object with fields `ai_probability` (float 0.0–1.0) and `reasoning` (one sentence). Do not include any other text." The user message is the raw submitted content. Temperature is set to 0 for consistency.

**Failure mode handling:** If the Groq call fails or returns unparseable JSON, `llm_score` is set to `None` and the confidence engine falls back to stylometric-only scoring, with the confidence capped at 0.65 regardless of the stylometric result (to force an uncertain label when a signal is missing).

---

#### Signal 2: Stylometric Analyzer (pure Python)

**Output format:** A float between 0.0 and 1.0, where:
- `0.0` = highly human-like statistical profile (high variance, messy, diverse)
- `1.0` = highly AI-like statistical profile (uniform, clean, regular)

Four sub-metrics are computed, each normalized to 0.0–1.0, then combined into a single `stylometric_score` via equal-weight averaging:

| Sub-metric | Variable name | Direction | Normalization approach |
|---|---|---|---|
| Sentence length variance | `sent_variance` | Low variance → AI | Cap raw std-dev at 20; invert and normalize: `1 - min(std, 20) / 20` |
| Type-token ratio | `ttr` | High TTR → human (short texts); used only if word count ≥ 50 | Invert: `1 - ttr` clipped to [0, 1] |
| Punctuation density | `punct_density` | Low density → AI | Invert: `1 - min(density, 0.15) / 0.15` |
| Average word length | `avg_word_len` | Longer words → AI | `min((avg_len - 3.5) / 3.0, 1.0)` clipped to [0, 1] |

**Short text handling:** If the submission is fewer than 50 words, `ttr` is excluded from the average (only the remaining three sub-metrics are averaged), and a `short_text_warning: true` flag is set in the response. If fewer than 20 words, the entire stylometric score is set to `None` and treated the same as a signal failure.

**Raw metrics are always returned** in `stylometric_detail` regardless of the score, so graders and human reviewers can inspect the underlying numbers.

---

#### Combining Signals into a Confidence Score

**Base formula:** Weighted average with the LLM signal given more weight, because it captures semantic properties the heuristics cannot:

```
combined_score = (llm_score × 0.65) + (stylometric_score × 0.35)
```

**Disagreement penalty:** If the two signals disagree by more than 0.35 (i.e., `abs(llm_score - stylometric_score) > 0.35`), the combined score is pulled toward 0.5 by 15%:

```
if abs(llm_score - stylometric_score) > 0.35:
    combined_score = combined_score * 0.85 + 0.5 * 0.15
```

This reflects genuine uncertainty when the two independent signals point in opposite directions — rather than letting the weighted average paper over a real disagreement.

**Fallback cases:**

| Condition | Behavior |
|---|---|
| Both signals present | Full formula above |
| Only LLM available | `combined_score = llm_score`, capped at 0.65 |
| Only stylometric available | `combined_score = stylometric_score`, capped at 0.60 |
| Neither signal available | `combined_score = 0.5`, verdict forced to `uncertain` |

---

### 2. Uncertainty Representation — Thresholds and What Scores Mean

#### What a confidence score means in plain English

The `combined_score` represents **the system's estimated probability that this content is AI-generated.** It is not a claim of certainty — it is a probabilistic assessment based on the two signals described above.

A score of **0.50** means the two signals produced contradictory or inconclusive evidence. The system has no meaningful basis for a verdict. This is the honest floor of uncertainty.

A score of **0.62** means the signals lean AI but not convincingly — think "mildly suspicious, not alarming." At this score, the system is wrong often enough that accusing a creator would be unfair. The label must reflect this.

A score of **0.88** means both signals agree strongly. The system has seen patterns that are statistically and semantically consistent with AI generation. The label can be more direct — but still not absolute.

#### Threshold table

| Score range | Verdict | Label variant | Reasoning |
|---|---|---|---|
| 0.00 – 0.28 | `human` | High-confidence human | Both signals consistently human-like; very low false positive risk |
| 0.29 – 0.42 | `human` | Lean-human (still uncertain label) | Signals lean human but not decisively; use cautious language |
| 0.43 – 0.72 | `uncertain` | Uncertain | Wide uncertain band; false positive risk too high to make a claim |
| 0.73 – 0.87 | `ai` | Lean-AI (still uncertain label) | Signals lean AI but system acknowledges it could be wrong |
| 0.88 – 1.00 | `ai` | High-confidence AI | Both signals strongly agree; system speaks more directly |

**The asymmetry is intentional.** The human band (0.00–0.42) is wider than the AI band (0.73–1.00). The uncertain zone runs 0.29–0.87 for the cautious label variants. The system needs a score of 0.88 to use confident AI language, but only needs a score below 0.29 to use confident human language. This reflects the spec's stated principle: a false positive is worse than a false negative on a creative platform.

---

### 3. Transparency Labels — Exact Text for All Three Variants

These are the verbatim strings the system returns in the `label` field. They are not summaries — this is exactly what gets displayed to readers on the platform.

---

#### Variant A — High-Confidence Human (`combined_score ≤ 0.28`)

```
✓ This content appears to be human-authored.

Our analysis found no strong indicators of AI generation. This label reflects our best assessment — not a guarantee.
```

---

#### Variant B — Uncertain / Lean-Human (`combined_score 0.29–0.42`)

```
~ Authorship unclear — likely human.

Our analysis found more human-like patterns than AI-like ones, but the evidence isn't strong enough for a confident assessment. Some human writing styles can resemble AI output. If you're the creator and believe this label is wrong, you can submit an appeal.
```

---

#### Variant C — Uncertain / Inconclusive (`combined_score 0.43–0.72`)

```
~ Authorship unclear.

Our analysis couldn't confidently determine whether this content was written by a human or generated by AI. This does not mean the content is AI-generated — it means our system is uncertain. If you're the creator and believe this label is inaccurate, you can submit an appeal.
```

---

#### Variant D — Uncertain / Lean-AI (`combined_score 0.73–0.87`)

```
~ Authorship unclear — some AI-like patterns detected.

Our analysis found patterns that appear more often in AI-generated content than in human writing, but we're not confident enough to make a definitive call. Some human writing — especially formal, polished, or conventionally structured work — can resemble AI output. If this is your original work, you can submit an appeal.
```

---

#### Variant E — High-Confidence AI (`combined_score ≥ 0.88`)

```
⚠ This content shows strong indicators of AI generation.

Our analysis found consistent patterns across multiple signals that are characteristic of AI-generated text. This label reflects our best assessment — it is not a guaranteed determination. If you believe this is incorrect, you can submit an appeal.
```

---

**Design notes on label language:**
- No variant uses the word "detected" (implies certainty the system doesn't have)
- No variant says "AI-generated content" as a flat statement below 0.88
- Every variant except Variant A surfaces the appeal path
- Variant E still includes "not a guaranteed determination" — even at high confidence, the system doesn't claim to be infallible
- Labels are written for the *reader*, not the creator — they must make sense to someone who didn't submit the content

---

### 4. Appeals Workflow — Complete Specification

#### Who can submit an appeal
Any creator who submitted the content — identified by `creator_id` in the original submission. The appeal endpoint requires a `creator_id` that matches the one on the original submission record. If no `creator_id` was provided at submission time, any `creator_id` is accepted (anonymous submissions can be appealed by anyone claiming authorship — the system logs it and leaves adjudication to a human moderator).

One appeal per submission. If an appeal already exists for a `submission_id`, the endpoint returns a `409 Conflict` with the existing appeal's details.

#### What information an appeal captures

| Field | Required | Description |
|---|---|---|
| `submission_id` | Yes | Links appeal to the original classification |
| `creator_id` | Yes | Who is appealing |
| `reasoning` | Yes | Creator's explanation, free text, 10–2000 characters |
| `appeal_id` | Auto-generated | UUID assigned by the system |
| `timestamp` | Auto-generated | ISO 8601, UTC |

#### What the system does when an appeal is received

1. **Validates** that `submission_id` exists in the audit log. Returns `404` if not found.
2. **Validates** that no prior appeal exists for this `submission_id`. Returns `409` if one does.
3. **Writes** a new audit log entry of type `appeal`, containing: `appeal_id`, `submission_id`, `creator_id`, `reasoning`, `timestamp`, and a copy of the original verdict and confidence score at time of appeal.
4. **Updates** the original submission's status field from `classified` → `under_review`. This update is reflected in `GET /status/<submission_id>`.
5. **Returns** a confirmation response with `appeal_id`, `submission_id`, `status: "under_review"`, a human-readable `message`, and `timestamp`.

The system does **not** trigger automatic re-classification. It does not modify the original verdict or confidence score. Those fields are immutable once written.

#### What a human reviewer sees in the appeal queue

When a moderator calls `GET /log?status=under_review`, each entry exposes:

```json
{
  "submission_id": "...",
  "timestamp": "...",
  "verdict": "ai",
  "confidence": 0.81,
  "llm_score": 0.79,
  "stylometric_score": 0.85,
  "llm_reasoning": "The text uses consistently polished transitions and lacks idiosyncratic phrasing.",
  "label": "~ Authorship unclear — some AI-like patterns detected. ...",
  "status": "under_review",
  "appeal": {
    "appeal_id": "...",
    "creator_id": "...",
    "reasoning": "I wrote this for my MFA thesis. I can provide a draft history.",
    "timestamp": "..."
  }
}
```

The reviewer sees: what the system decided, how confident it was, what each signal contributed, what reasoning the LLM gave, and what the creator says in their defense. No information relevant to overturning or upholding the decision is hidden.

---

### 5. Anticipated Edge Cases

These are not generic risks. They are specific content types that will interact badly with specific parts of the pipeline, and they inform how the thresholds and labels are designed.

#### Edge Case 1: Formal or genre-constrained human writing

**Scenario:** A creator submits a Petrarchan sonnet, a legal brief written in plain English, or a structured how-to guide. All three are human-authored but share surface properties with AI output: low sentence length variance (the genre demands consistent rhythm or parallel structure), clean punctuation, formal vocabulary.

**Failure mode:** The stylometric analyzer will score these texts as AI-like because it measures uniformity, not intentionality. The LLM classifier may also flag them if the genre conventions are strong enough to feel "smooth." Combined score could reach 0.70–0.80.

**Mitigation already built in:** The wide uncertain band (0.43–0.87) means this creator gets a cautious label, not an accusatory one. The label explicitly says "some human writing — especially formal, polished, or conventionally structured work — can resemble AI output." The appeal path is surfaced in the label text itself.

**What the system cannot fix:** It cannot distinguish intentional formalism from AI generation without additional context. This is a fundamental limitation of text-only signals.

---

#### Edge Case 2: Very short submissions (under 100 words)

**Scenario:** A creator submits a haiku, a flash fiction piece of three sentences, or a short poem with eight lines. The word count is too low for meaningful stylometric analysis.

**Failure mode:** TTR on a 40-word text is almost meaningless — a single repeated word changes the ratio dramatically. Sentence length variance is computed from 2–3 data points. The stylometric signal will be noisy and unreliable. If it happens to land far from the LLM score, the disagreement penalty kicks in and pulls the combined score toward 0.5 — which is actually the correct behavior, but for the wrong reason.

**Mitigation already built in:** TTR is excluded below 50 words. The entire stylometric score is nullified below 20 words, and the combined score is capped at 0.65 (forcing an uncertain label). The `short_text_warning: true` flag in the response tells the platform that the analysis is less reliable.

**What the system cannot fix:** It cannot classify very short texts reliably. The honest answer for an 8-word haiku is "we don't know," and the system will say that — but it cannot do better without more text.

---

#### Edge Case 3: AI text that deliberately imitates human messiness

**Scenario:** A user submits AI-generated content that was produced with a prompt like "write this in a casual, unpolished style with sentence fragments, colloquialisms, and irregular punctuation." The stylometric analyzer will find high variance and irregular punctuation — scoring it as human-like. The LLM may or may not see through the imitation depending on how well the prompt worked.

**Failure mode:** If the LLM scores 0.60 (uncertain lean-AI) and the stylometric scores 0.28 (human-like), the disagreement penalty applies and the combined score is pulled toward 0.5. The system outputs `uncertain` — which is technically correct (it is uncertain) but is a false negative in effect.

**Mitigation philosophy:** The spec hint is explicit here: the system does not need to catch all AI content. It needs to be honest about uncertainty. A false negative (missing AI content) is less harmful than a false positive (accusing a human). If the system says "uncertain" about adversarially constructed AI text, it has done its job correctly — it didn't accuse anyone unfairly, and it didn't falsely certify AI content as human.

---

#### Edge Case 4: Non-native English writing with unconventional syntax

**Scenario:** A creator writes in English as a second language. Their syntax is non-standard, their vocabulary choices are unusual by native-speaker norms, and their sentence construction follows patterns from their first language. The LLM classifier may read this as "not how humans write" — but it's exactly how *this* human writes.

**Failure mode:** The LLM is trained predominantly on writing that reflects dominant linguistic norms. Writing that deviates from those norms — even authentically human writing — may register as anomalous. This is a bias in the signal, not a calibration problem.

**Mitigation:** The wide uncertain band and non-accusatory label language reduce the impact, but they don't fix the underlying bias. This edge case argues for making the appeal path as frictionless as possible — creators who are systematically disadvantaged by the classifier need an easy path to human review.

---

## Architecture

*(Unchanged from Milestone 1 — this section travels into Milestones 3–5 as the reference diagram for AI code generation.)*

### Narrative Summary

**Submission flow:** A request enters through the rate limiter, which enforces per-IP limits before the text reaches the pipeline. The submission handler assigns a unique ID and fans the text out to both detection signals in parallel. Signal scores flow into the confidence scoring engine, which applies the weighted formula and disagreement penalty to produce a single score and verdict. The label generator maps that score to one of five label variants. The audit logger writes the full decision record to SQLite. The structured response returns to the client.

**Appeal flow:** An appeal request arrives at the appeal endpoint, which validates the submission ID and checks for a prior appeal. If valid, it writes a new appeal-type audit log entry, updates the original submission's status to `under_review`, and returns a confirmation. No re-classification occurs. The human review queue is exposed via `GET /log?status=under_review`.

### Submission Flow

```
SUBMISSION FLOW
══════════════════════════════════════════════════════════════════

Client
  │
  │  POST /submit  {content, creator_id}
  ▼
┌─────────────────┐
│   Rate Limiter  │──── 429 Too Many Requests ──────────────────▶ Client
└────────┬────────┘         (if limit exceeded)
         │
         │  raw text
         ▼
┌─────────────────────┐
│  Submission Handler │  assigns submission_id, validates input
└──────────┬──────────┘
           │
     raw text + id
     ┌─────┴──────┐
     │            │
     ▼            ▼
┌─────────┐  ┌──────────────────┐
│  Groq   │  │  Stylometric     │
│  LLM    │  │  Analyzer        │
│Classif. │  │  (pure Python)   │
└────┬────┘  └────────┬─────────┘
     │                │
  llm_score        stylometric_score
  (0.0–1.0)        + raw metrics
     │                │
     └────────┬────────┘
              │
              ▼
┌──────────────────────────┐
│   Confidence Scoring     │
│   Engine                 │
│                          │
│  combined_score,         │
│  verdict                 │
│  (human/ai/uncertain)    │
└────────────┬─────────────┘
             │
     verdict + confidence
             │
             ▼
┌──────────────────────────┐
│  Transparency Label      │
│  Generator               │
│                          │
│  → label text string     │
└────────────┬─────────────┘
             │
    full decision record
             │
             ▼
┌──────────────────────────┐
│      Audit Logger        │
│  (SQLite)                │
│                          │
│  writes: id, timestamp,  │
│  scores, verdict, label  │
└────────────┬─────────────┘
             │
    structured JSON response
             │
             ▼
          Client
  {submission_id, verdict, confidence,
   label, signals, status, timestamp}
```

### Appeal Flow

```
APPEAL FLOW
══════════════════════════════════════════════════════════════════

Client
  │
  │  POST /appeal  {submission_id, creator_id, reasoning}
  ▼
┌─────────────────────┐
│  Appeal Endpoint    │
│                     │
│  looks up original  │
│  audit record by    │
│  submission_id      │
└──────────┬──────────┘
           │
    original record + appeal data
           │
           ▼
┌──────────────────────────┐
│      Audit Logger        │
│                          │
│  appends appeal entry:   │
│  appeal_id, timestamp,   │
│  reasoning,              │
│  original verdict        │
│                          │
│  updates status:         │
│  classified →            │
│  under_review            │
└────────────┬─────────────┘
             │
    confirmation response
             │
             ▼
          Client
  {appeal_id, submission_id,
   status: "under_review", message,
   timestamp}
```

---

## AI Tool Plan

> For each implementation milestone, this section specifies: which spec sections to paste into the AI prompt, what to ask it to generate, and how to verify the output before wiring it further.

---

### M3 — Submission Endpoint + Signal 1 (LLM Classifier)

**Spec sections to provide:**
- The **Architecture** section (both diagrams + narrative summary)
- **Detection Signals → Signal 1** (output format, prompt design contract, failure mode handling)
- **API Surface → `POST /submit`** (request/response shape)
- **Uncertainty Representation → Fallback cases table** (so the scaffold knows what to return when Groq fails)

**What to ask the AI tool to generate:**
1. A Flask app skeleton with `POST /submit` wired up, including request validation (content required, non-empty) and unique ID generation (`uuid4`).
2. A `classify_with_llm(text: str) -> dict` function that calls Groq with the exact prompt contract specified above and returns `{"llm_score": float, "reasoning": str}`. Include the JSON extraction logic and the failure-mode fallback (return `None` on any exception).
3. Stub placeholders for the stylometric function, confidence engine, label generator, and audit logger — just function signatures with `pass` bodies — so the architecture is visible before M4 fills them in.

**How to verify before wiring further:**
- Call `classify_with_llm()` directly in a Python REPL with three test inputs: a paragraph of clearly AI-generated text (copy one from a known AI writing sample), a paragraph of clearly human text (a passage from a published novel), and a borderline case (a competent but generic blog post).
- Confirm that the three outputs are meaningfully ordered (AI sample scores highest, novel scores lowest) and that the function handles a Groq API failure gracefully (unplug the API key temporarily and confirm it returns `None` without crashing).
- Test `POST /submit` with curl and confirm the response shape matches the API contract — even with stub functions, the skeleton should return a valid JSON object.

---

### M4 — Signal 2 + Confidence Scoring Engine

**Spec sections to provide:**
- The **Architecture** section (diagrams + narrative)
- **Detection Signals → Signal 2** (all four sub-metrics, normalization formulas, short text handling, the exact variable names)
- **Uncertainty Representation** (the full threshold table, the weighting formula `0.65/0.35`, the disagreement penalty, the fallback cases table)

**What to ask the AI tool to generate:**
1. A `analyze_stylometrics(text: str) -> dict` function that computes all four sub-metrics, normalizes them per the spec formulas, handles the short-text exclusions, and returns `{"stylometric_score": float | None, "detail": {...}, "short_text_warning": bool}`.
2. A `compute_confidence(llm_score, stylometric_score) -> dict` function that implements the weighted formula, the disagreement penalty, and all four fallback cases, returning `{"combined_score": float, "verdict": str, "disagreement_flagged": bool}`.
3. Unit tests (or at minimum, inline assertions) for the confidence engine covering: both signals present and agreeing, both present and disagreeing by >0.35, only LLM available, only stylometric available, neither available.

**What to check:**
- Run `analyze_stylometrics()` on the same three test inputs from M3. Confirm that the AI-generated sample scores higher (more AI-like) than the novel passage. Confirm the short-text warning fires on a submission under 50 words.
- Run `compute_confidence()` with a disagreeing pair (e.g., `llm_score=0.85`, `stylometric_score=0.40`) and confirm the disagreement penalty is applied and the combined score is pulled toward 0.5.
- Confirm that a combined score of 0.62 and a combined score of 0.91 produce different verdicts — `uncertain` and `ai` respectively — per the threshold table.

---

### M5 — Production Layer: Labels, Appeals, Rate Limiting, Audit Log

**Spec sections to provide:**
- The **Architecture** section (diagrams + narrative)
- **Transparency Labels** (all five variant strings, verbatim — paste the exact text blocks)
- **Uncertainty Representation → Threshold table** (so the generator maps scores to the right variant)
- **Appeals Workflow** (the complete specification: validation logic, what gets written, status transitions, the reviewer-facing log shape)
- **API Surface → `POST /appeal`** and **`GET /log`** (request/response shapes)

**What to ask the AI tool to generate:**
1. A `generate_label(combined_score: float, verdict: str) -> str` function that maps scores to the exact label text strings per the threshold table. The label strings must match the verbatim text in this spec — no paraphrasing.
2. The SQLite audit logger: a schema with two tables (`submissions` and `appeals`), an `insert_submission()` function, an `insert_appeal()` function, and an `update_status()` function. The `GET /log` endpoint should join both tables and return entries in the reviewer-facing shape specified in the appeals workflow section.
3. The `POST /appeal` endpoint with full validation: 404 if submission not found, 409 if appeal already exists, status update to `under_review`, and the confirmation response shape.
4. Flask-Limiter configuration on `POST /submit` with the rate limits documented in the README.

**How to verify:**
- Manually reach all five label variants by calling `POST /submit` with inputs tuned to land in each score band. Confirm the `label` field in the response matches the verbatim text in this spec.
- Submit an appeal via `POST /appeal`, then call `GET /status/<submission_id>` and confirm status is `under_review`. Call `GET /log` and confirm the appeal entry is visible with the full reviewer-facing shape.
- Submit a second appeal to the same `submission_id` and confirm the endpoint returns `409`.
- Trigger the rate limit by submitting more requests than the limit allows in the configured window. Confirm the `429` response fires.
- Call `GET /log` and confirm at least 3 entries are visible (required for grading).

---

*Last updated: Milestone 2 — Implementation Spec*