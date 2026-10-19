"""The Platform Operator commands of the CLI: ``org create``, ``workspace create``,
``user invite``, ``user link``. Argument parsing, the service call and the exact output.

Output is English only (an operator tool, like ``ei-ai db``). Set-password links go to stdout
once and never through ``logging`` (D52). Unexpected errors print the exception class only: their
messages can hold SQL values or connection strings.
"""

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncEngine

from ei_ai.auth.set_password import set_password_link
from ei_ai.db.engine import run_with_app_engine
from ei_ai.provisioning.service import (
    DEFAULT_WORKSPACE_NAME,
    create_organization,
    create_workspace,
    invite_user,
    issue_link,
)
from ei_ai.provisioning.validation import ProvisioningError, parse_uuid
from ei_ai.settings import CliSettings, SettingsError, admin_base_url

COMMAND_GROUPS = ("org", "workspace", "user")
LINK_LABEL = "Set-password link (valid 24 h, shown once)"
_ORG_ID = "--org must be an Organization id (UUID)"
_WORKSPACE_ID = "--workspace must be a Workspace id (UUID)"

# Runs the service with an engine and the admin base URL; returns the stdout lines.
Work = Callable[[AsyncEngine, str], Awaitable[list[str]]]


def link_line(base_url: str, org_id: uuid.UUID, secret: str) -> str:
    """The stdout line that shows a set-password link once."""
    return f"{LINK_LABEL}: {set_password_link(base_url, org_id, secret)}"


def add_provisioning_parsers(
    commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    """Add the org, workspace and user subcommands to the ``ei-ai`` parser."""
    org = commands.add_parser("org", help="Organizations (Platform Operator)")
    org_create = org.add_subparsers(dest="action", required=True).add_parser(
        "create", help="an Organization, its default Workspace and its Org Owner"
    )
    org_create.add_argument("--name", required=True)
    org_create.add_argument("--owner", required=True, metavar="EMAIL")
    org_create.add_argument("--owner-name", metavar="DISPLAY_NAME")
    org_create.add_argument("--workspace-name", default=DEFAULT_WORKSPACE_NAME, metavar="NAME")

    workspace = commands.add_parser("workspace", help="Workspaces (Platform Operator)")
    ws_create = workspace.add_subparsers(dest="action", required=True).add_parser(
        "create", help="a Workspace in an Organization"
    )
    ws_create.add_argument("--org", required=True, metavar="ORG_ID")
    ws_create.add_argument("--name", required=True)

    user = commands.add_parser("user", help="users (Platform Operator)")
    user_actions = user.add_subparsers(dest="action", required=True)
    invite = user_actions.add_parser("invite", help="invite a user with roles")
    invite.add_argument("--org", required=True, metavar="ORG_ID")
    invite.add_argument("--email", required=True)
    invite.add_argument("--role", required=True, action="append", metavar="ROLE")
    invite.add_argument("--workspace", metavar="WORKSPACE_ID")
    invite.add_argument("--name", metavar="DISPLAY_NAME")
    link = user_actions.add_parser("link", help="a new set-password link for a user")
    link.add_argument("--org", required=True, metavar="ORG_ID")
    link.add_argument("--email", required=True)


def _org_create(args: argparse.Namespace) -> Work:
    """The work of ``org create``: Organization, Workspace, Org Owner and the link line."""

    async def work(engine: AsyncEngine, base_url: str) -> list[str]:
        """Run the service call and return the stdout lines."""
        result = await create_organization(
            engine,
            name=args.name,
            owner_email=args.owner,
            owner_name=args.owner_name,
            workspace_name=args.workspace_name,
        )
        return [
            f"Organization created: {result.org_id} ({result.org_name})",
            f"Workspace created: {result.workspace_id} ({result.workspace_name})",
            f"Org Owner created: {result.owner_id} ({result.owner_email})",
            link_line(base_url, result.org_id, result.secret),
        ]

    return work


def _workspace_create(args: argparse.Namespace) -> Work:
    """The work of ``workspace create`` (the --org value is checked first)."""
    org_id = parse_uuid(args.org, _ORG_ID)

    async def work(engine: AsyncEngine, base_url: str) -> list[str]:
        """Run the service call and return the stdout lines."""
        result = await create_workspace(engine, org_id, args.name)
        return [f"Workspace created: {result.workspace_id} ({result.name})"]

    return work


def _user_invite(args: argparse.Namespace) -> Work:
    """The work of ``user invite`` (the --org and --workspace values are checked first)."""
    org_id = parse_uuid(args.org, _ORG_ID)
    workspace_id = None if args.workspace is None else parse_uuid(args.workspace, _WORKSPACE_ID)

    async def work(engine: AsyncEngine, base_url: str) -> list[str]:
        """Run the service call and return the stdout lines."""
        result = await invite_user(
            engine, org_id, args.email, args.role, workspace_id=workspace_id, display_name=args.name
        )
        return [
            f"User invited: {result.user_id} ({result.email}) roles: {', '.join(result.roles)}",
            link_line(base_url, org_id, result.secret),
        ]

    return work


def _user_link(args: argparse.Namespace) -> Work:
    """The work of ``user link`` (the --org value is checked first)."""
    org_id = parse_uuid(args.org, _ORG_ID)

    async def work(engine: AsyncEngine, base_url: str) -> list[str]:
        """Run the service call and return the stdout lines."""
        result = await issue_link(engine, org_id, args.email)
        return [link_line(base_url, org_id, result.secret)]

    return work


# (command name, needs ADMIN_BASE_URL, builder of the work)
_HANDLERS: dict[tuple[str, str], tuple[bool, Callable[[argparse.Namespace], Work]]] = {
    ("org", "create"): (True, _org_create),
    ("workspace", "create"): (False, _workspace_create),
    ("user", "invite"): (True, _user_invite),
    ("user", "link"): (True, _user_link),
}


def run_provisioning_command(args: argparse.Namespace) -> int:
    """Run one parsed command; returns the exit code (0 done, 1 failed)."""
    command = f"{args.command} {args.action}"
    needs_link, build = _HANDLERS[(args.command, args.action)]
    try:
        settings = CliSettings.from_env(os.environ)
        base_url = admin_base_url(os.environ, settings.environment) if needs_link else ""
    except SettingsError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 1
    try:
        work = build(args)
        lines = asyncio.run(
            run_with_app_engine(settings.database_url, lambda engine: work(engine, base_url))
        )
    except ProvisioningError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        # Exception class only: messages can carry SQL values or connection strings (D52).
        print(f"error: {command} failed ({type(error).__name__})", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0
