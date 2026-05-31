import datetime
from .models import UserScore

def daily_challenge_status(request):
    if request.user.is_authenticated:
        today = datetime.date.today()
        has_played = UserScore.objects.filter(
            user=request.user,
            is_daily=True,
            created_at__date=today
        ).exists()

        return {"has_played_daily": has_played}

    return {"has_played_daily": False}