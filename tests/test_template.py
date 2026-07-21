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
COOKIECUTTER = shutil.which("cookiecutter")
COOKIECUTTER_TEMPLATE = Path(
    os.environ.get(
        "COOKIECUTTER_TEMPLATE",
        str(ROOT.parent / "django-cookiecutter"),
    )
)
DOCKER = shutil.which("docker")
RUN_COOKIECUTTER_PARITY = os.environ.get("RUN_COOKIECUTTER_PARITY") == "1"


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
            self.assertNotIn("cookiecutter.", content, path)
            self.assertNotIn("[%%", content, path)

    def git(self, repository: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
        )


@unittest.skipUnless(
    RUN_COOKIECUTTER_PARITY
    and COPIER
    and COOKIECUTTER
    and COOKIECUTTER_TEMPLATE.is_dir(),
    "set RUN_COOKIECUTTER_PARITY=1 with both template engines available",
)
class CookiecutterParityTests(unittest.TestCase):
    def test_rendered_projects_are_equivalent(self) -> None:
        cases = (
            ("default", "My New Project", "my-new-project", False, True, False, ()),
            ("minimal", "Minimal Project", "minimal-project", False, False, False, ()),
            ("cabinet", "Cabinet Project", "cabinet-project", True, True, False, ()),
            (
                "multilingual",
                "Multilingual Project",
                "multilingual-project",
                False,
                True,
                True,
                ("it", "en"),
            ),
            (
                "full",
                "Full Project",
                "full-project",
                True,
                True,
                True,
                ("it", "en", "fr"),
            ),
        )

        for name, project_name, repo_name, cabinet, sorl, translations, languages in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                cookie_project, cookie_output = self.render_cookiecutter(
                    root,
                    project_name,
                    repo_name,
                    cabinet,
                    sorl,
                    translations,
                    languages,
                )
                copier_project, copier_output = self.render_copier(
                    root,
                    project_name,
                    repo_name,
                    cabinet,
                    sorl,
                    translations,
                    languages,
                )
                self.assert_project_files_equal(cookie_project, copier_project)
                self.assert_readmes_equivalent(cookie_project, copier_project)
                self.assert_env_equivalent(
                    cookie_project / repo_name / ".env",
                    copier_project / repo_name / ".env",
                    cookie_output + copier_output,
                )

    def render_cookiecutter(
        self,
        root: Path,
        project_name: str,
        repo_name: str,
        cabinet: bool,
        sorl: bool,
        translations: bool,
        languages: tuple[str, ...],
    ) -> tuple[Path, str]:
        output = root / "cookiecutter-output"
        replay = root / "cookiecutter-replay"
        cache = root / "cookiecutter-cache"
        output.mkdir()
        replay.mkdir()
        cache.mkdir()
        config = root / "cookiecutter-config.yml"
        config.write_text(
            f"cookiecutters_dir: {cache}\nreplay_dir: {replay}\n",
            encoding="utf-8",
        )
        language_csv = ",".join(languages) if languages else "it,en"
        result = subprocess.run(
            [
                str(COOKIECUTTER),
                "--no-input",
                "--config-file",
                str(config),
                "--output-dir",
                str(output),
                str(COOKIECUTTER_TEMPLATE),
                f"project_name={project_name}",
                f"repo_name={repo_name}",
                f"use_cabinet={'y' if cabinet else 'n'}",
                f"use_sorl_thumbnail={'y' if sorl else 'n'}",
                f"use_translations={'y' if translations else 'n'}",
                f"languages={language_csv}",
                "default_language=it",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return output / repo_name, result.stdout + result.stderr

    def render_copier(
        self,
        root: Path,
        project_name: str,
        repo_name: str,
        cabinet: bool,
        sorl: bool,
        translations: bool,
        languages: tuple[str, ...],
    ) -> tuple[Path, str]:
        output = root / "copier-output"
        language_yaml = "[" + ",".join(languages or ("it", "en")) + "]"
        result = subprocess.run(
            [
                str(COPIER),
                "copy",
                "--trust",
                "--defaults",
                "--quiet",
                "--vcs-ref=HEAD",
                "--data",
                f"project_name={project_name}",
                "--data",
                f"repo_name={repo_name}",
                "--data",
                f"use_cabinet={str(cabinet).lower()}",
                "--data",
                f"use_sorl_thumbnail={str(sorl).lower()}",
                "--data",
                f"use_translations={str(translations).lower()}",
                "--data",
                f"languages={language_yaml}",
                "--data",
                "default_language=it",
                str(ROOT),
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return output, result.stdout + result.stderr

    def assert_project_files_equal(self, cookie: Path, copier: Path) -> None:
        cookie_files = self.comparable_files(cookie)
        copier_files = self.comparable_files(copier)
        self.assertEqual(cookie_files, copier_files)
        for relative_path in cookie_files:
            self.assertEqual(
                (cookie / relative_path).read_bytes(),
                (copier / relative_path).read_bytes(),
                relative_path,
            )

    def comparable_files(self, root: Path) -> set[Path]:
        ignored_names = {".copier-answers.yml", ".env", "README.md"}
        return {
            path.relative_to(root)
            for path in root.rglob("*")
            if path.is_file()
            and path.name not in ignored_names
            and path.suffix != ".pyc"
            and "__pycache__" not in path.parts
        }

    def assert_readmes_equivalent(self, cookie: Path, copier: Path) -> None:
        cookie_readme = (cookie / "README.md").read_text()
        copier_lines = (copier / "README.md").read_text().splitlines(keepends=True)
        copier_readme = "".join(
            line for line in copier_lines if "Made%20with-Copier" not in line
        ).replace("Copier generation", "Cookiecutter generation")
        self.assertEqual(cookie_readme, copier_readme)

    def assert_env_equivalent(
        self,
        cookie_env: Path,
        copier_env: Path,
        command_output: str,
    ) -> None:
        cookie_values = self.env_values(cookie_env)
        copier_values = self.env_values(copier_env)
        self.assertEqual(cookie_values.keys(), copier_values.keys())
        self.assertEqual(stat.S_IMODE(cookie_env.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(copier_env.stat().st_mode), 0o600)
        for name in ("SECRET_KEY", "DB_PASSWORD", "POSTGRES_PASSWORD"):
            self.assertNotIn(cookie_values[name][1:-1], command_output)
            self.assertNotIn(copier_values[name][1:-1], command_output)

    def env_values(self, env_path: Path) -> dict[str, str]:
        values = dict(
            line.split("=", 1)
            for line in env_path.read_text(encoding="utf-8").splitlines()
        )
        for value in values.values():
            self.assertTrue(value.startswith('"') and value.endswith('"'))
        return values


if __name__ == "__main__":
    unittest.main()
