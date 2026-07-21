#!/usr/bin/env python3
"""Validate generated-project answers and required local development ports."""

from __future__ import annotations

import argparse
import re
import socket
import sys


LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]+)*$")
REPO_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LOCAL_PORTS = {
    1025: "MailHog SMTP",
    5434: "PostgreSQL",
    5678: "debugpy",
    8000: "Django",
    8001: "Django with pdb",
    8025: "MailHog web UI",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--languages", required=True)
    parser.add_argument("--default-language", required=True)
    parser.add_argument("--use-translations", choices=("true", "false"), required=True)
    return parser.parse_args()


def validate_answers(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    if not REPO_NAME_PATTERN.fullmatch(args.repo_name):
        errors.append(
            "repo_name must contain lowercase letters, digits and single hyphens only"
        )

    languages = [language.strip() for language in args.languages.split(",")]

    if args.use_translations == "true":
        if len(languages) < 2:
            errors.append("choose at least two language codes")
        if len(languages) != len(set(languages)):
            errors.append("language codes must not be repeated")
        invalid = [
            language
            for language in languages
            if not LANGUAGE_CODE_PATTERN.fullmatch(language)
        ]
        if invalid:
            errors.append("invalid language code(s): " + ", ".join(invalid))
        if args.default_language not in languages:
            errors.append(
                f"default_language '{args.default_language}' must be in languages"
            )
    return errors


def unavailable_ports() -> list[tuple[int, str, OSError]]:
    unavailable: list[tuple[int, str, OSError]] = []
    for port, service in LOCAL_PORTS.items():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                unavailable.append((port, service, error))
    return unavailable


def main() -> None:
    args = parse_args()
    errors = validate_answers(args)
    unavailable = unavailable_ports()
    if not errors and not unavailable:
        return

    print("\nCannot create the project:", file=sys.stderr)
    for answer_error in errors:
        print(f"  - {answer_error}", file=sys.stderr)
    for port, service, port_error in unavailable:
        print(f"  - port {port} ({service}): {port_error.strerror}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
