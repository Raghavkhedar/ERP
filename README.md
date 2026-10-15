# Senken ERP

The Senken ERP, starting with the **Empanelment** module: tracking candidates from
sourcing through hiring, onboarding and offboarding. It replaces the Zoho Creator app.

**Stack:** Django 5.2, PostgreSQL 16 (run in Docker), Python 3.12 managed by `uv`,
Tailwind CSS, htmx and Alpine.js (no Node or JavaScript build step).

**Why it is set up this way**
- PostgreSQL runs in Docker so everyone, and production, uses the same database version.
- `uv` pins Python and every package version in `uv.lock`, so the project runs the same on every machine.
- Settings and secrets come from a `.env` file that is never committed to git.
- Tailwind is built by its standalone CLI, and htmx and Alpine are stored in the repo at pinned versions, so there is no Node toolchain to maintain.
- GitHub Actions runs the checks and tests on every pull request.

## Requirements

- [Docker](https://docs.docker.com/engine/install/) with the Compose plugin
- [uv](https://docs.astral.sh/uv/)
- Git
- Linux x86-64 (the Tailwind install script downloads the Linux binary)

## First-time setup

Run these from the project folder, in order.

| Step | Command | What it does |
| --- | --- | --- |
| 1 | `cp .env.example .env` | Creates your private settings file. It is ignored by git. |
| 2 | Edit `.env` | Fill in the values (see **Filling in `.env`** below). |
| 3 | `docker compose up -d` | Starts PostgreSQL 16 in a container, in the background. |
| 4 | `uv sync` | Installs the pinned Python version and packages from `uv.lock`. |
| 5 | `./scripts/install-tailwind.sh` | Downloads the pinned Tailwind CLI into `bin/` (not committed). |
| 6 | `bin/tailwindcss -i static/css/input.css -o static/css/app.css` | Builds the site's CSS. The pages are unstyled without this. |
| 7 | `uv run python manage.py migrate` | Creates the database tables. |
| 8 | `uv run python manage.py createsuperuser` | Creates your admin login. |
| 9 | `uv run python manage.py runserver` | Starts the app. Open http://127.0.0.1:8000/ and log in. |

Fill in `.env` (step 2) **before** starting the database (step 3). The database
password is fixed at the moment the database is first created.

### Filling in `.env`

| Variable | What to put |
| --- | --- |
| `DEBUG` | `True` for local development |
| `SECRET_KEY` | A generated key. Create one with the command below. |
| `DB_PASSWORD` | A password for the database. Letters and digits only. |
| `DATABASE_URL` | `postgres://senken_erp:PASSWORD@localhost:5432/senken_erp` |

Generate a secret key:

    uv run python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"

Generate a database password:

    tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24; echo

> **Important: the database password appears twice.**
> The same password must be written in **both** `DB_PASSWORD` and inside
> `DATABASE_URL` (where `PASSWORD` is in the example above). If they differ,
> Django cannot log in to the database.
> Do not leave angle brackets, quotes or spaces in the values.
>
> Before starting the database, run `grep -n "change-me" .env`. It should print
> nothing. If it prints a line, that placeholder has not been replaced yet.

## Everyday commands

| Task | Command |
| --- | --- |
| Start the database | `docker compose up -d` |
| Stop the database (keeps data) | `docker compose stop` |
| Check the database is healthy | `docker compose ps` |
| Open a SQL shell | `docker compose exec db psql -U senken_erp` |
| Run the app | `uv run python manage.py runserver` |
| Rebuild the CSS once | `bin/tailwindcss -i static/css/input.css -o static/css/app.css` |
| Rebuild the CSS automatically while editing | the same command with `--watch` added (needs its own terminal) |
| Run the tests | `uv run pytest` |
| Check the project for problems | `uv run python manage.py check` |
| Create migrations after changing a model | `uv run python manage.py makemigrations` |
| Apply migrations | `uv run python manage.py migrate` |

While developing templates, keep **two terminals** open: one running
`runserver` and one running the Tailwind build with `--watch`.

Only one copy of this project can run its database at a time (the container name
and port are fixed). If you have another copy running, stop it first with
`docker compose stop`.

## Frontend

There is no Node or JavaScript build step.

- **Tailwind CSS** is built by the standalone CLI. `scripts/install-tailwind.sh`
  installs a pinned version into `bin/`. `static/css/input.css` is the source and
  `static/css/app.css` is generated, so it is not committed. Tailwind only
  generates the classes it finds in `templates/`, so rebuild after adding new classes.
- **htmx** and **Alpine.js** are stored in `static/vendor/` at pinned versions
  (listed in `static/vendor/VERSIONS.md`). To update one, download the new file,
  replace it, update `VERSIONS.md`, and test in the browser.

## Working on the code

`production` is the live branch and is **protected**: you cannot push to it
directly. A fresh clone starts on `production`, so create your own branch before
changing anything:

    git switch production
    git pull
    git switch -c feature/short-description

Then:

1. Make small commits with clear messages.
2. Push the branch: `git push -u origin feature/short-description`
3. Open a pull request into `production`.
4. Wait for the CI check (`test`) to pass, then merge.
5. Tidy up:

        git switch production
        git pull
        git branch -d feature/short-description

Always run `git pull` on `production` before creating a new branch, so you build
on the latest code.

Branch names: `feature/...` for new work, `fix/...` for bug fixes.

## Continuous integration

On every pull request into `production`, GitHub Actions starts a PostgreSQL 16
service and runs:

1. `manage.py check`, which catches broken settings or models
2. `manage.py makemigrations --check --dry-run`, which fails if a model change has no migration
3. `pytest`, which runs the tests against a real database

If you change a model, commit its migration file too. CI does not build the CSS;
the tests do not need it.

## Project layout

| Path | Purpose |
| --- | --- |
| `config/` | Project settings and URL configuration |
| `core/` | Shared code, including the custom `User` model, the home view and the tests |
| `templates/` | Shared HTML templates (`base.html`, login, home) |
| `static/css/` | `input.css` (Tailwind source); `app.css` is generated |
| `static/vendor/` | Pinned htmx and Alpine.js, with `VERSIONS.md` |
| `scripts/` | Helper scripts, such as the Tailwind installer |
| `compose.yaml` | PostgreSQL 16 for local development |
| `.env.example` | Template for your private `.env` file |
| `pyproject.toml`, `uv.lock` | Dependencies and their pinned versions |
| `.github/workflows/ci.yml` | The CI pipeline |

## Troubleshooting

**`password authentication failed for user "senken_erp"`**
The database was created with a different password from the one Django is
sending. Check that `DB_PASSWORD` and the password inside `DATABASE_URL` are
identical. If the database holds nothing you need, recreate it:

    docker compose down -v
    docker compose up -d

`down -v` deletes the database volume, so it **destroys all data** in it.

**`Connection refused` on port 5432**
The database container is not running. Start it with `docker compose up -d` and
wait until `docker compose ps` shows `healthy`.

**`permission denied ... /var/run/docker.sock`**
Your user is not in the `docker` group, or the terminal has not picked up the
change yet. Run `sudo usermod -aG docker $USER`, then log out and back in
(or use `newgrp docker` in the current terminal).

**`Cannot connect to the Docker daemon`**
The Docker service is not running: `sudo systemctl start docker`.

**`ImproperlyConfigured: Set the SECRET_KEY environment variable`**
`.env` is missing, is not in the project root, or has no `SECRET_KEY` line.

**The database container name is already in use**
Another copy of this project has a container running. Stop it with
`docker compose stop` from that copy's folder.

**The pages load but have no styling**
`static/css/app.css` is missing or out of date. Run the Tailwind build command
from the first-time setup (step 6). If a new class has no effect, rebuild.

**Tests or CI fail on a missing migration**
Run `uv run python manage.py makemigrations`, then commit the new migration file.
