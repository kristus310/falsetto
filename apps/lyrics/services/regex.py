import re

_BRACKET_VARIANT_REGEX = re.compile(
    r"[\(\[]"
    r"[^\)\]]*"
    r"(live|acoustic|remix|remaster(?:ed)?|re-?master(?:ed)?|demo|instrumental|cover|karaoke"
    r"|version|edit|mix|session|radio|medley|tribute|reprise|interlude|bonus"
    r"|intro|outro|ft\.?|feat\.?|single|ep\b|album\b"
    r"|en\s+vivo|ao\s+vivo|directo|unplugged"
    r"|explicit|clean|deluxe|expanded|re-?recorded"
    r"|re-?issue|anniversary|parody)"
    r"[^\)\]]*"
    r"[\)\]]",
    re.IGNORECASE,
)

_DASH_SUFFIX_RE = re.compile(
    r"\s+-\s+"
    r"(single|ep\b|re-?master(?:ed)?|remix|live|acoustic|demo"
    r"|radio\s+edit|album\s+version|bonus\s+track|instrumental"
    r"|[0-9]{4}(\s+-?)?\s+re-?master(?:ed)?(\s+version)?"
    r"|mono\s+version|stereo\s+version|expanded\s+edition"
    r"|original(\s+\S+)?\s+version(\s+\d{4})?"
    r"|original"
    r"|en\s+vivo|ao\s+vivo|directo|unplugged)"
    r"\s*$",
    re.IGNORECASE,
)

_FEAT_REGEX = re.compile(r"\s*[\(\[](feat|ft)\.?[^\)\]]*[\)\]]", re.IGNORECASE)

_PUNCT_REGEX = re.compile(r"[^\w\s']")