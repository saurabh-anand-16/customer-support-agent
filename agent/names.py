"""
names.py - one helper that shortens a catalogue product name for display (phase 8c).

Catalogue names can be very long ("Redmi 13C | 6000mAh Battery | Upto 12GB RAM ..."). The name is cut at the first " | ", and then
at `max_chars` with an ellipsis. It is for text a customer reads (notices, cards, the chat header). The stored name is never changed,
and the model and the answer check keep seeing the full name.
"""


def short_product_name(name, max_chars: int = 60) -> str:
    text = " ".join(str(name or "").split())
    text = text.split(" | ")[0].strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip(" ,;:|-") + "…"
