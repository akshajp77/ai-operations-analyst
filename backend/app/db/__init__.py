"""Database engine, session lifecycle, declarative base, and migrations.

This package knows about PostgreSQL. Nothing above it should: services take
an ``AsyncSession`` and repositories translate it into rows, so swapping the
persistence detail never reaches business logic.
"""
