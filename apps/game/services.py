def _remove_live(lives: dict) -> dict:
    for key, value in reversed(list(lives.items())):
        if value is True:
            lives[key] = not lives[key]
            break
    return lives