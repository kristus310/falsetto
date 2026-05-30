PYTHON_VERSION ?= 3.13
PROJECT_SLUG   := falsetto
MANAGE         := uv run manage.py

.DEFAULT_GOAL := help

.PHONY: help install run tailwind-watch migrate migrations shell build collectstatic clean serve test

help:
	@echo "Available commands:"
	@echo "  make install        - Setup python, install deps, and tailwind"
	@echo "  make run            - Start dev server"
	@echo "  make tailwind-watch - Watch tailwind changes"
	@echo "  make test           - Run the unit test suite"
	@echo "  make migrate        - Run migrations"
	@echo "  make migrations     - Create migrations"
	@echo "  make superuser      - Create a super user (admin)"
	@echo "  make shell          - Open Django shell"
	@echo "  make build          - Production build (tailwind + static)"
	@echo "  make clean          - Remove pycache and temporary files"
	@echo "  make serve          - Run production gunicorn server"
	@echo "  make warmup         - Warm up the database with artist"
	@echo "  make cleanup-om-dry - Show what user media files are not used"
	@echo "  make cleanup-om     - Remove the not-used user media files"

install:
	mise use python@$(PYTHON_VERSION)
	uv sync --python $$(mise which python)
	$(MANAGE) tailwind setup

run:
	$(MANAGE) tailwind runserver

tailwind-watch:
	$(MANAGE) tailwind watch

shell:
	$(MANAGE) shell

migrate:
	$(MANAGE) migrate

migrations:
	$(MANAGE) makemigrations

superuser:
	$(MANAGE) createsuperuser

build:
	$(MANAGE) tailwind build
	$(MANAGE) collectstatic --no-input --ignore css/input.css

collectstatic:
	$(MANAGE) collectstatic --no-input --ignore css/input.css

serve:
	uv run gunicorn core.wsgi:application --bind 127.0.0.1:8000

test:
	$(MANAGE) collectstatic --noinput --ignore css/input.css
	$(MANAGE) test apps --pattern="tests.py" --verbosity=2

warmup:
	$(MANAGE) warm_music_up

cleanup-om-dry:
	$(MANAGE) cleanup_orphaned_media --dry-run

cleanup-om:
	$(MANAGE) cleanup_orphaned_media

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type f -name "*.pyc" -exec rm -f {} +