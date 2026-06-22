"""Jiejing formal SaaS backend MVP.

This package is the first backend boundary above the existing Jiejing Runtime.
It is intentionally local-first and safe: no real eBay, payment, refund,
procurement, or platform write is executed from this MVP.
"""

from .api_server import SaaSBackendServer
from .config import SaaSSettings
from .ebay_oauth import EbayOAuthPlanner
from .ebay_read_adapter import EbayReadOnlyAdapter
from .independence import build_independence_status
from .readiness import build_product_readiness
from .repository import SaaSRepository
from .runtime_bridge import RuntimeBridge
from .security import SessionManager, hash_password, verify_password
from .secret_store import SecretStoreBoundary

__all__ = [
    "RuntimeBridge",
    "SaaSBackendServer",
    "SaaSRepository",
    "SaaSSettings",
    "SessionManager",
    "EbayOAuthPlanner",
    "EbayReadOnlyAdapter",
    "SecretStoreBoundary",
    "build_independence_status",
    "build_product_readiness",
    "hash_password",
    "verify_password",
]
