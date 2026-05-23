from django import forms

class LyricsGuessForm(forms.Form):
    guess = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={"required": "Please enter a guess."},
    )