"""agy-switcher: Zero-dependency multi-account session manager and resilient coding agent delegator for Antigravity CLI."""

__version__ = "1.0.0"

from agy_switcher.vault import get_vault, BaseVault
from agy_switcher.pool import AccountPool
from agy_switcher.coder import run_agy_delegation, DelegationResult

__all__ = [
    "__version__",
    "get_vault",
    "BaseVault",
    "AccountPool",
    "run_agy_delegation",
    "DelegationResult",
]
