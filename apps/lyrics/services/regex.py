import re

_BRACKET_VARIANT_REGEX = re.compile(
    r"[\(\[]"
    r"[^\)\]]*"
    r"(live|acoustic|remix|remaster(?:ed)?|demo|instrumental|cover|karaoke"
    r"|version|edit|mix|session|radio|medley|tribute|reprise|interlude|bonus"
    r"|intro|outro|ft\.?|feat\.?|single|ep\b|album\b)"
    r"[^\)\]]*"
    r"[\)\]]",
    re.IGNORECASE,
)

_DASH_SUFFIX_REGEX = re.compile(
    r"\s+-\s+"
    r"(single|ep\b|remaster(?:ed)?|remix|live|acoustic|demo"
    r"|radio\s+edit|album\s+version|bonus\s+track|instrumental"
    r"|[0-9]{4}\s+remaster(?:ed)?)"
    r"\s*$",
    re.IGNORECASE,
)

_FEAT_REGEX = re.compile(r"\s*[\(\[](feat|ft)\.?[^\)\]]*[\)\]]", re.IGNORECASE)

_PUNCT_REGEX = re.compile(r"[^\w\s']")