"""Source connectors.

Importing this package registers every built-in connector. Third-party
connectors register themselves by subclassing :class:`~trailguide.connectors.base.Connector`
and applying the :func:`~trailguide.connectors.base.register` decorator.
"""

from .base import (  # noqa: F401
    Connector, get_connector, load_sources, read_rows, register, registered_connectors,
)
from . import (  # noqa: F401  - imported for registration side effects
    cms, distribution, ga4, generic, gsc, hubspot,
    llm_panel, performance, screaming_frog, semrush, server_logs, surveys,
)

__all__ = [
    "Connector", "get_connector", "load_sources", "read_rows",
    "register", "registered_connectors",
]
