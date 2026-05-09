from django import forms

class LyricsGuessForm(forms.Form):
    guess = forms.CharField(max_length=255)