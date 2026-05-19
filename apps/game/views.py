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

        return redirect("game:game")

    return render(request, "game/lobby.html")


def game(request: HttpRequest) -> HttpResponse:
    artist = request.session.get("game_artist")
    if not artist:
        messages.error(request, "Please choose an artist and start a session first.")
        return redirect("game:lobby")

    difficulty = request.session.get("difficulty", "medium")
    total_rounds = request.session.get("total_rounds", 5)
    current_round = request.session.get("current_round", 1)
    lives = request.session.get("lives", {"1": True, "2": True, "3": True})
    answered = request.session.get("answered", False)
    music = request.session.get("music")

    if current_round > total_rounds:
        request.session["game_artist"] = None
        return render(request, "game/victory.html")

    if request.method == "POST" and request.GET.get("action") == "quit":
        request.session["lives"] = {"1": True, "2": True, "3": True}
        request.session["current_round"] = 1
        request.session["answered"] = False
        request.session["music"] = None
        return redirect("game:lobby")

    if request.method == "POST" and request.GET.get("action") == "next":
        request.session["current_round"] = current_round + 1
        request.session["answered"] = False
        request.session["music"] = None
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
                f"Could not extract sufficient text data for '{artist}'. "
                "They might be instrumental or unavailable. Try another artist!"
            )
            return redirect("game:lobby")

        request.session["music"] = music
        request.session["answered"] = False
        answered = False

    if request.method == "POST" and not request.GET.get("action"):
        form = LyricsGuessForm(request.POST)
        if form.is_valid():
            guess = form.cleaned_data["guess"].strip().lower()
            correct_answer = music["answer"].lower()

            if guess == correct_answer:
                request.session["answered"] = True
                answered = True
            else:
                lives, is_dead = game_service.remove_live(lives)
                request.session["lives"] = lives

                if is_dead:
                    request.session["game_artist"] = None
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


def game_over(request: HttpRequest) -> HttpResponse:
    return render(request, "game/game-over.html")