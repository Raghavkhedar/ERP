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
| `DB_PASSWORD` | A password for the database. Generate oe with the command below. |

Generate a secret key:

    uv run python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"

Generate a database password:

    tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24; echo

> **Note: the database password is set once.**
> Write it only in `DB_PASSWORD`. Docker uses it to create the database and
> Django uses it to log in, so there is nothing else to keep in sync. Do not
> leave angle brackets, quotes or spaces in the values.
>
> The password is fixed when the database is first created, so choose it before
> starting the database. Changing it later means recreating the database with
> `docker compose down -v`, which deletes all its data.
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

## Code style and pre-commit hooks

Code is linted and formatted with [Ruff](https://docs.astral.sh/ruff/), and
`.editorconfig` sets the basics (indentation, final newline) for editors.
Ruff's settings live in `pyproject.toml`.

Run this **once after cloning**. Git does not share hooks, so each clone needs it:

    uv run pre-commit install

From then on, every `git commit` automatically fixes trailing whitespace and
missing final newlines, checks YAML and TOML syntax, and runs Ruff on the
Python files. If a hook changes a file, the commit is **refused**: run
`git add` on the changed files and commit again. Nothing is committed on a failure.

| Task | Command |
| --- | --- |
| Run all hooks on every file | `uv run pre-commit run --all-files` |
| Lint | `uv run ruff check .` |
| Lint and apply the safe fixes | `uv run ruff check --fix .` |
| Format | `uv run ruff format .` |
| Check formatting without changing files | `uv run ruff format --check .` |

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

1. `ruff check`, which catches lint errors such as unused imports
2. `ruff format --check`, which fails if code is not formatted
3. `manage.py check`, which catches broken settings or models
4. `manage.py makemigrations --check --dry-run`, which fails if a model change has no migration
5. `pytest`, which runs the tests against a real database

If you change a model, commit its migration file too. CI does not build the CSS;
the tests do not need it.

## Deployment

Production is one DigitalOcean droplet (Ubuntu 24.04) at `erp.<domain>`.
Caddy handles HTTPS and the static files, Gunicorn runs Django, and PostgreSQL
runs in Docker from the same `compose.yaml` used in development. The files are
in `deploy/`.

| File | Purpose |
| --- | --- |
| `deploy/setup-server.sh` | One-time setup of a fresh droplet: firewall, Docker, Caddy, the `erp` user, `.env` with generated secrets, backups, first deploy |
| `deploy/deploy.sh` | Every update: pull `production`, install packages, build CSS, `check --deploy`, collectstatic, migrate, open office hours, restart |
| `deploy/erp.service` | systemd service for Gunicorn |
| `deploy/Caddyfile` | Caddy site (`ERP_DOMAIN` is filled in by the setup script) |
| `deploy/backup.sh` | Nightly `pg_dump` at 02:30 into `/srv/erp-backups`, kept 14 days |
| `open_office_hours` (cron) | Nightly at 00:05: opens everyone's office hours (Mon–Sat 10:00–18:00, lunch 13:30–14:00 off) as 15-minute slots for the next 7 days |

**First time**

1. Create the droplet: Ubuntu 24.04, region Bangalore (BLR1), SSH key
   authentication, and turn on **Backups** (the off-server copy of everything,
   including the nightly dumps).
2. At the domain's DNS (HostGator), add an `A` record: name `erp`, value the
   droplet's IP. Leave everything else alone; the website and email stay where they are.
3. SSH in as root and run:

        curl -fsSL https://raw.githubusercontent.com/Raghavkhedar/ERP/production/deploy/setup-server.sh | bash -s erp.<domain>

4. Create the first admin account (the username is an employee ID such as S1):

        sudo -u erp -i sh -c 'cd /srv/erp && .venv/bin/python manage.py createsuperuser'

**Updating** after a PR is merged into `production`:

    ssh root@<droplet-ip> sudo -u erp -i /srv/erp/deploy/deploy.sh

**Useful commands on the server**

| Task | Command |
| --- | --- |
| App errors | `journalctl -u erp -e` |
| Restart the app | `systemctl restart erp` |
| Caddy and HTTPS problems | `journalctl -u caddy -e` |
| Open office hours now (e.g. for a new employee) | `sudo -u erp -i sh -c 'cd /srv/erp && .venv/bin/python manage.py open_office_hours'` |
| Run a backup now | `/srv/erp/deploy/backup.sh` |
| Restore a backup | `docker exec -i senken_erp_db pg_restore -U senken_erp -d senken_erp --clean < /srv/erp-backups/FILE.dump` |

The server clones the repo over HTTPS, which works while the repo is public. If it
becomes private, add a read-only deploy key on the server first.

## Project layout

| Path | Purpose |
| --- | --- |
| `config/` | Project settings and URL configuration |
| `core/` | Shared code, including the custom `User` model, the home view and the tests |
| `templates/` | Shared HTML templates (`base.html`, login, home) |
| `static/css/` | `input.css` (Tailwind source); `app.css` is generated |
| `static/vendor/` | Pinned htmx and Alpine.js, with `VERSIONS.md` |
| `scripts/` | Helper scripts: the Tailwind installer, and 'ship.sh' (check, push, PR, wait for CI, merge, sync) |
| `compose.yaml` | PostgreSQL 16 (development and production) |
| `deploy/` | Server setup, deploy and backup scripts (see **Deployment**) |
| `.env.example` | Template for your private `.env` file |
| `pyproject.toml`, `uv.lock` | Dependencies and their pinned versions |
| `.github/workflows/ci.yml` | The CI pipeline |

## Troubleshooting

**`password authentication failed for user "senken_erp"`**
The database was created with a different password from the `DB_PASSWORD` in
your `.env` now. If the database holds nothing you need, recreate it:

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

## Change history

Every business model must keep an audit trail with
[django-simple-history](https://django-simple-history.readthedocs.io/):

    from simple_history.models import HistoricalRecords

    class Something(models.Model):
        ...
        history = HistoricalRecords()

- It writes a row to a `Historical<Model>` table on every create, update and delete,
  including who made the change (the logged-in user, via `HistoryRequestMiddleware`).
- Leave out sensitive or noisy fields with `excluded_fields=[...]`. The `User` model
  excludes `password` and `last_login`.
- A model that already has data when history is switched on needs a one-time
  back-fill: `uv run python manage.py populate_history --auto`
- Never store values that can be calculated (last call date, interview status and
  so on). Calculate them from the records and their history when shown.
