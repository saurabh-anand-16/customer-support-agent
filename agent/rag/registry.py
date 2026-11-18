"""
registry.py - swappable parts, looked up by name.

A part (for example a chunker) is a class with a `@register("chunker", "heading")` line above
it. The config names the part it wants; `get("chunker", name)` finds it. Adding a new part is
one new file plus that one line plus a name in the config.
"""
_PARTS: dict[str, dict[str, type]] = {}


def register(kind: str, name: str):
    """Class decorator: make `cls` available as part `name` of the given `kind`."""
    def wrap(cls):
        parts = _PARTS.setdefault(kind, {})
        if name in parts:
            raise ValueError(f"A {kind} named '{name}' is already registered")
        parts[name] = cls
        return cls
    return wrap


def names(kind: str) -> list[str]:
    """Registered names of one kind, sorted."""
    return sorted(_PARTS.get(kind, {}))


def get(kind: str, name: str) -> type:
    """The class registered under (kind, name). Unknown names list what is available."""
    parts = _PARTS.get(kind, {})
    if name not in parts:
        raise KeyError(f"No {kind} named '{name}'. Available: {', '.join(sorted(parts)) or 'none'}")
    return parts[name]
