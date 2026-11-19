"""
router_path.py - the "Path through the agent" drawing of the Developer trace page (phase 9). Plain functions, no Streamlit.

`path_svg(route)` returns one inline SVG (no JavaScript, no image file). The drawing is made from one fact only: the router label
of the turn (`route.router_label` in the trace record). The lane that label names is drawn solid and green, the other six dashed and
grey. A turn that went through a pending confirmation has the label "confirm_step": it skips the router, so the router and all seven
lanes are dashed and the Session -> Confirm step -> Reply line is solid.
"""
import html

# (router label, the name shown). The order is the order of the lanes from top to bottom. These are the labels of [router.labels].
LANES = [("order_status", "Order status"), ("policy_question", "Policy question"), ("return_or_replace", "Return or replace"),
         ("cancel_item", "Cancel an item"), ("human_help", "Human help"), ("out_of_scope", "Out of scope"), ("clarify", "Clarify")]
CONFIRM = "confirm_step"

GREEN, GREY, INK, MUTED = "#0E7C6B", "#A9ABB2", "#16181D", "#5F6470"
W, ROW, TOP = 570, 40, 12


def lane_names() -> list:
    return [name for _, name in LANES]


def taken(route: str | None) -> str | None:
    """The name of the lane a router label stands for, 'Confirm step' for the pending-confirmation bypass, else None."""
    if route == CONFIRM:
        return "Confirm step"
    return next((name for label, name in LANES if label == route), None)


def _box(x, y, w, h, text, on, dashed=False, sub=None, size=13.5) -> str:
    stroke = GREEN if on else GREY
    fill = "#E3F1EE" if on else "#FFFFFF"
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    weight = "700" if on else "400"
    label = f'<text x="{x + w / 2}" y="{y + h / 2 + 4}" text-anchor="middle" font-size="{size}" font-weight="{weight}" fill="{INK}">{html.escape(text)}</text>'
    small = f'<text x="{x + w / 2}" y="{y + h + 12}" text-anchor="middle" font-size="11" fill="{MUTED}">{html.escape(sub)}</text>' if sub else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="{2 if on else 1}"{dash}/>{label}{small}'


def _line(x1, y1, x2, y2, on) -> str:
    stroke = GREEN if on else GREY
    mid = (x1 + x2) / 2
    dash = "" if on else ' stroke-dasharray="5 4"'
    return f'<path d="M{x1} {y1} C{mid} {y1} {mid} {y2} {x2} {y2}" fill="none" stroke="{stroke}" stroke-width="{2.5 if on else 1}"{dash}/>'


def path_svg(route: str | None) -> str:
    """The drawing for a turn whose router label is `route`. An unknown or missing label draws every lane as not taken."""
    confirm = route == CONFIRM
    lane = None if confirm else next((i for i, (label, _) in enumerate(LANES) if label == route), None)
    rows = len(LANES) + 1
    height = TOP * 2 + rows * ROW
    mid_y = TOP + (len(LANES) * ROW) / 2 - 14
    sx, sw, rx, rw, lx, lw, ax, aw, ex, ew = 4, 62, 84, 60, 160, 196, 372, 108, 494, 68
    parts = []
    ok_router = lane is not None
    parts.append(_box(sx, mid_y, sw, 28, "Session", True))
    parts.append(_line(sx + sw, mid_y + 14, rx, mid_y + 14, ok_router))
    parts.append(_box(rx, mid_y, rw, 28, "Router", ok_router, dashed=not ok_router))
    for i, (label, name) in enumerate(LANES):
        y = TOP + i * ROW
        on = lane == i
        parts.append(_line(rx + rw, mid_y + 14, lx, y + 14, on))
        parts.append(_line(lx + lw, y + 14, ax, mid_y + 14, on))
        parts.append(_box(lx, y, lw, 28, name + (" · taken" if on else ""), on, dashed=not on))
    parts.append(_box(ax, mid_y, aw, 28, "Answer check", ok_router, dashed=not ok_router, size=12.5))
    parts.append(_line(ax + aw, mid_y + 14, ex, mid_y + 14, ok_router))
    parts.append(_box(ex, mid_y, ew, 28, "Reply", ok_router or confirm, dashed=not (ok_router or confirm)))
    cy = TOP + len(LANES) * ROW
    parts.append(_line(sx + sw, mid_y + 14, lx, cy + 14, confirm))
    parts.append(_line(lx + lw, cy + 14, ex, mid_y + 14, confirm))
    parts.append(_box(lx, cy, lw, 28, "Confirm step (pending)" + (" · taken" if confirm else ""), confirm, dashed=not confirm,
                      sub="a confirmation is pending: skip the router" if confirm else None))
    said = taken(route)
    label = f"Path through the agent: {said} was taken." if said else "Path through the agent: the route is not recognised, so no lane is marked."
    return (f'<svg class="path-svg" viewBox="0 0 {W} {height + 14}" width="100%" role="img" aria-label="{html.escape(label)}" font-family="Inter, Arial, sans-serif" xmlns="http://www.w3.org/2000/svg">'
            f'<title>{html.escape(label)}</title>{"".join(parts)}</svg>')
