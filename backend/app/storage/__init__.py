"""Blob storage: interface plus swappable adapters.

* ``base.py``   — the ``ObjectStorage`` protocol (the only thing services import)
* ``local.py``  — filesystem adapter for development
* ``s3.py``     — S3-compatible adapter for deployed environments
* ``memory.py`` — in-memory adapter used by tests
* ``factory.py``— selects an adapter from ``STORAGE_BACKEND``

Adding a provider means adding one file. No service changes.
"""
