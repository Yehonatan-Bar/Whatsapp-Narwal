"""Turn a natural-language chat message into a concrete robot clean intent.

This is the whole "understanding" layer of the project, and it is deliberately pure (no I/O, no
network, no robot): given a message's text plus the room map from the config, it decides whether the
message is a clean command and, if so, what to clean. That makes it trivially unit-testable
(tests/test_narwal_commands.py) and keeps every home-specific detail -- room names and their numeric
IDs -- in the local config rather than in code.

The rule, in two parts:

1. A message is a **command** only if it contains a clean verb (e.g. "נקה"/"clean"). This is what
   separates a command from ordinary chatter in a group ("thanks!", "the robot is stuck"). The group
   may be dedicated to commands, but the verb gate keeps a stray non-command message from moving the
   robot -- and, when messages are polled rather than pushed, it lets a caller pick the most recent
   *command* and ignore chatter that came after it.
2. The **target** is resolved from the same text: a whole-home phrase ("everything"/"הכל") wins;
   otherwise room aliases are matched longest-first and consumed, so "living-room toilet" maps to the
   one room called that, not to "living room" plus "toilet".

Everything is config-driven, so it works in any language: put your verbs, whole-home aliases and
room-name -> room-ID map in the config (see config.example.json).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

# Fold Hebrew combining points (niqqud/cantillation) and the geresh/gershayim/apostrophe glyphs so a
# spoken-style or pointed spelling matches a plainly typed word. Harmless for other languages.
_NIQQUD = "".join(chr(codepoint) for codepoint in range(0x0591, 0x05C8))
_GERESH = "'׳״’ʼ`′"
_STRIP = {ord(char): None for char in _NIQQUD + _GERESH}
_WHITESPACE = re.compile(r"\s+")
# A leading "ו" ("and") on a Hebrew verb: "ושטוף" -> "שטוף".
_VAV = re.compile(r"^ו")


@dataclass(frozen=True)
class CleanIntent:
    """What the robot should clean. `scope` is "all" (whole home) or "rooms"; `room_ids` is the
    ordered, de-duplicated list of numeric room IDs for a "rooms" intent, and empty for "all"."""

    scope: str
    room_ids: tuple[int, ...] = ()


def normalize(text: str | None) -> str:
    if not text:
        return ""
    return _WHITESPACE.sub(" ", text.translate(_STRIP)).strip().lower()


def has_clean_verb(text: str | None, verbs: Sequence[str]) -> bool:
    """True if the (normalised) text contains one of the clean verbs as a whole word."""
    normalized = normalize(text)
    wanted = {normalize(verb) for verb in verbs}
    for token in normalized.split():
        if token in wanted or _VAV.sub("", token) in wanted:
            return True
    return False


def parse_command(
    text: str | None,
    *,
    rooms: Mapping[str, Sequence[int]],
    all_aliases: Sequence[str],
    verbs: Sequence[str],
) -> CleanIntent | None:
    """Resolve a chat message into a clean intent, or None if it is not a clean command.

    None is returned when the message carries no clean verb, or a verb but no recognised area -- the
    caller then does nothing rather than guess. A whole-home phrase wins over any room match. Room
    aliases are matched longest-first and consumed, so a two-word room name is not also counted as the
    shorter room whose name it contains.
    """
    normalized = normalize(text)
    if not normalized or not has_clean_verb(normalized, verbs):
        return None

    for alias in all_aliases:
        normalized_alias = normalize(alias)
        if normalized_alias and normalized_alias in normalized:
            return CleanIntent(scope="all")

    remaining = normalized
    room_ids: list[int] = []
    for alias in sorted(rooms, key=lambda name: len(normalize(name)), reverse=True):
        normalized_alias = normalize(alias)
        if normalized_alias and normalized_alias in remaining:
            for room_id in rooms[alias]:
                if room_id not in room_ids:
                    room_ids.append(room_id)
            remaining = remaining.replace(normalized_alias, " ")

    if not room_ids:
        return None
    return CleanIntent(scope="rooms", room_ids=tuple(room_ids))
