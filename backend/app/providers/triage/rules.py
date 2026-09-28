"""Deterministic keyword triage.

Contract: this provider always returns. It never raises, never touches the network and
never needs a key, because it is the floor the whole AI layer falls back to (§2.5).
Every `if` here is a guess a language model would make better — that is the point of
measuring the two against each other in docs/TRIAGE.md.
"""

import re

from app.domain.enums import Category, Priority
from app.schemas import TriageResult

# Urdu-influenced English is the register real complaints arrive in, so the keyword sets
# carry the local vocabulary alongside the textbook terms.
_CATEGORY_KEYWORDS: dict[Category, tuple[str, ...]] = {
    Category.WATER: (
        "water",
        "pani",
        "burst main",
        "water main",
        "pipeline",
        "pipe",
        "leak",
        "leakage",
        "sewer water",
        "tap",
        "boring",
        "tanker",
        "flood",
        "flooding",
        "drinking water",
        "supply line",
    ),
    Category.ELECTRICITY: (
        "electric",
        "electricity",
        "bijli",
        "power",
        "load shedding",
        "loadshedding",
        "transformer",
        "pmt",
        "wapda",
        "k-electric",
        "kesc",
        "outage",
        "current",
        "wire",
        "wiring",
        "shock",
        "meter",
        "grid",
        "voltage",
        "spark",
        "sparking",
    ),
    Category.SANITATION: (
        "garbage",
        "kachra",
        "trash",
        "rubbish",
        "sewerage",
        "sewage",
        "gutter",
        "nala",
        "drain",
        "drainage",
        "manhole",
        "sanitation",
        "waste",
        "dump",
        "dumping",
        "smell",
        "stink",
        "mosquito",
        "mosquitoes",
        "dengue",
        "overflow",
        "choke",
        "choked",
        "blocked drain",
    ),
    Category.ROADS: (
        "road",
        "sarak",
        "pothole",
        "potholes",
        "khadda",
        "footpath",
        "pavement",
        "speed breaker",
        "manhole cover",
        "traffic signal",
        "signal",
        "bridge",
        "underpass",
        "encroachment",
        "broken road",
        "carpeting",
        "asphalt",
    ),
    Category.STREETLIGHTS: (
        "streetlight",
        "street light",
        "street lights",
        "streetlights",
        "lamp",
        "lamp post",
        "light pole",
        "pole light",
        "dark street",
        "no light",
        "lights not working",
        "bulb",
    ),
}

# Words that mean "this is not a streetlight complaint, somebody could die today".
_HIGH_SIGNALS: tuple[str, ...] = (
    "burst",
    "flood",
    "flooding",
    "shock",
    "electrocut",
    "spark",
    "fire",
    "collapse",
    "collapsed",
    "injur",
    "injured",
    "death",
    "died",
    "dead",
    "danger",
    "dangerous",
    "emergency",
    "urgent",
    "hospital",
    "school",
    "child",
    "children",
    "bachay",
    "live wire",
    "open manhole",
    "gas leak",
    "overflowing into",
    "entering homes",
    "entering ground floor",
    "no water for",
    "three days",
    "week",
)

# Stand-in token for a negated urgency phrase; see _NEGATED_URGENCY below.
_NEGATED_MARKER = "lowurgencymarker"

_LOW_SIGNALS: tuple[str, ...] = (
    "request",
    "suggestion",
    "kindly consider",
    "would be nice",
    "please plan",
    "cosmetic",
    "paint",
    "faded",
    "minor",
    "small",
    "eventually",
    "someday",
    "at your convenience",
    _NEGATED_MARKER,
)

# Substring matching is naive in one specific way that matters: "not urgent" contains
# "urgent", so a citizen politely saying a request is not urgent would otherwise score as
# HIGH. Negated forms are collapsed to a marker before the high-signal scan, and the marker
# itself counts as a low signal.
_NEGATED_URGENCY: tuple[str, ...] = (
    "not urgent",
    "non-urgent",
    "nonurgent",
    "not very urgent",
    "not an emergency",
    "no emergency",
    "not dangerous",
    "not a danger",
    "no danger",
    "not injured",
    "nobody injured",
    "no injury",
    "not a fire",
    "no fire",
)


def _normalise(text: str, location: str) -> str:
    haystack = f"{text} {location}".lower()
    for phrase in _NEGATED_URGENCY:
        haystack = haystack.replace(phrase, f" {_NEGATED_MARKER} ")
    return haystack


def _score_categories(haystack: str) -> dict[Category, int]:
    scores: dict[Category, int] = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in haystack)
        if hits:
            scores[category] = hits
    return scores


def _pick_category(haystack: str) -> tuple[Category, float]:
    """Return the best category and a confidence derived from how clear the win was.

    Confidence is honest rather than flattering: a single keyword hit is a weak signal
    and says so, which is what makes the number usable on the dashboard.
    """
    scores = _score_categories(haystack)
    if not scores:
        return Category.OTHER, 0.25

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_hits = ranked[0]
    runner_up_hits = ranked[1][1] if len(ranked) > 1 else 0

    if best_hits >= 2 and best_hits > runner_up_hits:
        confidence = 0.75
    elif best_hits > runner_up_hits:
        confidence = 0.6
    else:
        confidence = 0.45  # tie between categories; the text is genuinely ambiguous
    return best, confidence


def _pick_priority(haystack: str, category: Category) -> Priority:
    if any(signal in haystack for signal in _HIGH_SIGNALS):
        return Priority.HIGH
    if any(signal in haystack for signal in _LOW_SIGNALS):
        return Priority.LOW
    # A dark street is a nuisance; a burst main is not. Absent explicit signals, the
    # category itself carries the default severity.
    if category is Category.STREETLIGHTS:
        return Priority.LOW
    if category in (Category.WATER, Category.ELECTRICITY):
        return Priority.HIGH
    return Priority.NORMAL


def _summarise(text: str, location: str, category: Category) -> str:
    """First sentence, trimmed to the 140-char contract, prefixed with the location."""
    first = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    first = " ".join(first.split())
    prefix = f"{location.strip()}: "
    budget = 140 - len(prefix)
    if budget < 20:  # pathologically long location — summarise on category alone
        return f"{category.value} complaint"[:140]
    if len(first) > budget:
        first = first[: budget - 1].rstrip() + "…"
    return f"{prefix}{first}"


class RuleBasedTriage:
    """Always available, never fails."""

    name = "rules"

    def triage(self, text: str, location: str) -> TriageResult:
        haystack = _normalise(text, location)
        category, confidence = _pick_category(haystack)
        return TriageResult(
            category=category,
            priority=_pick_priority(haystack, category),
            summary=_summarise(text, location, category),
            confidence=confidence,
        )
