from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse
from django.contrib import messages
from django.db.models import Count
from .forms import LyricsGuessForm
from .services import GameService, is_correct_guess, calculate_score

from apps.users.models import UserScore

_VALID_DIFFICULTIES = {"easy", "medium", "hard", "insane"}

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

    top_scores = (
        UserScore.objects.filter(completed=True, user__profile__show_on_leaderboard=True)
        .select_related("user")
        .order_by("-score", "-created_at")[:5]
    )

    context = {
        "most_played_artist": most_played,
        "play_count": play_count,
        "top_scores": top_scores,
    }
    return render(request, "game/index.html", context=context)

def lobby(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        artist = request.POST.get("artist", "").strip().title()

        difficulty = request.POST.get("difficulty", "medium")
        if difficulty not in _VALID_DIFFICULTIES:
            difficulty = "medium"

        try:
            total_rounds = int(request.POST.get("rounds", 5))
            total_rounds = max(1, min(total_rounds, 20))
        except ValueError:
            total_rounds = 5

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

        return redirect("game:game")
    return render(request, "game/lobby.html")

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

    if current_round > total_rounds:
        request.session["game_status"] = "won"
        return redirect("game:victory")

    action = request.POST.get("action") or request.GET.get("action")
    if request.method == "POST" and action:
        if action == "quit":
            request.session["game_status"] = "lobby"
            return redirect("game:lobby")

        elif action == "next" and answered:
            request.session["current_round"] = current_round + 1
            request.session["music"] = None
            request.session["answered"] = False
            request.session.modified = True
            return redirect("game:game")

    if not music:
        game_service = GameService()
        attempts = 0
        while attempts < 3:
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
            return redirect("game:lobby")

        request.session["music"] = music
        request.session["answered"] = False
        answered = False
        request.session.modified = True

    if request.method == "POST" and not action:
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

                summary = request.session.get("round_summary", [])
                summary.append({
                    "artist": music["artist"],
                    "song": music["song"],
                    "answer": music["answer"],
                    "correct": True,
                    "round_score": round_score,
                })
                request.session["round_summary"] = summary
                request.session.modified = True
            else:
                game_service = GameService()
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
                    })
                    request.session["round_summary"] = summary
                    request.session["game_status"] = "lost"
                    request.session.modified = True
                    return redirect("game:game_over")

                messages.error(request, "Incorrect lyric guess! Try again.")
    else:
        form = LyricsGuessForm()

    context = {
        "answered": answered,
        "form": form,
        "music": music,
        "lives": lives,
        "difficulty": difficulty,
        "total_rounds": total_rounds,
        "current_round": current_round,
        "game_artist": artist,
    }
    return render(request, "game/game.html", context=context)

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

    if request.user.is_authenticated and not request.session.get("score_saved", False):
        UserScore.objects.create(
            user=request.user,
            artist=artist,
            difficulty=difficulty,
            score=score,
            correct_count=correct_count,
            total_rounds=total_rounds,
            completed=True
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

    if request.user.is_authenticated and not request.session.get("score_saved", False):
        UserScore.objects.create(
            user=request.user,
            artist=artist,
            difficulty=difficulty,
            score=score,
            correct_count=correct_count,
            total_rounds=total_rounds,
            completed=False
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
    }
    return render(request, "game/game-over.html", context)

def leaderboard(request: HttpRequest) -> HttpResponse:
    top_scores = (
        UserScore.objects.filter(completed=True, user__profile__show_on_leaderboard=True)
        .select_related("user")
        .order_by("-score", "-created_at")[:50]
    )
    context = {
        "top_scores": top_scores,
    }
    return render(request, "game/leaderboard.html", context)