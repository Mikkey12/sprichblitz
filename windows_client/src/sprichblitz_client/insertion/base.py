"""Text-Insertion-Interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TextInserter(ABC):
    name: str

    @abstractmethod
    def insert(self, text: str) -> None:
        """Fügt ``text`` an der aktuellen Cursor-Position ein."""
