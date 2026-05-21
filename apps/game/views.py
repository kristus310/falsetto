from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse
from django.contrib import messages
from .forms import LyricsGuessForm
from .services import GameService

game_service = GameService()

def index(request: HttpRequest) -> HttpResponse:
    return render(request, "game/index.html")

def lobby(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        artist = request.POST.get("artist", "").strip()
        difficulty = request.POST.get("difficulty", "medium")
        try:
            total_rounds = int(request.POST.get("rounds", 5))
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
        request.session["round_summary"] = []

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

    action = request.GET.get("action")
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
            guess = form.cleaned_data["guess"].strip().lower()
            correct_answer = music["answer"].lower()

            if guess == correct_answer:
                request.session["answered"] = True
                answered = True
                request.session["correct_count"] = request.session.get("correct_count", 0) + 1
                summary = request.session.get("round_summary", [])
                summary.append({
                    "artist": music["artist"],
                    "song": music["song"],
                    "answer": music["answer"],
                    "correct": True,
                })
                request.session["round_summary"] = summary
                request.session.modified = True
            else:
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

    context = {
        "total_rounds": request.session.get("total_rounds", 0),
        "correct_count": request.session.get("correct_count", 0),
        "lives_remaining": lives_remaining,
        "round_summary": request.session.get("round_summary", []),
        "difficulty": request.session.get("difficulty", ""),
        "game_artist": request.session.get("game_artist", ""),
    }
    return render(request, "game/victory.html", context)

def game_over(request: HttpRequest) -> HttpResponse:
    if request.session.get("game_status") != "lost":
        return redirect("game:lobby")

    lives = request.session.get("lives", {})
    lives_lost = sum(1 for v in lives.values() if not v)

    context = {
        "total_rounds": request.session.get("total_rounds", 0),
        "current_round": request.session.get("current_round", 0),
        "correct_count": request.session.get("correct_count", 0),
        "lives_lost": lives_lost,
        "round_summary": request.session.get("round_summary", []),
        "difficulty": request.session.get("difficulty", ""),
        "game_artist": request.session.get("game_artist", ""),
    }
    return render(request, "game/game-over.html", context)