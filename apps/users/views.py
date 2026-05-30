from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.db.models import Sum, Max, Count
from django.views.decorators.http import require_http_methods

from .forms import UsernameForm, EmailForm, DeleteAccountForm, AvatarForm
from .models import UserProfile


def _compute_win_streak(scores_qs):
    games = list(scores_qs.order_by("-created_at").values_list("completed", flat=True))
    current = 0
    for completed in games:
        if completed:
            current += 1
        else:
            break

    best = 0
    running = 0
    for completed in reversed(games):
        if completed:
            running += 1
            best = max(best, running)
        else:
            running = 0

    return current, best


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    user = request.user
    scores_qs = user.scores.all()
    recent_scores = scores_qs.order_by("-created_at")[:5]

    aggregates = scores_qs.aggregate(
        total_games=Count("id"),
        total_correct=Sum("correct_count"),
        total_rounds=Sum("total_rounds"),
        best_score=Max("score"),
    )

    total_correct = aggregates["total_correct"] or 0
    total_rounds = aggregates["total_rounds"] or 0
    accuracy = round(total_correct / total_rounds * 100) if total_rounds else 0

    best_score_obj = scores_qs.order_by("-score").first()
    best_score_difficulty = (
        f"pts - {best_score_obj.get_difficulty_display()}" if best_score_obj else None
    )

    win_streak, best_streak = _compute_win_streak(scores_qs)

    context = {
        "scores": recent_scores,
        "total_games": aggregates["total_games"] or 0,
        "total_correct": total_correct,
        "accuracy": accuracy,
        "best_score": aggregates["best_score"] or 0,
        "best_score_difficulty": best_score_difficulty,
        "win_streak": win_streak,
        "best_streak": best_streak,
    }
    return render(request, "users/profile.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def settings(request: HttpRequest) -> HttpResponse:
    user = request.user
    user_profile, _ = UserProfile.objects.get_or_create(user=user)

    username_form = UsernameForm(instance=user)
    email_form = EmailForm(instance=user)
    avatar_form = AvatarForm(instance=user_profile)
    delete_form = DeleteAccountForm(user=user)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "avatar":
            if "avatar" in request.FILES:
                avatar_form = AvatarForm(request.POST, request.FILES, instance=user_profile)
                if avatar_form.is_valid():
                    avatar_form.save()
                    messages.success(request, "Avatar updated successfully.")
                    return redirect("users:settings")
                else:
                    messages.error(request, avatar_form.errors["avatar"][0])
            else:
                messages.error(request, "Please pick an image file before clicking save.")

        elif action == "profile":
            username_form = UsernameForm(request.POST, instance=user)
            email_form = EmailForm(request.POST, instance=user)
            if username_form.is_valid() and email_form.is_valid():
                username_form.save()
                email_form.save()
                messages.success(request, "Profile updated successfully.")
                return redirect("users:settings")
            messages.error(request, "Please fix the errors below.")

        elif action == "preferences":
            difficulty = request.POST.get("default_difficulty", "medium")
            if difficulty not in {"easy", "medium", "hard", "insane"}:
                difficulty = "medium"
            try:
                rounds = int(request.POST.get("default_rounds", 3))
                rounds = max(1, min(rounds, 20))
            except ValueError:
                rounds = 3

            user_profile.show_on_leaderboard = "show_on_leaderboard" in request.POST
            user_profile.default_difficulty = difficulty
            user_profile.default_rounds = rounds
            user_profile.save(update_fields=[
                "show_on_leaderboard",
                "default_difficulty",
                "default_rounds",
            ])

    context = {
        "username_form": username_form,
        "email_form": email_form,
        "avatar_form": avatar_form,
        "delete_form": delete_form,
    }
    return render(request, "users/settings.html", context)


@login_required
@require_http_methods(["POST"])
def delete_avatar(request):
    request.user.profile.delete_avatar()
    messages.success(request, "Avatar removed.")
    return redirect("users:settings")


@login_required
@require_http_methods(["POST"])
def delete_account(request: HttpRequest) -> HttpResponse:
    user = request.user
    form = DeleteAccountForm(request.POST, user=user)
    if form.is_valid():
        logout(request)
        user.delete()
        messages.success(request, "Your account has been permanently deleted.")
        return redirect("account_login")
    messages.error(request, "Incorrect password. Account was not deleted.")
    return redirect("users:settings")