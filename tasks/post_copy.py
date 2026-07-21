#!/usr/bin/env python3
"""Create the ignored local environment file after the first Copier copy."""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--db-user", required=True)
    return parser.parse_args()


def dotenv_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("Environment values must not contain newlines")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    args = parse_args()
    env_path = Path.cwd() / args.repo_name / ".env"
    if env_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {env_path}")
    if not env_path.parent.is_dir():
        raise FileNotFoundError(f"Application directory not found: {env_path.parent}")

    db_password = secrets.token_urlsafe(32)
    values = {
        "DJANGO_SETTINGS_MODULE": "core.settings.local",
        "SECRET_KEY": secrets.token_urlsafe(50),
        "DB_NAME": f"db{args.repo_name}",
        "DB_HOST": "db",
        "DB_PORT": "5432",
        "DB_USER": args.db_user,
        "DB_PASSWORD": db_password,
        "POSTGRES_DB": f"db{args.repo_name}",
        "POSTGRES_USER": args.db_user,
        "POSTGRES_PASSWORD": db_password,
        "PYTHONUNBUFFERED": "true",
        "LC_ALL": "en_US.UTF-8",
    }
    content = "".join(
        f"{name}={dotenv_value(str(value))}\n" for name, value in values.items()
    )
    env_path.write_text(content, encoding="utf-8")
    env_path.chmod(0o600)
    print("\nProject generated without building images or starting services.")
    print("Run `make bootstrap` from the project root when ready.")


if __name__ == "__main__":
    main()
