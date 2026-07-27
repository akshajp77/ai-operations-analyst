"""Service-tier unit tests.

Services orchestrate, so their tests run them against fakes — an in-memory
storage adapter, a typed fake database — rather than against real I/O. That is
what keeps this tier fast enough to run on every save.
"""
