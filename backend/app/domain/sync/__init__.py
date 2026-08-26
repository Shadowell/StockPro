"""Sync domain package.

The legacy sync service still imports exchange adapters. Keep it lazy so the
A-share read-only backend can import sync submodules without requiring dormant
digital-asset dependencies.
"""

__all__ = ["sync_domain_service", "SyncDomainService"]


def __getattr__(name):
    if name in __all__:
        from .service import SyncDomainService, sync_domain_service

        return {
            "SyncDomainService": SyncDomainService,
            "sync_domain_service": sync_domain_service,
        }[name]
    raise AttributeError(name)
