from django.shortcuts import render
from .forms import LyricsGuessForm
from .services import _remove_life

def index(request):
    return render(request, "game/index.html")

def lobby(request):
    return render(request, "game/lobby.html")

def game(request):
    music = {
        "artist": "Muse",
        "song": "Starlight",
        "lyrics": "Far away, this ship is taking me far away. Far away from the ________ of the people who care if I live or die.",
        "answer": "memories",
    }
    lives = request.session.get("lives", {"1": True, "2": True, "3": True})
    difficulty = request.session.get("difficulty", "medium")
    total_rounds = request.session.get("total_rounds", 5)
    current_round = request.session.get("currend_round", 1)
    answered = request.session.get("answered", False)

    if request.method == "POST":
        form = LyricsGuessForm(request.POST)
        if form.is_valid():
            guess = form.cleaned_data["guess"].strip().lower()

            if guess == music["answer"].lower():
                answered = True
                request.session["answered"] = answered

                current_round += 1
                request.session["current_round"] = current_round
            else:
                lives = _remove_life(lives)
                request.session["lives"] = lives
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
    }

    return render(request, "game/game.html", context=context)