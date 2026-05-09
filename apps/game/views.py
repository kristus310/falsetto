from django.shortcuts import render

def index(request):
    return render(request, "game/index.html")

def lobby(request):
    return render(request, "game/lobby.html")

def game(request):
    lyrics = "Far away, this ship is taking me far away. Far away from the ________ of the people who care if I live or die."

    context = {
        "lyrics": lyrics,
        "lives": range(3),
    }

    return render(request, "game/game.html", context=context)