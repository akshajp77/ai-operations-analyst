"""HTTP interface layer.

The only layer that knows about HTTP. Its job is narrow and mechanical:

* parse and validate the request into typed schema objects,
* resolve dependencies (session, settings, current user),
* call exactly one service method,
* return a typed response model.

Business rules do not live here. When a route function grows past roughly
twenty lines or contains an ``if`` that encodes a policy decision, that logic
belongs in ``app/services``.
"""
