"""Reading which constraint a database error violated."""

from sqlalchemy.exc import IntegrityError


def violated_constraint(error: IntegrityError) -> str | None:
    """Name of the constraint a database error violated, if the driver reports one."""
    diag = getattr(error.orig, "diag", None)
    name: str | None = getattr(diag, "constraint_name", None)
    return name
