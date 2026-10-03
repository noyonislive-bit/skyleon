from django.http import HttpResponse
from django.shortcuts import render


def home(request):
    return render(request, "website/home.html")


def stub(request, **kwargs):
    return HttpResponse("Coming soon")
