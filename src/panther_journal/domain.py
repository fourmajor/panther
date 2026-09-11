"""Structured game records; a player identity does not imply a Panther login account."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Slug = str


class NamedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Slug = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=96)
    name: str = Field(min_length=1, max_length=120)


class Player(NamedEntity):
    """Stable person identity, reusable across games; no character or account conflation."""


class Character(NamedEntity):
    """Fictional identity scoped to a game."""


class GameMembership(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    playerId: str
    role: Literal["player", "dungeon-master"]
    characterIds: list[str] = Field(default_factory=list, max_length=20)


class GameSetup(NamedEntity):
    visualStyle: Literal[
        "photorealistic",
        "anime",
        "illustrated-fantasy",
        "comic-book",
        "watercolor",
        "oil-painting",
        "stylized-3d",
        "pixel-art",
    ] = "photorealistic"
    purpose: Literal["campaign", "test"]
    ruleset: str = Field(min_length=1, max_length=120)
    players: list[Player] = Field(default_factory=list, max_length=20)
    characters: list[Character] = Field(default_factory=list, max_length=20)
    memberships: list[GameMembership] = Field(default_factory=list, max_length=20)

    @field_validator("ruleset")
    @classmethod
    def ruleset_name(cls, value):
        if value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Ruleset must be a name without surrounding whitespace or controls")
        return value

    @model_validator(mode="after")
    def references(self):
        players = {p.id for p in self.players}
        characters = {c.id for c in self.characters}
        members = {m.playerId for m in self.memberships}
        if len(players) != len(self.players) or len(characters) != len(self.characters):
            raise ValueError("Duplicate player or character ID")
        if members != players or len(members) != len(self.memberships):
            raise ValueError("Each player needs exactly one membership")
        for m in self.memberships:
            if not set(m.characterIds) <= characters or len(set(m.characterIds)) != len(
                m.characterIds
            ):
                raise ValueError("Unknown or duplicate character association")
            if m.role == "dungeon-master" and m.characterIds:
                raise ValueError("Dungeon Master is a role, not a character")
        return self
