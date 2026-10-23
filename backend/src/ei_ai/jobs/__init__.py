"""Background jobs that always run inside the tenant context of the Organization that queued them
(D46). Queue-agnostic: ``envelope_for`` builds the message, ``run_tenant_job`` executes it.

Handler modules register themselves with ``@JOBS.register(...)`` when they are imported, so each
one must be imported here (``import ei_ai.<area>.jobs  # noqa: F401``): the worker and the
tenant-isolation suite both import ``ei_ai.jobs``, which is how the suite sees the kind and
demands its ``JobCase``. A handler module that nothing imports is invisible to both.
"""

import ei_ai.knowledge.ingestion.job  # noqa: F401
