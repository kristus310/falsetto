from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse
from django.contrib import messages
from django.db.models import Count, Avg, Max, F, FloatField
from django.db.models.functions import Cast
from django.core.paginator import Paginator
from .forms import LyricsGuessForm
from .services import GameService, is_correct_guess, calculate_score

from apps.users.models import UserScore

_VALID_DIFFICULTIES = {"easy", "medium", "hard", "insane"}
_VALID_MODES = {"complete_lyrics", "guess_song", "pick_song"}


def index(request: HttpRequest) -> HttpResponse:
    most_played = "None yet!"
    play_count = 0

    if request.user.is_authenticated:
        most_played_data = (
            UserScore.objects.filter(user=request.user)
            .values("artist")
            .annotate(times_played=Count("artist"))
            .order_by("-times_played")
            .first()
        )
        if most_played_data:
            most_played = most_played_data["artist"]
            play_count = most_played_data["times_played"]

    context = {
        "most_played_artist": most_played,
        "play_count": play_count,
    }
    return render(request, "game/index.html", context=context)


def lobby(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        artist = request.POST.get("artist", "").strip().title()[:120]

        difficulty = request.POST.get("difficulty", "medium")
        if difficulty not in _VALID_DIFFICULTIES:
            difficulty = "medium"

        try:
            total_rounds = int(request.POST.get("rounds", 5))
            total_rounds = max(1, min(total_rounds, 20))
        except ValueError:
            total_rounds = 5

        mode = request.POST.get("mode", "complete_lyrics")
        if mode not in {"complete_lyrics", "guess_song"}:
            mode = "complete_lyrics"

        if not artist:
            messages.error(request, "Please type an artist name to begin.")
            return render(request, "game/lobby.html")

        request.session["game_artist"] = artist
        request.session["difficulty"] = difficulty
        request.session["total_rounds"] = total_rounds
        request.session["current_round"] = 1
        request.session["lives"] = {"1": True, "2": True, "3": True}
        request.session["music"] = None
        request.session["answered"] = False
        request.session["game_status"] = "playing"
        request.session["correct_count"] = 0
        request.session["score"] = 0
        request.session["streak"] = 0
        request.session["round_summary"] = []
        request.session["score_saved"] = False
        request.session["game_mode"] = mode

        GameService().warm_up_cache_async(artist, difficulty)

        return redirect("game:game")

    default_difficulty = "medium"
    default_rounds = 3
    if request.user.is_authenticated:
        try:
            default_difficulty = request.user.profile.default_difficulty
            default_rounds = request.user.profile.default_rounds
        except Exception:
            pass

    return render(request, "game/lobby.html", {
        "default_difficulty": default_difficulty,
        "default_rounds": default_rounds,
    })


def pick_song_lobby(request: HttpRequest) -> HttpResponse:
    game_service = GameService()

    if request.method == "POST" and request.POST.get("action") == "search_tracks":
        artist = request.POST.get("artist", "").strip().title()
        if not artist:
            return render(request, "game/partials/track-list.html", {"tracks": [], "artist": ""})

        tracks = game_service.get_tracks_for_artist(artist)
        return render(request, "game/partials/track-list.html", {
            "tracks": tracks,
            "artist": artist,
        })

    if request.method == "POST" and request.POST.get("action") == "start_pick_song":
        artist = request.POST.get("artist", "").strip().title()[:120]
        song = request.POST.get("song", "").strip()[:200]

        try:
            total_rounds = int(request.POST.get("rounds", 5))
            total_rounds = max(1, min(total_rounds, 20))
        except ValueError:
            total_rounds = 5

        if not artist or not song:
            messages.error(request, "Please select an artist and a song.")
            return render(request, "game/pick-song-lobby.html")

        request.session["game_artist"] = artist
        request.session["pick_song_name"] = song
        request.session["difficulty"] = "medium"
        request.session["total_rounds"] = total_rounds
        request.session["current_round"] = 1
        request.session["lives"] = {"1": True, "2": True, "3": True}
        request.session["music"] = None
        request.session["answered"] = False
        request.session["game_status"] = "playing"
        request.session["correct_count"] = 0
        request.session["score"] = 0
        request.session["streak"] = 0
        request.session["round_summary"] = []
        request.session["score_saved"] = False
        request.session["game_mode"] = "pick_song"
        request.session["pick_song_used_words"] = []

        return redirect("game:game")

    return render(request, "game/pick-song-lobby.html")


def game(request: HttpRequest) -> HttpResponse:
    artist = request.session.get("game_artist")
    status = request.session.get("game_status", "lobby")

    if not artist or status != "playing":
        messages.error(request, "Please choose an artist and start a session first.")
        return redirect("game:lobby")

    difficulty = request.session.get("difficulty", "medium")
    total_rounds = request.session.get("total_rounds", 5)
    current_round = request.session.get("current_round", 1)
    lives = request.session.get("lives", {"1": True, "2": True, "3": True})
    answered = request.session.get("answered", False)
    music = request.session.get("music")
    game_mode = request.session.get("game_mode", "complete_lyrics")

    if current_round > total_rounds:
        request.session["game_status"] = "won"
        return redirect("game:victory")

    game_service = GameService()
    form = LyricsGuessForm()

    if request.method == "POST":
        action = request.POST.get("action") or request.GET.get("action")

        if action:
            if action == "quit":
                request.session["game_status"] = "lobby"
                if game_mode == "pick_song":
                    return redirect("game:pick_song_lobby")
                return redirect("game:lobby")

            elif action == "next" and answered:
                request.session["current_round"] = current_round + 1
                request.session["music"] = None
                request.session["answered"] = False
                request.session.modified = True
                return redirect("game:game")

        else:
            form = LyricsGuessForm(request.POST)
            if form.is_valid():
                guess = form.cleaned_data["guess"].strip()
                correct_answer = music["answer"]

                if is_correct_guess(guess, correct_answer):
                    request.session["answered"] = True
                    answered = True
                    request.session["correct_count"] = request.session.get("correct_count", 0) + 1

                    streak = request.session.get("streak", 0) + 1
                    request.session["streak"] = streak
                    round_score = calculate_score(difficulty, lives, streak)
                    request.session["score"] = request.session.get("score", 0) + round_score

                    if game_mode == "pick_song":
                        used = request.session.get("pick_song_used_words", [])
                        used.append(correct_answer)
                        request.session["pick_song_used_words"] = used

                    summary = request.session.get("round_summary", [])
                    summary.append({
                        "artist": music["artist"],
                        "song": music["song"],
                        "answer": music["answer"],
                        "correct": True,
                        "round_score": round_score,
                        "mode": game_mode,
                    })
                    request.session["round_summary"] = summary
                    request.session.modified = True

                    if game_mode != "pick_song":
                        game_service.warm_up_cache_async(artist, difficulty)
                else:
                    request.session["streak"] = 0
                    lives, is_dead = game_service.remove_live(lives)
                    request.session["lives"] = lives
                    request.session.modified = True

                    if is_dead:
                        summary = request.session.get("round_summary", [])
                        summary.append({
                            "artist": music["artist"],
                            "song": music["song"],
                            "answer": music["answer"],
                            "correct": False,
                            "mode": game_mode,
                        })
                        request.session["round_summary"] = summary
                        request.session["game_status"] = "lost"
                        request.session.modified = True
                        return redirect("game:game_over")

                    if game_mode != "pick_song":
                        game_service.warm_up_cache_async(artist, difficulty)

                    messages.error(request, _wrong_guess_message(game_mode))
    else:
        form = LyricsGuessForm()

    if not music:
        attempts = 0
        while attempts < 3:
            if game_mode == "guess_song":
                music = game_service.generate_guess_song_data(artist, difficulty)
            elif game_mode == "pick_song":
                song_name = request.session.get("pick_song_name", "")
                used_words = request.session.get("pick_song_used_words", [])
                music = game_service.generate_pick_song_data(artist, song_name, used_words)
            else:
                music = game_service.generate_round_data(artist, difficulty)

            if music:
                break
            attempts += 1

        if not music:
            messages.error(
                request,
                f"Could not extract sufficient lyrics for '{artist}'. Try another artist!"
            )
            request.session["game_status"] = "lobby"
            if game_mode == "pick_song":
                return redirect("game:pick_song_lobby")
            return redirect("game:lobby")

        request.session["music"] = music
        request.session["answered"] = False
        answered = False
        request.session.modified = True

    context = {
        "answered": answered,
        "form": form,
        "music": music,
        "lives": lives,
        "difficulty": difficulty,
        "total_rounds": total_rounds,
        "current_round": current_round,
        "game_artist": artist,
        "game_mode": game_mode,
        "is_guess_song": game_mode == "guess_song",
        "is_pick_song": game_mode == "pick_song",
        "is_complete_lyrics": game_mode == "complete_lyrics",
    }
    return render(request, "game/game.html", context=context)


def _wrong_guess_message(game_mode: str) -> str:
    if game_mode == "guess_song":
        return "Wrong song title! Try again."
    return "Incorrect lyric guess! Try again."


def victory(request: HttpRequest) -> HttpResponse:
    if request.session.get("game_status") != "won":
        return redirect("game:lobby")

    lives = request.session.get("lives", {})
    lives_remaining = sum(1 for v in lives.values() if v)

    score = request.session.get("score", 0)
    correct_count = request.session.get("correct_count", 0)
    total_rounds = request.session.get("total_rounds", 0)
    difficulty = request.session.get("difficulty", "medium")
    artist = request.session.get("game_artist", "")
    game_mode = request.session.get("game_mode", "complete_lyrics")

    if request.user.is_authenticated and not request.session.get("score_saved", False):
        UserScore.objects.create(
            user=request.user,
            artist=artist,
            difficulty=difficulty,
            game_mode=game_mode,
            score=score,
            correct_count=correct_count,
            total_rounds=total_rounds,
            completed=True,
        )
        request.session["score_saved"] = True

    context = {
        "total_rounds": total_rounds,
        "correct_count": correct_count,
        "score": score,
        "points": score,
        "lives_remaining": lives_remaining,
        "round_summary": request.session.get("round_summary", []),
        "difficulty": difficulty,
        "game_artist": artist,
        "game_mode": game_mode,
        "is_guess_song": game_mode == "guess_song",
        "is_pick_song": game_mode == "pick_song",
        "is_complete_lyrics": game_mode == "complete_lyrics",
        "pick_song_name": request.session.get("pick_song_name", ""),
    }
    return render(request, "game/victory.html", context)


def game_over(request: HttpRequest) -> HttpResponse:
    if request.session.get("game_status") != "lost":
        return redirect("game:lobby")

    lives = request.session.get("lives", {})
    lives_lost = sum(1 for v in lives.values() if not v)

    score = request.session.get("score", 0)
    correct_count = request.session.get("correct_count", 0)
    total_rounds = request.session.get("total_rounds", 0)
    difficulty = request.session.get("difficulty", "medium")
    artist = request.session.get("game_artist", "")
    game_mode = request.session.get("game_mode", "complete_lyrics")

    if request.user.is_authenticated and not request.session.get("score_saved", False):
        UserScore.objects.create(
            user=request.user,
            artist=artist,
            difficulty=difficulty,
            game_mode=game_mode,
            score=score,
            correct_count=correct_count,
            total_rounds=total_rounds,
            completed=False,
        )
        request.session["score_saved"] = True

    context = {
        "total_rounds": total_rounds,
        "current_round": request.session.get("current_round", 0),
        "correct_count": correct_count,
        "score": score,
        "lives_lost": lives_lost,
        "round_summary": request.session.get("round_summary", []),
        "difficulty": difficulty,
        "game_artist": artist,
        "game_mode": game_mode,
        "is_guess_song": game_mode == "guess_song",
        "is_pick_song": game_mode == "pick_song",
        "is_complete_lyrics": game_mode == "complete_lyrics",
        "pick_song_name": request.session.get("pick_song_name", ""),
    }
    return render(request, "game/game-over.html", context)


def history(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        return render(request, "game/history.html", {
            "is_authenticated": False,
        })

    # Available choices for filtering
    selected_mode = request.GET.get("mode", "")
    selected_difficulty = request.GET.get("difficulty", "")

    # Query scores strictly for the logged-in user
    scores = UserScore.objects.filter(user=request.user)

    if selected_mode in _VALID_MODES:
        scores = scores.filter(game_mode=selected_mode)
    if selected_difficulty in _VALID_DIFFICULTIES:
        scores = scores.filter(difficulty=selected_difficulty)

    scores = scores.order_by("-created_at")

    # Compute personal stats/metrics
    total_games = UserScore.objects.filter(user=request.user).count()
    completed_games = UserScore.objects.filter(user=request.user, completed=True)

    # Calculate avg accuracy & highest score securely and performantly, avoiding division by zero in SQL
    metrics = completed_games.filter(total_rounds__gt=0).aggregate(
        avg_accuracy=Avg(Cast(F("correct_count"), FloatField()) / Cast(F("total_rounds"), FloatField()) * 100),
        highest_score=Max("score")
    )

    avg_accuracy = round(metrics["avg_accuracy"] or 0.0, 1)
    highest_score = metrics["highest_score"] or 0
    completed_count = completed_games.count()
    victory_rate = round(completed_count / total_games * 100, 1) if total_games > 0 else 0.0

    # Paginate the scores list
    page_number = request.GET.get("page", 1)
    paginator = Paginator(scores, 15)  # 15 scores per page
    page_obj = paginator.get_page(page_number)

    context = {
        "is_authenticated": True,
        "page_obj": page_obj,
        "selected_mode": selected_mode,
        "selected_difficulty": selected_difficulty,
        "available_modes": UserScore.GameModes.choices,
        "available_difficulties": UserScore.Difficulties.choices,
        "total_games": total_games,
        "highest_score": highest_score,
        "avg_accuracy": avg_accuracy,
        "victory_rate": victory_rate,
    }
    return render(request, "game/history.html", context)