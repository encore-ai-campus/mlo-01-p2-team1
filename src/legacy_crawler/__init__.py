"""Bronze Relay crawler package.

The package preserves source values and adds lineage metadata only at storage
boundaries. Silver normalization is deliberately outside this package.
"""

from .models import (
    BronzeStatus,
    MongoValidationStatus,
    PipelineStatus,
    RunState,
)

__all__ = [
    "BronzeStatus",
    "MongoValidationStatus",
    "PipelineStatus",
    "RunState",
]

__version__ = "0.1.0"
