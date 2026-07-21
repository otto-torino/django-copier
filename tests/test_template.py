from __future__ import annotations

import argparse
import contextlib
import io
import os
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
                if languages:
                    settings = (app / "core/settings/common.py").read_text()
                    rendered_languages = "\n".join(
                        f'    "{language}",' for language in languages
                    )
                    self.assertIn(rendered_languages, settings)
                self.assert_no_compiled_artifacts(destination)
                self.assert_python_syntax(app)
                self.assert_compose_config(destination, app)
                self.assert_no_generator_markers(destination)

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
    ) -> None:
        command = [
            str(COPIER),
            "copy",
            "--trust",
            "--defaults",
            "--skip-tasks",
            "--quiet",
        ]
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

    def assert_python_syntax(self, app: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(app)],
            check=False,
        )
        self.assertEqual(result.returncode, 0)

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

    def git(self, repository: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
