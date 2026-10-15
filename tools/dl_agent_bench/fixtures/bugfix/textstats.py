"""Small text statistics used by the report generator."""


def word_count(text):
    """Number of words in text."""
    return len(text.split(" "))


def top_words(text, n=3):
    """The n most common words, lowercased, punctuation stripped."""
    counts = {}
    for w in text.lower().split():
        w = w.strip(".,!?;:\"'()")
        if w:
            counts[w] = counts.get(w, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [w for w, _ in ranked[:n]]
