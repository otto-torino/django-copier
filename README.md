# Django Copier

A Copier template for a Docker-based Django project, with a ready-to-use local
environment and automated staging and production deployments through GitHub
Actions.

## Requirements

- [Copier](https://copier.readthedocs.io/)
- Git
- Docker Engine and the Docker Compose plugin (to run a generated project)

Install Copier in an isolated environment:

```bash
pipx install copier
```

## Create a project

From a local checkout, including uncommitted template changes:

```bash
copier copy --trust --vcs-ref HEAD . ../my-project
```

From the published repository:

```bash
copier copy --trust <TEMPLATE_URL> my-project
```

`--trust` is required because the template runs reviewed Python tasks. They
validate the local development ports and create an ignored
`<repo_name>/.env`, with random secrets and mode `0600`. Generation does not
build images, access application services or start containers. Run
`make bootstrap` inside the generated project when ready.

The questionnaire controls the project name and description, repository slug,
PostgreSQL user, timezone, author, email, the optional cabinet and
sorl-thumbnail integrations, and multilingual support.

## Update a generated project

Generated projects track their answers in `.copier-answers.yml`. Commit local
work first, then run:

```bash
git status --short
copier update --trust
```

Review any conflict markers before committing the update. The ignored `.env`
is not recreated or overwritten during updates.

## Development

The rendered project lives under `template/`; `copier.yml` defines questions,
delimiters, exclusions and tasks. Copier uses `[[ ... ]]` for values and the
more specific `[%% ... %%]` for control blocks so Django's `{% ... %}` and
`{{ ... }}` syntax remains untouched.

Run the test suite with an explicit Copier executable if it is not on `PATH`:

```bash
COPIER_BIN="$HOME/.local/bin/copier" python -m unittest -v
```

See `doc.md` for the conversion rationale and the release checklist.

