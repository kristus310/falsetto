# Falsetto

Hi! Welcome to **Falsetto** — a music trivia game I built as a passion project to test how well we actually know our favorite artists (not just their top-played radio hits).

It is a fully responsive web application built with **Django**, **Tailwind CSS**, and **HTMX**. It queries live music databases, parses lyrics dynamically, and serves up smooth, fast trivia directly in your browser.

---

## The Game Modes

There are three ways to play, plus a special daily challenge:

*   **Complete the Lyrics:** The game pulls a random song from an artist's catalog, displays a verse snippet with a single word blanked out, and you have to fill it in.
*   **Guess the Song:** You get a full lyric verse snippet with nothing hidden, and you have to name the track.
*   **Pick a Song:** Choose a specific song from an artist's catalog to get quizzed on across multiple rounds, pulling a different blanked-out word each time.
*   **Daily Challenge:** A deterministic game generated once a day featuring a designated daily artist. Everyone gets the exact same lyric snippets based on date seeds, and you get exactly one attempt per day to build your streak and track your performance history!

> [!NOTE]
> Accounts are entirely optional! You can play as a guest as much as you'd like. Creating an account simply allows the game to securely save your detailed match history, victory rates, and personal accuracy metrics.

---

## How a Round Works

1.  **Select Your Game:** Pick an artist, mode, difficulty, and round count (or pick a specific song in Pick a Song mode).
2.  **Read the Lyrics:** A beautiful, responsive snippet of lyrics will appear.
3.  **Type Your Guess:** Submit your answer. Correct guesses score points and build your streak. Incorrect guesses cost a life (you get **3 lives** per session).
4.  **Victory or Defeat:** Complete all rounds to win! If you run out of lives, it's game over. If you are signed in, your stats are instantly committed to your personal **My History** page.

---

## Under the Hood (For Techies)

If you're interested in the coding side, here is how the engine runs behind the scenes:

### 1. Song Filtering & Smart Deduplication
When you search for an artist, the game queries the **Last.fm API** to retrieve their top tracks. To keep gameplay clean, the engine runs a deduplication filter using regular expressions to collapse variants (like `Live`, `Acoustic`, `Remastered`, `Radio Edit`, or `feat.`) into their single canonical tracks.

The tracks are then sorted by popularity and grouped into difficulty tiers:
*   **Easy:** Top 20% by play count
*   **Medium:** 20% to 55%
*   **Hard:** 55% to 75%
*   **Insane:** The deep cuts (75%+)

We cache this catalog in the database after the first fetch so subsequent rounds load instantly and conserve API limits.

### 2. Lyric Processing & Excerpt Selection
Once a track is selected, the game talks to **LRCLIB** to fetch synchronized and plain-text lyrics. The engine filters the text by:
*   Stripping out structural markers (e.g. `[Chorus]`, `[Verse 1]`).
*   Scoring lines based on meaningful word density (excluding generic filler words like "oh", "yeah", "la").
*   Discarding any snippets containing the song's title to prevent accidental giveaways.

The highest-scoring block of 3–4 lines is chosen as the round's excerpt.

### 3. Fuzzy Matching
To make sure a missing accent or minor typo doesn't cost you a life, the guess checker normalizes both the input and the answer by stripping accents, capitalization, and punctuation. It then performs a `difflib.SequenceMatcher` comparison. By default, an **85% similarity** passes as correct.

### 4. Session & Database Cache (Production Ready)
Active game states (round, lives, score, streak) are handled entirely in-memory using Django's session middleware to keep database writes minimal.
For production, the project utilizes Django's shared **`DatabaseCache`** backend. This is highly reliable for multi-process Gunicorn deployments on a home server because it ensures rate limits (via `django-allauth`) and session state are shared instantly across all worker processes without needing Redis.

---

## The Tech Stack

*   **Backend:** Python 3.13, Django 5+
*   **Frontend:** HTML5, Tailwind CSS, daisyUI, and HTMX (for fast, partial page reloads without full browser refreshes)
*   **Database:** SQLite (Local Dev) / PostgreSQL (Production)
*   **Authentication & Security:** Custom User Model, `django-allauth` integration (secured with post-save signals keeping primary email records strictly synchronized), and in-session rate-limiting.
*   **Serving:** Gunicorn WSGI server and WhiteNoise (with Brotli compression) for serving static files.
*   **Tooling:** `uv` for python dependency locks and `mise` for local runtime versions.

---

## Getting Started Locally

To run this project on your machine, ensure you have **`mise`** and **`uv`** installed, then execute:

```bash
# Setup Python toolchain, install dependencies, and build Tailwind CSS
make install

# Apply database migrations
make migrate

# Create an administrator account
make superuser

# Start the local development server at http://127.0.0.1:8000
make run
```

---

## Full Make Command Reference

| Command | What it does |
| :--- | :--- |
| `make install` | Full development environment setup (python dependencies + Tailwind) |
| `make run` | Runs local dev server |
| `make tailwind-watch` | Recompiles styling assets on HTML template modifications |
| `make test` | Runs the 289-case Django unit test suite |
| `make migrations` | Creates new database migration files |
| `make migrate` | Applies pending database migrations |
| `make superuser` | Launches the interactive admin creation utility |
| `make warmup` | Pre-caches lyric logs for daily challenge artists |
| `make build` | Prepares production assets (collects static files, builds minified CSS) |
| `make serve` | Runs the production-grade Gunicorn server locally |
| `make clean` | Removes temporary build and pycache folders |
