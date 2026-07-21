from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tasks.post_copy import main as post_copy_main
from tasks.preflight import validate_answers


ROOT = Path(__file__).resolve().parents[1]
COPIER = os.environ.get("COPIER_BIN") or shutil.which("copier")


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


class PostCopyTests(unittest.TestCase):
    def test_env_is_private_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "example-project").mkdir()
            previous_directory = Path.cwd()
            previous_argv = os.sys.argv
            try:
                os.chdir(root)
                os.sys.argv = [
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
                os.sys.argv = previous_argv
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
        ]
        for answer in data:
            command.extend(("--data", answer))
        command.extend((str(ROOT), str(destination)))
        subprocess.run(command, check=True)
        return destination

    def test_default_render(self) -> None:
        destination = self.render()
        app = destination / "my-new-project"
        self.assertTrue((destination / ".copier-answers.yml").is_file())
        self.assertFalse((app / "cabinet").exists())
        self.assertFalse((app / "pages" / "translation.py").exists())
        self.assertIn(
            "{% load sorl_thumbnail %}",
            (app / "pages/templates/pages/grid/grid_item.html").read_text(),
        )
        self.assert_python_syntax(app)
        self.assert_no_generator_markers(destination)

    def test_full_multilingual_render(self) -> None:
        destination = self.render(
            "project_name=Full Project",
            "repo_name=full-project",
            "use_cabinet=true",
            "use_sorl_thumbnail=false",
            "use_translations=true",
            "languages=[it,en,fr]",
            "default_language=it",
        )
        app = destination / "full-project"
        self.assertTrue((app / "cabinet" / "admin.py").is_file())
        for module in ("pages", "cabinet", "tagall", "core"):
            self.assertTrue((app / module / "translation.py").is_file())
        settings = (app / "core/settings/common.py").read_text()
        self.assertIn('"it",\n    "en",\n    "fr",', settings)
        self.assertIn(
            "{% load sorl_fallback %}",
            (app / "pages/templates/pages/grid/grid_item.html").read_text(),
        )
        self.assert_python_syntax(app)
        self.assert_no_generator_markers(destination)

    def test_update_preserves_project_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            template_repository = temporary_root / "template-repository"
            destination = temporary_root / "project"
            shutil.copytree(
                ROOT,
                template_repository,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
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

            subprocess.run(
                [
                    str(COPIER),
                    "copy",
                    "--trust",
                    "--defaults",
                    "--skip-tasks",
                    "--quiet",
                    str(template_repository),
                    str(destination),
                ],
                check=True,
            )
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
            generated_readme = destination / "README.md"
            generated_readme.write_text(
                generated_readme.read_text() + "\nLocal project note.\n"
            )
            self.git(destination, "add", "README.md")
            self.git(destination, "commit", "-qm", "Customize project")

            probe = template_repository / "template" / "copier-update-probe.txt"
            probe.write_text("updated template\n")
            self.git(template_repository, "add", ".")
            self.git(template_repository, "commit", "-qm", "Template v2")
            self.git(template_repository, "tag", "v1.1.0")
            subprocess.run(
                [
                    str(COPIER),
                    "update",
                    "--trust",
                    "--defaults",
                    "--skip-tasks",
                    "--quiet",
                    str(destination),
                ],
                check=True,
            )
            self.assertEqual(
                (destination / "copier-update-probe.txt").read_text(),
                "updated template\n",
            )
            self.assertIn("Local project note.", generated_readme.read_text())
            answers = (destination / ".copier-answers.yml").read_text()
            self.assertIn("_commit: v1.1.0", answers)

    def assert_python_syntax(self, app: Path) -> None:
        result = subprocess.run(
            [os.sys.executable, "-m", "compileall", "-q", str(app)],
            check=False,
        )
        self.assertEqual(result.returncode, 0)

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


if __name__ == "__main__":
    unittest.main()
