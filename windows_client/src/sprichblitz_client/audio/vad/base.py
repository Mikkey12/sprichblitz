"""VAD-Basisklasse + gemeinsames Result-Dataklasse."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from pydantic import BaseModel


class VADResult(BaseModel):
    speech_ratio: float
    is_speech: bool
    backend: str


class BaseVAD(ABC):
    name: str

    @abstractmethod
    def analyse(
        self,
        samples: np.ndarray,
        sample_rate: int,
        min_speech_ratio: float,
    ) -> VADResult:
        ...
