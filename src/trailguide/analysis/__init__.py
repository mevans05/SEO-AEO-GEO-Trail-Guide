"""Analysis layer: the dark-traffic model and the opportunity analyzers.

Importing this package registers every built-in analyzer.
"""

from .base import (  # noqa: F401
    AnalysisContext, Analyzer, register_analyzer, registered_analyzers, select_analyzers,
)
from .dark_traffic import DarkTrafficResult, model_dark_traffic  # noqa: F401
from . import generative, growth, search, technical  # noqa: F401  - registration side effects

__all__ = [
    "AnalysisContext", "Analyzer", "DarkTrafficResult", "model_dark_traffic",
    "register_analyzer", "registered_analyzers", "select_analyzers",
]
