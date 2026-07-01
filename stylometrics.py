"""
Signal 2: Stylometric heuristics analyzer (pure Python, no external API).

Spec contract:
  - Input: raw text string
  - Output: {"stylometric_score": float 0.0-1.0 | None, "detail": {...}, "short_text_warning": bool}
  - 0.0 = highly human-like statistical profile
  - 1.0 = highly AI-like statistical profile

Four sub-metrics, each normalized to [0,1], averaged with equal weight
(TTR excluded below 50 words; entire score nulled below 20 words).
"""

import re
import statistics


def _split_sentences(text: str) -> list[str]:
    # Simple sentence splitter on ., !, ?
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in sentences if s.strip()]


def _split_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text)


def analyze_stylometrics(text: str) -> dict:
    words = _split_words(text)
    word_count = len(words)

    # --- Hard floor: fewer than 20 words -> score is None ---
    if word_count < 20:
        return {
            "stylometric_score": None,
            "detail": {
                "word_count": word_count,
                "sentence_variance": None,
                "ttr": None,
                "punct_density": None,
                "avg_word_length": None,
            },
            "short_text_warning": True,
        }

    short_text_warning = word_count < 50

    # --- Sub-metric 1: sentence length variance ---
    sentences = _split_sentences(text)
    sentence_lengths = [len(_split_words(s)) for s in sentences if _split_words(s)]
    if len(sentence_lengths) >= 2:
        sent_std = statistics.stdev(sentence_lengths)
    else:
        sent_std = 0.0  # single sentence -> treat as zero variance (uniform)
    sent_variance_norm = 1 - min(sent_std, 20) / 20  # low variance -> AI -> high score

    # --- Sub-metric 2: type-token ratio (only if word_count >= 50) ---
    ttr = None
    ttr_norm = None
    if word_count >= 50:
        unique_words = set(w.lower() for w in words)
        ttr = len(unique_words) / word_count
        ttr_norm = max(0.0, min(1 - ttr, 1.0))  # high TTR -> human -> low score

    # --- Sub-metric 3: punctuation density ---
    punct_count = len(re.findall(r'[.,;:!?\'"()\-]', text))
    punct_density = punct_count / word_count if word_count else 0.0
    punct_density_norm = 1 - min(punct_density, 0.15) / 0.15  # low density -> AI -> high score

    # --- Sub-metric 4: average word length ---
    avg_word_len = sum(len(w) for w in words) / word_count
    avg_word_len_norm = max(0.0, min((avg_word_len - 3.5) / 3.0, 1.0))  # longer words -> AI

    # --- Combine sub-metrics (equal-weight average) ---
    sub_scores = [sent_variance_norm, punct_density_norm, avg_word_len_norm]
    if ttr_norm is not None:
        sub_scores.append(ttr_norm)

    stylometric_score = sum(sub_scores) / len(sub_scores)
    stylometric_score = round(max(0.0, min(stylometric_score, 1.0)), 4)

    return {
        "stylometric_score": stylometric_score,
        "detail": {
            "word_count": word_count,
            "sentence_variance": round(sent_std, 4),
            "ttr": round(ttr, 4) if ttr is not None else None,
            "punct_density": round(punct_density, 4),
            "avg_word_length": round(avg_word_len, 4),
        },
        "short_text_warning": short_text_warning,
    }


# ---------------------------------------------------------------------------
# Quick smoke-test — run directly: python stylometrics.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        (
            "clearly-ai",
            "Artificial intelligence represents a transformative paradigm shift in modern "
            "society. It is important to note that while the benefits of AI are numerous, "
            "it is equally essential to consider the ethical implications. Furthermore, "
            "stakeholders across various sectors must collaborate to ensure responsible "
            "deployment.",
        ),
        (
            "clearly-human",
            "ok so i finally tried that new ramen place downtown and honestly? "
            "underwhelming. the broth was fine but they put WAY too much sodium in it and "
            "i was thirsty for like three hours after. my friend got the spicy version and "
            "said it was better. probably won't go back unless someone drags me there",
        ),
        (
            "borderline-formal-human",
            "The relationship between monetary policy and asset price inflation has been "
            "extensively studied in the literature. Central banks face a fundamental tension "
            "between their mandate for price stability and the unintended consequences of "
            "prolonged low interest rates on equity and real estate valuations.",
        ),
        (
            "borderline-edited-ai",
            "I've been thinking a lot about remote work lately. There are genuine tradeoffs — "
            "flexibility and no commute on one side, isolation and blurred work-life boundaries "
            "on the other. Studies show productivity varies widely by individual and role type.",
        ),
    ]

    for label, text in samples:
        result = analyze_stylometrics(text)
        print(f"\n[{label}]")
        print(f"  stylometric_score : {result['stylometric_score']}")
        print(f"  short_text_warning: {result['short_text_warning']}")
        print(f"  detail            : {result['detail']}")