-- Runs once, on first initialisation of the Compose database volume.
--
-- Extensions belong here rather than in an Alembic migration because
-- CREATE EXTENSION requires superuser privileges, which the application role
-- must not have. In a managed environment (RDS, Cloud SQL, Neon) the
-- equivalent is enabled through the provider's console or Terraform.

-- Server-side UUID generation. The application generates UUIDs in Python, but
-- having this available lets a migration backfill a new UUID column without a
-- round trip per row.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Trigram indexes, for fuzzy search over dataset and column names. Users look
-- for "Q3 revenu" and expect to find "Q3 Revenue Report"; a LIKE prefix scan
-- will not do that, and a full-text index is the wrong tool for short labels.
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Query statistics. The first question during any performance investigation
-- is "which statements dominate total time?", and without this extension
-- enabled beforehand there is no way to answer it retrospectively.
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
