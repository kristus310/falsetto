from django.shortcuts import render

def about(request):
    return render(request, "pages/about.html")

def contact(request):
    return render(request, "pages/contact.html")

def legal(request):
    return render(request, "pages/legal.html")
