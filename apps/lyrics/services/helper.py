import re
from . import regex

def _is_variant(name: str) -> bool:
    return bool(
        regex._BRACKET_VARIANT_REGEX.search(name)
        or regex._DASH_SUFFIX_REGEX.search(name)
        or regex._FEAT_REGEX.search(name)
    )

def _normalize_title(name: str) -> str:
    name = regex._BRACKET_VARIANT_REGEX.sub("", name)
    name = regex._DASH_SUFFIX_REGEX.sub("", name)
    name = regex._FEAT_REGEX.sub("", name)
    name = regex._PUNCT_REGEX.sub("", name)
    return re.sub(r"\s+", " ", name).strip().lower()