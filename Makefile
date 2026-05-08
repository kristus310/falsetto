PYTHON_VERSION ?= 3.13
PROJECT_SLUG   := falsetto
MANAGE         := uv run manage.py

.DEFAULT_GOAL := help

.PHONY: help install run tailwind-watch migrate migrations shell build collectstatic clean serve 

help:
	@echo "Available commands:"
	@echo "  make install        - Setup python, install deps, and tailwind"
	@echo "  make run            - Start dev server"
	@echo "  make tailwind-watch - Watch tailwind changes"
	@echo "  make migrate        - Run migrations"
	@echo "  make migrations     - Create migrations"
	@echo "  make shell          - Open Django shell"
	@echo "  make build          - Production build (tailwind + static)"
	@echo "  make clean          - Remove pycache and temporary files"
	@echo "  make serve          - Run production gunicorn server"


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

build:
	$(MANAGE) tailwind build
	$(MANAGE) collectstatic --no-input

collectstatic:
	$(MANAGE) collectstatic --no-input

serve:
	uv run gunicorn $(PROJECT_SLUG).wsgi:application --bind 0.0.0.0:8000

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type f -name "*.pyc" -exec rm -f {} +