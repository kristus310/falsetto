def _remove_life(lives: dict) -> dict:
    for key, value in reversed(list(lives.items())):
        if value is True:
            lives[key] = not lives[key]
            break
    return lives