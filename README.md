# Senken ERP

Empanelment module of the Senken ERP. Django 5.2, PostgreSQL 16.

## Requirements
- Docker with the compose plugin
- uv (https://docs.astral.sh/uv/)

## First-time setup
1. `cp .env.example .env`, then fill in real values
   (use letters and digits only in DB_PASSWORD, and use the same value in DATABASE_URL)
2. `docker compose up -d`
3. `uv sync`
4. `uv run python manage.py migrate`
5. `uv run python manage.py createsuperuser`
6. `uv run python manage.py runserver`, then open http://127.0.0.1:8000/admin/

## Everyday commands
| Task | Command |
| --- | --- |
| Start database | `docker compose up -d` |
| Stop database | `docker compose stop` |
| Run tests | `uv run pytest` |
| Make migrations | `uv run python manage.py makemigrations` |

## Workflow
- `production` is protected. Work on a branch, open a PR, wait for CI to pass.
- Branch names: `feature/...`, `fix/...`

## Layout
- `config/`: project settings and URLs
- `core/`: shared things (the custom User model)
