from django.http import HttpRequest, HttpResponse

def theme_processor(request: HttpRequest) -> HttpResponse:
    return {
        "theme": request.session.get("theme", "night")
    }