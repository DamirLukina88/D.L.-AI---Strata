"""Small text helpers."""


def slugify(s: str) -> str:
    """Lowercase; runs of characters that are not a-z or 0-9 become one '-'; no '-' at either end."""
    raise NotImplementedError


def is_anagram(a: str, b: str) -> bool:
    """True if a and b use the same letters the same number of times, ignoring case and anything not a letter."""
    raise NotImplementedError


def caesar(s: str, k: int) -> str:
    """Shift each ASCII letter k places, wrapping within its case; other characters unchanged.  k may be negative."""
    raise NotImplementedError


def rle_encode(s: str) -> str:
    """'aaab' -> '3a1b'.  Input is letters only."""
    raise NotImplementedError


def rle_decode(s: str) -> str:
    """The inverse of rle_encode ('12a' is twelve a's).  Malformed input such as 'a3' or '3' raises ValueError."""
    raise NotImplementedError


def word_freq(s: str) -> dict[str, int]:
    """Count words (runs of letters and apostrophes), lowercased."""
    raise NotImplementedError


def truncate(s: str, n: int) -> str:
    """s if it has at most n characters, else its first n-1 characters followed by '…'.  n < 1 raises ValueError."""
    raise NotImplementedError


def camel_to_snake(s: str) -> str:
    """'parseHTTPResponse' -> 'parse_http_response', 'userId' -> 'user_id'."""
    raise NotImplementedError


def snake_to_camel(s: str) -> str:
    """'user_id' -> 'userId'; leading, trailing and repeated underscores are dropped."""
    raise NotImplementedError


def common_prefix(words: list[str]) -> str:
    """The longest prefix shared by all words; '' for an empty list."""
    raise NotImplementedError
