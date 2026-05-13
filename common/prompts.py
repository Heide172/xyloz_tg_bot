from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts"


@lru_cache(maxsize=64)
def load(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def render(name: str, **variables) -> str:
    text = load(name)
    return text.format(**variables) if variables else text


def reload_cache() -> None:
    load.cache_clear()
