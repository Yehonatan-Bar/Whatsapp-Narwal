"""Pure tests for the message -> clean-intent parser (narwal_commands.py). No robot, no network."""

from narwal_commands import CleanIntent, has_clean_verb, normalize, parse_command

ROOMS = {
    # English
    "living room": [1], "living": [1], "salon": [1],
    "kitchen": [2],
    "bathroom": [4], "toilet": [4],
    "hallway": [5], "corridor": [5],
    # Hebrew (mixed on purpose: the parser is language-agnostic and config-driven)
    "סלון": [1],
    "מטבח": [2],
    "המאורה": [3], "מאורה": [3],
    "שרותי המאורה": [6],
}
ALL_ALIASES = ["everything", "whole home", "all", "הכל", "כל הבית", "הבית"]
VERBS = ["clean", "vacuum", "mop", "נקה", "תנקה", "שאב", "שטוף"]


def parse(text):
    return parse_command(text, rooms=ROOMS, all_aliases=ALL_ALIASES, verbs=VERBS)


class TestNormalize:
    def test_strips_points_and_geresh(self):
        assert normalize("גימליָה") == "גימליה"
        assert normalize("ג׳ימלי") == "גימלי"

    def test_lowercases_and_collapses_whitespace(self):
        assert normalize("  Clean  The   Kitchen ") == "clean the kitchen"
        assert normalize(None) == ""


class TestVerbGate:
    def test_a_clean_verb_is_required(self):
        assert has_clean_verb("clean the kitchen", VERBS)
        assert has_clean_verb("נקה את הסלון", VERBS)
        assert not has_clean_verb("the kitchen is dirty", VERBS)

    def test_leading_vav_on_a_hebrew_verb(self):
        assert has_clean_verb("שאב ושטוף את הסלון", VERBS)


class TestParseCommand:
    def test_english_single_room(self):
        assert parse("clean the kitchen") == CleanIntent(scope="rooms", room_ids=(2,))

    def test_hebrew_single_room(self):
        assert parse("נקה את הסלון") == CleanIntent(scope="rooms", room_ids=(1,))

    def test_whole_home_wins(self):
        assert parse("clean everything") == CleanIntent(scope="all")
        assert parse("נקה הכל") == CleanIntent(scope="all")

    def test_longer_room_alias_is_not_shadowed(self):
        # "שרותי המאורה" is room 6 alone, not rooms 6 and 3 (it contains "מאורה").
        assert parse("נקה את שרותי המאורה") == CleanIntent(scope="rooms", room_ids=(6,))

    def test_multiple_rooms(self):
        intent = parse("clean the kitchen and the living room")
        assert intent.scope == "rooms"
        assert set(intent.room_ids) == {1, 2}

    def test_no_verb_is_not_a_command(self):
        assert parse("where is the kitchen") is None
        assert parse("הסלון מלוכלך") is None

    def test_verb_without_a_known_room_is_none(self):
        assert parse("clean the garage") is None

    def test_empty_is_none(self):
        assert parse("") is None
        assert parse(None) is None
