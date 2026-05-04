# src/generation/__init__.py
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt_file(filename: str) -> str:
    with (_PROMPTS_DIR / filename).open(encoding="utf-8") as f:
        return f.read()
