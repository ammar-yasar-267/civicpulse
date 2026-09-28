"""RuleBasedTriage unit tests.

This provider is the floor the whole AI layer stands on, so its contract is tested directly:
it always returns, it never raises, and its output always satisfies TriageResult.
"""

import pytest

from app.domain.enums import Category, Priority
from app.providers.triage.rules import RuleBasedTriage
from app.schemas import TriageResult


@pytest.fixture
def rules() -> RuleBasedTriage:
    return RuleBasedTriage()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Burst water main flooding the street since fajr", Category.WATER),
        ("No pani in our lane for three days, tanker is expensive", Category.WATER),
        ("Live wire hanging low, transformer sparking badly", Category.ELECTRICITY),
        ("Load shedding for seven hours and bijli bill is full", Category.ELECTRICITY),
        ("Garbage not lifted for ten days, kachra everywhere", Category.SANITATION),
        ("Gutter overflowing and mosquitoes causing dengue", Category.SANITATION),
        ("Big khadda in the road near school gate", Category.ROADS),
        ("Footpath encroached by shopkeepers", Category.ROADS),
        ("All street lights of our lane are not working", Category.STREETLIGHTS),
        ("Lamp post bulb is fused in the park", Category.STREETLIGHTS),
        ("Stray dogs have increased near the children park", Category.OTHER),
    ],
)
def test_categorises_urdu_influenced_english(
    rules: RuleBasedTriage, text: str, expected: Category
) -> None:
    assert rules.triage(text, "Lahore").category is expected


def test_danger_signals_raise_priority(rules: RuleBasedTriage) -> None:
    dangerous = rules.triage("Live wire is hanging and a child can get a shock", "Street 7")
    assert dangerous.priority is Priority.HIGH


def test_explicit_low_signals_lower_priority(rules: RuleBasedTriage) -> None:
    request = rules.triage(
        "Request for one more dustbin at the corner, not urgent, would be nice", "Street 3"
    )
    assert request.priority is Priority.LOW


def test_streetlights_default_to_low_without_danger_signals(rules: RuleBasedTriage) -> None:
    assert rules.triage("Bulb is fused in our lamp post", "Park").priority is Priority.LOW


def test_summary_respects_the_140_character_contract(rules: RuleBasedTriage) -> None:
    long_text = (
        "Sewerage water is mixing with the drinking water line near our street and the "
        "water is coming yellow and smelling very badly and two children have loose "
        "motions since Tuesday and nobody from the office is picking the phone at all"
    )
    result = rules.triage(long_text, "Mohalla Islampura, Faisalabad")

    assert len(result.summary) <= 140
    assert "\n" not in result.summary
    assert result.summary.startswith("Mohalla Islampura")


def test_never_raises_on_hostile_input(rules: RuleBasedTriage) -> None:
    """Empty-ish text, emoji, a pathological location — the floor must hold."""
    for text, location in [
        ("..........", "xxx"),
        ("🚰💧 water leaking 💧🚰", "Lahore"),
        ("a" * 2000, "b" * 200),
        ("<script>alert(1)</script> gutter blocked", "Karachi"),
    ]:
        result = rules.triage(text, location)
        assert isinstance(result, TriageResult)
        assert len(result.summary) <= 140


def test_confidence_is_honest_about_weak_signals(rules: RuleBasedTriage) -> None:
    """No keyword match means low confidence, not a confident 'other'."""
    vague = rules.triage("Please look into this matter quickly", "Somewhere")
    strong = rules.triage("Burst water main pipeline leaking, pani everywhere", "Street 12")

    assert vague.category is Category.OTHER
    assert vague.confidence < strong.confidence
    assert strong.confidence <= 1.0
