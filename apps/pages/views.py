from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET
from django.utils.http import url_has_allowed_host_and_scheme

def about(request: HttpRequest) -> HttpResponse:
    return render(request, "pages/about.html")

def contact(request: HttpRequest) -> HttpResponse:
    return render(request, "pages/contact.html")

def legal(request: HttpRequest) -> HttpResponse:
    return render(request, "pages/legal.html")

@require_GET
def set_theme(request: HttpRequest) -> HttpResponse:
    origin_url = request.GET.get("next", "")
    is_safe = url_has_allowed_host_and_scheme(
        url=origin_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure()
    )
    if is_safe:
        safe_origin_url = origin_url
    else:
        safe_origin_url = "/"

    theme = request.session.get("theme", "night")
    if theme == "night":
        request.session["theme"] = "winter"
    else:
        request.session["theme"] = "night"

    return redirect(safe_origin_url)
