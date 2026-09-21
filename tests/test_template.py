from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tasks.post_copy import dotenv_value
from tasks.post_copy import main as post_copy_main
from tasks.post_copy import parse_args as parse_post_copy_args
from tasks.post_copy import write_private_file
from tasks.preflight import main as preflight_main
from tasks.preflight import parse_args as parse_preflight_args
from tasks.preflight import unavailable_ports
from tasks.preflight import validate_answers


ROOT = Path(__file__).resolve().parents[1]
COPIER = os.environ.get("COPIER_BIN") or shutil.which("copier")
DOCKER = shutil.which("docker")


class AnswerValidationTests(unittest.TestCase):
    def test_valid_multilingual_answers(self) -> None:
        answers = argparse.Namespace(
            repo_name="example-project",
            languages="it,en,fr",
            default_language="it",
            use_translations="true",
        )
        self.assertEqual(validate_answers(answers), [])

    def test_invalid_answers_are_reported_together(self) -> None:
        answers = argparse.Namespace(
            repo_name="Bad_Name",
            languages="it,it,INVALID!",
            default_language="en",
            use_translations="true",
        )
        errors = validate_answers(answers)
        self.assertEqual(len(errors), 4)

    def test_translation_rules_are_ignored_when_disabled(self) -> None:
        answers = argparse.Namespace(
            repo_name="example-project",
            languages="invalid",
            default_language="missing",
            use_translations="false",
        )
        self.assertEqual(validate_answers(answers), [])


class PreflightTests(unittest.TestCase):
    def test_cli_arguments_are_parsed(self) -> None:
        arguments = [
            "preflight.py",
            "--repo-name",
            "example-project",
            "--languages",
            "it,en",
            "--default-language",
            "it",
            "--use-translations",
            "true",
        ]
        with mock.patch.object(sys, "argv", arguments):
            answers = parse_preflight_args()
        self.assertEqual(answers.repo_name, "example-project")
        self.assertEqual(answers.languages, "it,en")

    def test_available_ports_allow_generation(self) -> None:
        answers = argparse.Namespace(
            repo_name="example-project",
            languages="it,en",
            default_language="it",
            use_translations="true",
        )
        with (
            mock.patch("tasks.preflight.parse_args", return_value=answers),
            mock.patch("tasks.preflight.unavailable_ports", return_value=[]),
        ):
            preflight_main()

    def test_all_preflight_errors_are_printed(self) -> None:
        answers = argparse.Namespace(
            repo_name="Bad_Name",
            languages="it",
            default_language="en",
            use_translations="true",
        )
        port_error = OSError(98, "Address already in use")
        stderr = io.StringIO()
        with (
            mock.patch("tasks.preflight.parse_args", return_value=answers),
            mock.patch(
                "tasks.preflight.unavailable_ports",
                return_value=[(8000, "Django", port_error)],
            ),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit),
        ):
            preflight_main()
        output = stderr.getvalue()
        self.assertIn("repo_name must contain", output)
        self.assertIn("port 8000 (Django): Address already in use", output)

    def test_unavailable_port_is_reported(self) -> None:
        probe = mock.MagicMock()
        probe.__enter__.return_value.bind.side_effect = OSError(
            98,
            "Address already in use",
        )
        with (
            mock.patch("tasks.preflight.LOCAL_PORTS", {8000: "Django"}),
            mock.patch("tasks.preflight.socket.socket", return_value=probe),
        ):
            result = unavailable_ports()
        self.assertEqual(result[0][:2], (8000, "Django"))


class PostCopyTests(unittest.TestCase):
    def test_cli_arguments_are_parsed(self) -> None:
        arguments = [
            "post_copy.py",
            "--repo-name",
            "example-project",
            "--db-user",
            "database-user",
        ]
        with mock.patch.object(sys, "argv", arguments):
            answers = parse_post_copy_args()
        self.assertEqual(answers.repo_name, "example-project")
        self.assertEqual(answers.db_user, "database-user")

    def test_dotenv_values_are_escaped_and_reject_newlines(self) -> None:
        self.assertEqual(dotenv_value('a\\b"c'), '"a\\\\b\\"c"')
        for value in ("line one\nline two", "line one\rline two"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dotenv_value(value)

    def test_missing_application_directory_is_rejected(self) -> None:
        answers = argparse.Namespace(repo_name="missing", db_user="database-user")
        with tempfile.TemporaryDirectory() as temporary_directory:
            previous_directory = Path.cwd()
            try:
                os.chdir(temporary_directory)
                with (
                    mock.patch("tasks.post_copy.parse_args", return_value=answers),
                    self.assertRaises(FileNotFoundError),
                ):
                    post_copy_main()
            finally:
                os.chdir(previous_directory)

    def test_env_is_private_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "example-project").mkdir()
            previous_directory = Path.cwd()
            previous_argv = sys.argv
            try:
                os.chdir(root)
                sys.argv = [
                    "post_copy.py",
                    "--repo-name",
                    "example-project",
                    "--db-user",
                    "example-project",
                ]
                post_copy_main()
                env_path = root / "example-project" / ".env"
                self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)
                original = env_path.read_bytes()
                with self.assertRaises(FileExistsError):
                    post_copy_main()
                self.assertEqual(env_path.read_bytes(), original)
            finally:
                sys.argv = previous_argv
                os.chdir(previous_directory)

    def test_private_file_refuses_existing_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target"
            target.write_text("unchanged\n")
            link = root / ".env"
            link.symlink_to(target)

            with self.assertRaises(FileExistsError):
                write_private_file(link, "SECRET=unsafe\n")

            self.assertEqual(target.read_text(), "unchanged\n")


class DatabaseBackupScriptTests(unittest.TestCase):
    def run_backup(
        self,
        *,
        allow_missing_container: bool = False,
        container_exists: bool = True,
        container_running: bool = True,
        corrupt_remote: bool = False,
        create_monthly_backup: bool = False,
        omit_s3_secret: bool = False,
        s3_bucket: str = "default",
    ) -> tuple[
        subprocess.CompletedProcess[str],
        str,
        Path,
    ]:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = Path(temporary_directory.name)
        fake_bin = root / "bin"
        fake_remote = root / "remote"
        fake_bin.mkdir()
        fake_remote.mkdir()

        script = root / "backup_database.sh"
        script.write_text(
            (ROOT / "template/bin/backup_database.sh.jinja")
            .read_text()
            .replace("[%% raw %%]", "")
            .replace("[%% endraw %%]", "")
            .replace("[[ repo_name ]]", "backup-project")
        )
        script.chmod(0o755)

        docker = fake_bin / "docker"
        docker.write_text(
            """#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$1" == "container" && "$2" == "inspect" ]]; then
  if [[ "$FAKE_CONTAINER_EXISTS" != "1" ]]; then
    exit 1
  fi
  if [[ "${3:-}" == "--format" ]]; then
    printf '%s\\n' "$FAKE_CONTAINER_RUNNING"
  fi
  exit 0
fi
if [[ "$1" == "exec" ]]; then
  if [[ "$*" == *"pg_restore --list"* ]]; then
    cat >/dev/null
  else
    printf 'valid custom-format dump'
  fi
  exit 0
fi
exit 1
"""
        )
        docker.chmod(0o755)

        rclone = fake_bin / "rclone"
        rclone.write_text(
            """#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\\n' "$*" >> "$RCLONE_LOG"
case "$1 ${2:-}" in
  "config file")
    printf 'Configuration file is stored at:\\n%s\\n' "$RCLONE_CONFIG"
    ;;
  "config show")
    printf '[s3]\\ntype = s3\\n'
    ;;
  "listremotes ")
    [[ "$RCLONE_CONFIG_S3_TYPE" == "s3" ]]
    [[ "$RCLONE_CONFIG_S3_ACCESS_KEY_ID" == "test-access-key" ]]
    [[ "$RCLONE_CONFIG_S3_SECRET_ACCESS_KEY" == "test-secret-key" ]]
    [[ "$RCLONE_CONFIG_S3_ENDPOINT" == "https://s3.example.test" ]]
    printf 's3:\\n'
    ;;
  "copy "*)
    cp "$2" "$FAKE_REMOTE_DIR/$(basename "$2")"
    ;;
  "cat "*)
    name="${2##*/}"
    if [[ "${CORRUPT_REMOTE:-0}" == "1" && "$name" == *.dump.gz ]]; then
      printf 'corrupted remote data'
    else
      cat "$FAKE_REMOTE_DIR/$name"
    fi
    ;;
  "delete "*)
    ;;
  "lsf "*)
    find "$FAKE_REMOTE_DIR" -maxdepth 1 -type f \
      -name 'database_????-??.dump.gz' -printf '%f\\n' | sort -r
    ;;
  "deletefile "*)
    rm -f "$FAKE_REMOTE_DIR/${2##*/}"
    ;;
  *)
    exit 1
    ;;
esac
"""
        )
        rclone.chmod(0o755)

        rclone_log = root / "rclone.log"
        rclone_log.touch()
        environment = os.environ.copy()
        environment.update(
            {
                "ALLOW_MISSING_CONTAINER": (
                    "1" if allow_missing_container else "0"
                ),
                "APP_CONTAINER": "backup-project_production",
                "CORRUPT_REMOTE": "1" if corrupt_remote else "0",
                "CREATE_MONTHLY_BACKUP": (
                    "1" if create_monthly_backup else "0"
                ),
                "ENVIRONMENT": "production",
                "FAKE_CONTAINER_EXISTS": "1" if container_exists else "0",
                "FAKE_CONTAINER_RUNNING": "true" if container_running else "false",
                "FAKE_REMOTE_DIR": str(fake_remote),
                "HOME": str(root),
                "LOCAL_BACKUP_ROOT": str(root / "backups"),
                "PATH": f"{fake_bin}:{environment['PATH']}",
                "RCLONE_LOG": str(rclone_log),
                "S3_ACCESS_KEY_ID": "test-access-key",
                "S3_BUCKET": s3_bucket,
                "S3_ENDPOINT": "https://s3.example.test",
                "S3_SECRET_ACCESS_KEY": "test-secret-key",
            }
        )
        if omit_s3_secret:
            environment.pop("S3_SECRET_ACCESS_KEY")
        result = subprocess.run(
            ["bash", str(script)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        return result, rclone_log.read_text(), fake_remote

    def test_verified_backup_uses_copy_and_scoped_retention(self) -> None:
        result, rclone_log, fake_remote = self.run_backup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(rclone_log.count("copy "), 2)
        self.assertIn(
            "cat s3:default/backup-project/db/production/daily/",
            rclone_log,
        )
        self.assertIn(
            "delete s3:default/backup-project/db/production/daily",
            rclone_log,
        )
        self.assertNotIn("sync ", rclone_log)
        self.assertEqual(len(list(fake_remote.glob("*.dump.gz"))), 1)
        self.assertEqual(len(list(fake_remote.glob("*.sha256"))), 1)

    def test_monthly_backup_is_created_and_verified(self) -> None:
        result, rclone_log, fake_remote = self.run_backup(
            create_monthly_backup=True
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(rclone_log.count("copy "), 4)
        self.assertIn(
            "cat s3:default/backup-project/db/production/monthly/database_",
            rclone_log,
        )
        self.assertIn(
            "lsf s3:default/backup-project/db/production/monthly",
            rclone_log,
        )
        self.assertEqual(
            len(list(fake_remote.glob("database_????-??.dump.gz"))),
            1,
        )
        self.assertEqual(
            len(list(fake_remote.glob("database_????-??.dump.gz.sha256"))),
            1,
        )

    def test_corrupt_remote_fails_before_retention(self) -> None:
        result, rclone_log, _ = self.run_backup(corrupt_remote=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Remote backup checksum verification failed", result.stderr)
        self.assertNotIn("delete ", rclone_log)

    def test_initial_deploy_may_skip_a_missing_container(self) -> None:
        result, rclone_log, _ = self.run_backup(
            allow_missing_container=True,
            container_exists=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No previous deployment found", result.stdout)
        self.assertEqual(rclone_log, "")

    def test_stopped_existing_container_blocks_deploy(self) -> None:
        result, rclone_log, _ = self.run_backup(
            allow_missing_container=True,
            container_running=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Application container is not running", result.stderr)
        self.assertEqual(rclone_log, "")

    def test_missing_s3_secret_fails_before_rclone(self) -> None:
        result, rclone_log, _ = self.run_backup(omit_s3_secret=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("S3_SECRET_ACCESS_KEY is required", result.stderr)
        self.assertEqual(rclone_log, "")

    def test_swiss_backup_bucket_must_be_default(self) -> None:
        result, rclone_log, _ = self.run_backup(s3_bucket="another-bucket")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("S3_BUCKET must be default", result.stderr)
        self.assertEqual(rclone_log, "")


@unittest.skipUnless(COPIER, "Copier executable not found; set COPIER_BIN")
class RenderingTests(unittest.TestCase):
    def render(self, *data: str) -> Path:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        destination = Path(temporary_directory.name) / "project"
        command = [
            str(COPIER),
            "copy",
            "--trust",
            "--defaults",
            "--skip-tasks",
            "--quiet",
            "--vcs-ref=HEAD",
        ]
        for answer in data:
            command.extend(("--data", answer))
        command.extend((str(ROOT), str(destination)))
        subprocess.run(command, check=True)
        return destination

    def test_rendering_matrix(self) -> None:
        cases = (
            ("default", (), "my-new-project", False, True, False, ()),
            (
                "minimal",
                (
                    "project_name=Minimal Project",
                    "repo_name=minimal-project",
                    "use_sorl_thumbnail=false",
                ),
                "minimal-project",
                False,
                False,
                False,
                (),
            ),
            (
                "cabinet",
                (
                    "project_name=Cabinet Project",
                    "repo_name=cabinet-project",
                    "use_cabinet=true",
                ),
                "cabinet-project",
                True,
                True,
                False,
                (),
            ),
            (
                "multilingual",
                (
                    "project_name=Multilingual Project",
                    "repo_name=multilingual-project",
                    "use_translations=true",
                    "languages=[it,en]",
                    "default_language=it",
                ),
                "multilingual-project",
                False,
                True,
                True,
                ("it", "en"),
            ),
            (
                "full",
                (
                    "project_name=Full Project",
                    "repo_name=full-project",
                    "use_cabinet=true",
                    "use_sorl_thumbnail=true",
                    "use_translations=true",
                    "languages=[it,en,fr]",
                    "default_language=it",
                ),
                "full-project",
                True,
                True,
                True,
                ("it", "en", "fr"),
            ),
        )

        for name, data, repo_name, cabinet, sorl, translations, languages in cases:
            with self.subTest(name=name):
                destination = self.render(*data)
                app = destination / repo_name
                self.assertTrue((destination / ".copier-answers.yml").is_file())
                self.assertEqual((app / "cabinet").exists(), cabinet)
                for module in ("pages", "tagall", "core"):
                    self.assertEqual(
                        (app / module / "translation.py").exists(),
                        translations,
                    )
                self.assertEqual(
                    (app / "cabinet" / "translation.py").exists(),
                    cabinet and translations,
                )
                thumbnail_library = "sorl_thumbnail" if sorl else "sorl_fallback"
                self.assertIn(
                    "{% load " + thumbnail_library + " %}",
                    (app / "pages/templates/pages/grid/grid_item.html").read_text(),
                )
                requirements = (app / "requirements/common.txt").read_text()
                self.assertEqual("sorl-thumbnail==" in requirements, sorl)
                settings = (app / "core/settings/common.py").read_text()
                self.assertEqual(
                    "from django.utils.translation import gettext_lazy as _"
                    in settings,
                    cabinet,
                )
                if languages:
                    rendered_languages = "\n".join(
                        f'    "{language}",' for language in languages
                    )
                    self.assertIn(rendered_languages, settings)
                self.assert_no_compiled_artifacts(destination)
                self.assert_python_syntax(app)
                self.assert_shell_scripts(destination)
                self.assert_compose_config(destination, app)
                self.assert_requirements_are_pinned(app)
                self.assert_no_generator_markers(destination)
                backup_workflow = (
                    destination / ".github/workflows/backup_daily.yml"
                ).read_text()
                self.assertIn(
                    "bash bin/backup_database.sh",
                    backup_workflow,
                )
                self.assertIn(
                    f"group: database-{repo_name}-${{{{ matrix.environment }}}}",
                    backup_workflow,
                )
                self.assertIn(
                    "environment:\n          - staging\n          - production",
                    backup_workflow,
                )
                self.assertIn(
                    "APP_CONTAINER: "
                    f"{repo_name}_${{{{ matrix.environment }}}}",
                    backup_workflow,
                )

    def test_text_answers_are_safely_serialized(self) -> None:
        destination = self.render(
            "project_name=Client's Site",
            "project_description=Research & development",
            "repo_name=client-site",
        )
        app = destination / "client-site"

        self.assert_python_syntax(app)
        settings = (app / "core/settings/common.py").read_text()
        self.assertIn('name = "Client\\u0027s Site"', settings)
        home = (app / "core/templates/home.html").read_text()
        self.assertIn("Client&#39;s Site", home)
        self.assertIn("Research &amp; development", home)

    def test_copier_validators_report_errors_without_template_syntax_failures(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "project"
            result = subprocess.run(
                [
                    str(COPIER),
                    "copy",
                    "--trust",
                    "--defaults",
                    "--skip-tasks",
                    "--quiet",
                    "--vcs-ref=HEAD",
                    "--data",
                    "use_translations=true",
                    "--data",
                    "languages=[it,it]",
                    "--data",
                    "default_language=it",
                    str(ROOT),
                    str(destination),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Validation error for question 'languages'", output)
        self.assertNotIn("unexpected '%'", output)

    def test_update_preserves_project_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            template_repository = self.create_template_repository(temporary_root)
            destination = temporary_root / "project"
            self.copy_from_repository(template_repository, destination)
            self.initialize_project_repository(destination)
            generated_readme = destination / "README.md"
            generated_readme.write_text(
                generated_readme.read_text() + "\nLocal project note.\n"
            )
            self.git(destination, "add", "README.md")
            self.git(destination, "commit", "-qm", "Customize project")

            self.add_template_version(
                template_repository,
                "v1.1.0",
                "updated template\n",
            )
            self.update_project(destination)
            self.assertEqual(
                (destination / "copier-update-probe.txt").read_text(),
                "updated template\n",
            )
            self.assertIn("Local project note.", generated_readme.read_text())
            answers = (destination / ".copier-answers.yml").read_text()
            self.assertIn("_commit: v1.1.0", answers)

    def test_update_toggles_optional_features_without_touching_env(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            template_repository = self.create_template_repository(temporary_root)
            destination = temporary_root / "project"
            self.copy_from_repository(
                template_repository,
                destination,
                "project_name=Update Project",
                "repo_name=update-project",
                "use_cabinet=false",
                "use_sorl_thumbnail=true",
                "use_translations=false",
            )
            self.initialize_project_repository(destination)

            app = destination / "update-project"
            env_path = app / ".env"
            env_path.write_text("LOCAL_SECRET=unchanged\n")
            env_path.chmod(0o600)
            original_env = env_path.read_bytes()

            self.add_template_version(template_repository, "v1.1.0", "features on\n")
            self.update_project(
                destination,
                "use_cabinet=true",
                "use_sorl_thumbnail=false",
                "use_translations=true",
                "languages=[it,en]",
                "default_language=it",
            )
            self.assert_optional_features(
                app,
                cabinet=True,
                sorl=False,
                translations=True,
            )
            self.assert_env_unchanged(env_path, original_env)

            self.git(destination, "add", ".")
            self.git(destination, "commit", "-qm", "Enable optional features")
            self.add_template_version(template_repository, "v1.2.0", "features off\n")
            self.update_project(
                destination,
                "use_cabinet=false",
                "use_sorl_thumbnail=true",
                "use_translations=false",
            )
            self.assert_optional_features(
                app,
                cabinet=False,
                sorl=True,
                translations=False,
            )
            self.assert_env_unchanged(env_path, original_env)
            answers = (destination / ".copier-answers.yml").read_text()
            self.assertIn("_commit: v1.2.0", answers)

    def test_update_from_previous_real_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            template_repository = temporary_root / "template-history"
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--no-hardlinks",
                    str(ROOT),
                    str(template_repository),
                ],
                check=True,
            )
            if (
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(template_repository),
                        "rev-parse",
                        "--verify",
                        "v1.0.5",
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                != 0
            ):
                self.skipTest("The previous release tag v1.0.5 is unavailable")

            # Build the synthetic release from the actual previous release.
            # Cloning ROOT checks out the current commit, so copying ROOT over
            # it would otherwise be a no-op in a clean checkout (as in CI).
            self.git(template_repository, "checkout", "-q", "v1.0.5")
            shutil.copytree(
                ROOT,
                template_repository,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".parity",
                    "__pycache__",
                    "*.pyc",
                ),
            )
            self.git(template_repository, "config", "user.name", "Template Test")
            self.git(
                template_repository,
                "config",
                "user.email",
                "template-test@example.com",
            )
            self.git(template_repository, "add", "-A")
            self.git(
                template_repository,
                "commit",
                "-qm",
                "Template version under test",
            )
            self.git(template_repository, "tag", "v1.0.6")

            destination = temporary_root / "project"
            self.copy_from_repository(
                template_repository,
                destination,
                "project_name=Upgrade Project",
                "repo_name=upgrade-project",
                "use_translations=true",
                "languages=[it,en]",
                "default_language=it",
                vcs_ref="v1.0.5",
            )
            self.initialize_project_repository(destination)
            readme = destination / "README.md"
            readme.write_text(readme.read_text() + "\nLocal upgrade note.\n")
            self.git(destination, "add", "README.md")
            self.git(destination, "commit", "-qm", "Customize generated project")

            self.update_project(destination)

            app = destination / "upgrade-project"
            self.assertIn("Local upgrade note.", readme.read_text())
            self.assertIn("django==6.0.7", (app / "requirements/common.txt").read_text())
            self.assertIn(
                "POSTGRES_SEARCH_CONFIGS",
                (app / "search_app/views.py").read_text(),
            )
            self.assert_python_syntax(app)
            answers = (destination / ".copier-answers.yml").read_text()
            self.assertIn("_commit: v1.0.6", answers)

    def create_template_repository(self, temporary_root: Path) -> Path:
        template_repository = temporary_root / "template-repository"
        shutil.copytree(
            ROOT,
            template_repository,
            ignore=shutil.ignore_patterns(
                ".git",
                ".parity",
                "__pycache__",
                "*.pyc",
            ),
        )
        self.git(template_repository, "init", "-q")
        self.git(template_repository, "config", "user.name", "Template Test")
        self.git(
            template_repository,
            "config",
            "user.email",
            "template-test@example.com",
        )
        self.git(template_repository, "add", ".")
        self.git(template_repository, "commit", "-qm", "Template v1")
        self.git(template_repository, "tag", "v1.0.0")
        return template_repository

    def copy_from_repository(
        self,
        template_repository: Path,
        destination: Path,
        *data: str,
        vcs_ref: str | None = None,
    ) -> None:
        command = [
            str(COPIER),
            "copy",
            "--trust",
            "--defaults",
            "--skip-tasks",
            "--quiet",
        ]
        if vcs_ref is not None:
            command.extend(("--vcs-ref", vcs_ref))
        for answer in data:
            command.extend(("--data", answer))
        command.extend((str(template_repository), str(destination)))
        subprocess.run(command, check=True)

    def initialize_project_repository(self, destination: Path) -> None:
        self.git(destination, "init", "-q")
        self.git(destination, "config", "user.name", "Project Test")
        self.git(
            destination,
            "config",
            "user.email",
            "project-test@example.com",
        )
        self.git(destination, "add", ".")
        self.git(destination, "commit", "-qm", "Generated project")

    def add_template_version(
        self,
        template_repository: Path,
        version: str,
        content: str,
    ) -> None:
        probe = template_repository / "template" / "copier-update-probe.txt"
        probe.write_text(content)
        self.git(template_repository, "add", ".")
        self.git(template_repository, "commit", "-qm", f"Template {version}")
        self.git(template_repository, "tag", version)

    def update_project(self, destination: Path, *data: str) -> None:
        command = [
            str(COPIER),
            "update",
            "--trust",
            "--defaults",
            "--skip-tasks",
            "--quiet",
        ]
        for answer in data:
            command.extend(("--data", answer))
        command.append(str(destination))
        subprocess.run(command, check=True)

    def assert_optional_features(
        self,
        app: Path,
        *,
        cabinet: bool,
        sorl: bool,
        translations: bool,
    ) -> None:
        self.assertEqual((app / "cabinet").exists(), cabinet)
        for module in ("pages", "tagall", "core"):
            self.assertEqual(
                (app / module / "translation.py").exists(),
                translations,
            )
        self.assertEqual(
            (app / "cabinet" / "translation.py").exists(),
            cabinet and translations,
        )
        grid_item = (app / "pages/templates/pages/grid/grid_item.html").read_text()
        thumbnail_library = "sorl_thumbnail" if sorl else "sorl_fallback"
        self.assertIn("{% load " + thumbnail_library + " %}", grid_item)
        requirements = (app / "requirements/common.txt").read_text()
        self.assertEqual("sorl-thumbnail==" in requirements, sorl)

    def assert_env_unchanged(self, env_path: Path, original: bytes) -> None:
        self.assertEqual(env_path.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)

    def assert_requirements_are_pinned(self, app: Path) -> None:
        requirement_pattern = re.compile(
            r"^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9._+-]*"
            r"(?:\s+--hash=sha256:[0-9a-f]{64})+$"
        )
        for requirements_file in (app / "requirements").glob("*.txt"):
            contents = requirements_file.read_text()
            self.assertIn("--require-hashes", contents, requirements_file)
            logical_lines = contents.replace("\\\n", " ").splitlines()
            for raw_line in logical_lines:
                line = raw_line.strip()
                if not line or line.startswith(("#", "-r ", "--require-hashes")):
                    continue
                self.assertRegex(line, requirement_pattern, requirements_file)

    def assert_python_syntax(self, app: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(app)],
            check=False,
        )
        self.assertEqual(result.returncode, 0)

    def assert_shell_scripts(self, destination: Path) -> None:
        backup_script = destination / "bin/backup_database.sh"
        self.assertTrue(backup_script.is_file())
        self.assertTrue(backup_script.stat().st_mode & stat.S_IXUSR)
        for script in destination.rglob("*.sh"):
            result = subprocess.run(
                ["bash", "-n", str(script)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def assert_no_compiled_artifacts(self, destination: Path) -> None:
        for path in destination.rglob("*"):
            self.assertNotEqual(path.name, "__pycache__", path)
            self.assertNotEqual(path.suffix, ".pyc", path)

    def assert_compose_config(self, destination: Path, app: Path) -> None:
        if DOCKER is None:
            return
        env_path = app / ".env"
        env_path.write_text("TEMPLATE_TEST=true\n")
        try:
            subprocess.run(
                [DOCKER, "compose", "config", "--quiet"],
                cwd=destination,
                check=True,
            )
        finally:
            env_path.unlink()

    def assert_no_generator_markers(self, destination: Path) -> None:
        for path in destination.rglob("*"):
            if not path.is_file() or path.suffix in {".mo", ".png", ".woff2"}:
                continue
            try:
                content = path.read_text()
            except UnicodeDecodeError:
                continue
            self.assertNotIn("[%%", content, path)
            self.assertIsNone(
                re.search(
                    r"\[\[[ \t]*(?:"
                    r"_copier|project_name|project_description|repo_name|"
                    r"use_cabinet|use_sorl_thumbnail|use_translations|languages|"
                    r"default_language|timezone|author|email|db_user"
                    r")\b",
                    content,
                ),
                path,
            )

    def git(self, repository: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
