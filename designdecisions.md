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

*Last updated: Milestone 1 — Architecture & Planning*