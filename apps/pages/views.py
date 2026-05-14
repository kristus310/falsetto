from django.shortcuts import render
from django.http import HttpRequest, HttpResponse

def about(request: HttpRequest) -> HttpResponse:
    return render(request, "pages/about.html")

def contact(request: HttpRequest) -> HttpResponse:
    return render(request, "pages/contact.html")

def legal(request: HttpRequest) -> HttpResponse:
    return render(request, "pages/legal.html")
