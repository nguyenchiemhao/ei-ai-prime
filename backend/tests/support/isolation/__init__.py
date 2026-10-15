"""Machinery of the tenant-isolation suite (FND-02), reused by every story that adds a route.

``cases`` (what a developer declares), ``routes`` (discovery and coverage), ``fields`` (request
fields that must not exist), ``checks`` (the cross-tenant assertions), ``client`` (the app under
test), ``snapshot``, ``markers`` and ``jobs``. See README, "Writing isolation tests".
"""
