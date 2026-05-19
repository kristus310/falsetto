# Falsetto

Falsetto is a web game where you test your music knowledge by guessing song lyrics! You simply pick your favorite artist or band, choose the difficulty level, and see if you can recognize the song from just a snippet

---

##  Built with Django-Microcuts

This project was generated using **[django-microcuts](https://github.com/kristus310/django-microcuts)**, a custom Django project template built to spin up lightweight, modern web applications instantly. It comes pre-configured with a clean asset pipeline and modern frontend tools right out of the box:

* **Django:** The reliable powerhouse handling the game logic and user accounts.
* **HTMX:** The magic behind the scenes that updates the game screen instantly without refreshing the whole page.
* **Tailwind CSS & daisyUI:** A beautiful, responsive user interface designed to look great on both desktop and mobile devices.

---

## How It Works

Falsetto combines a smart game loop with a custom data pipeline to keep your matches fast, fair, and unpredictable.

### 1. The Game Loop & Your Lives
Instead of slowing the game down by saving every single button click into a permanent database, Falsetto manages your live game match entirely in temporary server memory.
* When you hit **Start**, a fresh game session is created tracking your chosen artist, difficulty, and total rounds, along with a stateful tracking system for your **3 lives**.
* The game automatically reads your guesses, subtracts a life if you slip up, and routes you to a **Victory** or **Game Over** screen depending on how well you do.

### 2. The Lyric Engine: Sourcing the Prompts
When you type in a band name, Falsetto coordinates a quick two-step process to fetch your game data:
1. **Last.fm API:** Automatically gathers the artist's catalog, cleans up messy song titles, and filters out duplicate versions (like live tracks or remixes).
2. **LRCLIB API:** Grabs the clean, plain-text lyrics for the chosen song, while stripping out formatting noise like [Chorus] or [Verse 1].

### 3. Intelligent Difficulty Levels
To make "Easy", "Medium", and "Hard" actually feel different, the game doesn't just pick random songs. It calculates a song's real-world popularity to build the perfect challenge:
* **Easy:** Picks strictly from the artist's absolute biggest hits (the top 20% of their catalog).
* **Medium:** Blends mid-tier favorites and uses a custom formula to give you a diverse, realistic challenge (20% to 55% of their catalog).
* **Hard:** Dives deep into the artist's lesser-known tracks, deep cuts, and b-sides (55%+ of their catalog).

> **Quality Control (No Bad Snippets):** A great lyric game shouldn't give away the answer or show repetitive filler. Falsetto scores lyric blocks before showing them to you. It filters out generic lines (like "Yeah, yeah, oh"), hides blocks that give away the song title in the text, and selects descriptive, meaningful verses to ensure every round is fun to read.

---

## Project Structure

For developers looking at the code, the project is organized into clean, isolated modules:

```
├── apps/
│   ├── game/          # Handles game turns, guess evaluation, and game screens.
│   ├── lyrics/        # Connects to Last.fm & LRCLIB and handles the logic.
│   ├── pages/         # Static content pages (About, FAQ, Contact, Legal).
│   └── users/         # Custom user accounts, profiles, and login flows.
├── assets/            # Tailwind CSS source files, images, and HTMX.
├── templates/         # Clean HTML components and user interface layout files.
├── Makefile           # Simple, single-word terminal commands to manage the project.
├── mise.toml          # Toolchain manager to keep dev environments consistent.
└── pyproject.toml     # Modern Python packaging configuration managed by uv.
```

---

## Setup & Running the Project

The project uses **mise** to handle tool versions and **uv** for lightning-fast Python package management.

### Quick Start
1. Create a `.env` file in the root directory and add your Last.fm credentials:
   LASTFM_API_KEY=your_api_key_here
   LASTFM_BASE_URL=https://ws.audioscrobbler.com/2.0/

2. Run the automated installer script to set up your environment, install packages, and initialize your styles:
   make install

### Everyday Terminal Shortcuts

* make run            - Starts the local development server so you can play the app in your browser.
* make tailwind-watch - Automatically watches your template files and live-compiles styling changes.
* make migrations     - Generates database changes after you edit database structures.
* make migrate        - Applies pending database updates to your local database.
* make superuser      - Creates an administrator account for the Django backend.
* make build          - Prepares the project for production (builds styles and gathers static files).
* make clean          - Deletes temporary cache folders and junk files to keep the project tidy.
* make serve          - Runs the app in a production-ready mode via a Gunicorn server.