from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from django.contrib.auth.decorators import login_required

@login_required
def profile(request: HttpRequest) -> HttpResponse:
    recent_scores = request.user.scores.filter(completed=True).order_by("-score")[:5]
    context = {
        "scores": recent_scores,
    }
    return render(request, "users/profile.html", context)

@login_required
def settings(request: HttpRequest) -> HttpResponse:
    return render(request, "users/settings.html")
