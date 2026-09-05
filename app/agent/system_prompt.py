"""System prompt 加载与动态注入。"""

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_system_prompt() -> str:
    prompt = (PROMPT_DIR / "system.md").read_text(encoding="utf-8")
    plan = PROMPT_DIR / "plan.md"
    if plan.exists():
        prompt += "\n\n" + plan.read_text(encoding="utf-8")
    return prompt


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")
