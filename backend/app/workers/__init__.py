"""Background job execution.

Analysis of a large upload takes longer than a browser will wait, so the API
accepts the work, returns ``202 Accepted`` with a job id, and the client polls
or subscribes for completion. Holding an HTTP connection open for two minutes
is how a service falls over under modest load.

**Deliberate starting point:** FastAPI ``BackgroundTasks`` plus a ``jobs``
table for state. It is enough for launch and adds no infrastructure.

**Known limit, stated up front so nobody discovers it in production:**
in-process tasks die with the process, so a deploy mid-analysis interrupts the
job. The mitigation is that job state lives in PostgreSQL — work is
*resumable* and never silently lost, and a restarted instance can requeue
anything left in ``running``.

**The upgrade path is already designed for:** because services are pure
orchestration with injected dependencies, moving to a real queue (Celery, or
ARQ on Redis) means writing a task shim that calls the same service method.
No service or analytics code changes. Make that move when the job table shows
meaningful requeue volume, or when analyses regularly exceed ~60s.
"""
