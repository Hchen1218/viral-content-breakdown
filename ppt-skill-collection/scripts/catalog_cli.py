#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parents[1] / "references" / "catalog.json"
VALID_AGENTS = ("claude_code", "codex", "generic")
DIRECT_STATUS = "direct_command"


def load_catalog() -> dict[str, Any]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "projects" not in data:
        raise ValueError(f"Invalid catalog structure: {CATALOG_PATH}")
    if not isinstance(data["projects"], list):
        raise ValueError("catalog.json projects must be a list")
    return data


def listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"Expected string list item, got {type(item).__name__}")
            items.append(item)
        return items
    raise ValueError(f"Expected string or list of strings, got {type(value).__name__}")


def find_project(catalog: dict[str, Any], project_id: str) -> dict[str, Any]:
    for project in catalog["projects"]:
        if project.get("id") == project_id:
            return project
    known = ", ".join(sorted(project["id"] for project in catalog["projects"]))
    raise KeyError(f"Unknown project id '{project_id}'. Known ids: {known}")


def get_route(project: dict[str, Any], agent: str) -> dict[str, Any]:
    if agent not in VALID_AGENTS:
        raise ValueError(f"Unsupported agent '{agent}'. Use one of: {', '.join(VALID_AGENTS)}")
    routes = project.get("install_routes")
    if not isinstance(routes, dict):
        raise ValueError(f"Project '{project['id']}' is missing install_routes")
    route = routes.get(agent)
    if not isinstance(route, dict):
        raise ValueError(f"Project '{project['id']}' is missing route for agent '{agent}'")
    return route


def validate_commands(route: dict[str, Any]) -> list[list[str]]:
    commands = route.get("commands", [])
    if not isinstance(commands, list):
        raise ValueError("Route commands must be a list")
    validated: list[list[str]] = []
    for argv in commands:
        if not isinstance(argv, list) or not argv:
            raise ValueError("Each command must be a non-empty argv list")
        command: list[str] = []
        for arg in argv:
            if not isinstance(arg, str) or not arg:
                raise ValueError("Each argv item must be a non-empty string")
            command.append(arg)
        validated.append(command)
    return validated


def render_section(title: str, items: list[str]) -> None:
    if not items:
        return
    print(f"{title}:")
    for item in items:
        print(f"- {item}")


def format_command(argv: list[str]) -> str:
    return shlex.join(argv)


def show_project(project: dict[str, Any]) -> None:
    print(f"ID: {project['id']}")
    print(f"Name: {project['name']}")
    print(f"Kind: {project['kind']}")
    print(f"Repo: {project['repo_url']}")
    print(f"Tagline: {project['tagline']}")
    render_section("Best for", listify(project.get("best_for")))
    render_section("Not for", listify(project.get("not_for")))
    render_section("Outputs", listify(project.get("outputs")))
    render_section("Recommend signals", listify(project.get("recommend_signals")))
    render_section("Counter signals", listify(project.get("counter_signals")))
    render_section("Secondary pairings", listify(project.get("secondary_pairings")))
    print("Install route summary:")
    for agent in VALID_AGENTS:
        route = get_route(project, agent)
        print(f"- {agent}: {route.get('status', 'unknown')}")


def print_install(project: dict[str, Any], agent: str) -> None:
    route = get_route(project, agent)
    print(f"Project: {project['name']} ({project['id']})")
    print(f"Agent: {agent}")
    print(f"Status: {route.get('status', 'unknown')}")
    commands = validate_commands(route)
    if commands:
        print("Commands:")
        for argv in commands:
            print(f"- {format_command(argv)}")
    render_section("Display steps", listify(route.get("display_steps")))
    render_section("Notes", listify(route.get("notes")))


def run_install(project: dict[str, Any], agent: str, dry_run: bool, cwd: str | None) -> int:
    route = get_route(project, agent)
    status = route.get("status")
    if status != DIRECT_STATUS:
        print(
            f"Refusing to execute install for '{project['id']}' on '{agent}': "
            f"route status is '{status}', not '{DIRECT_STATUS}'.",
            file=sys.stderr,
        )
        print_install(project, agent)
        return 2

    commands = validate_commands(route)
    if not commands:
        print("Route is direct_command but has no commands.", file=sys.stderr)
        return 3

    run_cwd = Path(cwd).resolve() if cwd else None
    if run_cwd and not run_cwd.exists():
        raise FileNotFoundError(f"--cwd path not found: {run_cwd}")

    for argv in commands:
        print(f"$ {format_command(argv)}")
        if dry_run:
            continue
        subprocess.run(argv, cwd=run_cwd, check=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Catalog helper for ppt-skill-collection")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Show project summary")
    show_parser.add_argument("project_id", help="Catalog project id")

    install_parser = subparsers.add_parser("print-install", help="Print install route for an agent")
    install_parser.add_argument("project_id", help="Catalog project id")
    install_parser.add_argument("--agent", required=True, choices=VALID_AGENTS)

    run_parser = subparsers.add_parser("run-install", help="Run direct_command install routes only")
    run_parser.add_argument("project_id", help="Catalog project id")
    run_parser.add_argument("--agent", required=True, choices=VALID_AGENTS)
    run_parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them")
    run_parser.add_argument("--cwd", help="Optional working directory for the install command")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    catalog = load_catalog()
    project = find_project(catalog, args.project_id)

    if args.command == "show":
        show_project(project)
        return 0
    if args.command == "print-install":
        print_install(project, args.agent)
        return 0
    if args.command == "run-install":
        return run_install(project, args.agent, args.dry_run, args.cwd)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
