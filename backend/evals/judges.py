"""Judge-model adapters for the faithfulness harness (docs/evaluation.md §4).

A judge is a ``judge_fn(prompt) -> str`` returning the model's raw text. It MUST be a
different / at-least-as-strong model than the generator (Llama generates → Claude judges)
to avoid self-preference bias. Importing this module builds a client and needs a key, so
offline tests do not import it.

**Claude judge (recommended for the final evaluation).** Install ``anthropic``
and use:

    import anthropic
    _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    def claude_judge(prompt: str) -> str:
        msg = _client.messages.create(
            model="claude-opus-4-8", max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

Then: ``evaluate_faithfulness(pairs, claude_judge)``.
"""
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq

from ..config import GROQ_API_KEY


def make_groq_judge(model: str = "llama-3.3-70b-versatile"):
    """Build a judge_fn backed by a Groq model.

    Interim option only: pass a model DIFFERENT from the generator. Both-on-Groq still
    carries a self-preference caveat — prefer the Claude judge below for final numbers.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is required to construct a live Groq judge.")
    llm = ChatGroq(model=model, api_key=GROQ_API_KEY, temperature=0)

    def judge(prompt: str) -> str:
        return llm.invoke([HumanMessage(content=prompt)]).content

    return judge


def make_claude_judge(model: str = "claude-opus-4-8"):
    """Build a judge_fn backed by Claude (reads ANTHROPIC_API_KEY).

    Strongest judge condition: generator = Groq Llama, judge = Claude — a different and
    stronger model, avoiding self-preference bias (evaluation.md §4). Paid API.
    """
    import anthropic

    client = anthropic.Anthropic()

    def judge(prompt: str) -> str:
        msg = client.messages.create(
            model=model, max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    return judge


def make_gemini_judge(model: str = "gemini-2.5-flash"):
    """Build a judge_fn backed by Gemini (reads GOOGLE_API_KEY; free tier suffices).

    Default judge for the evaluation: cross-family (Google judges Meta-Llama outputs),
    no self-preference, zero cost at eval scale.
    """
    import os

    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(model=model, google_api_key=os.environ["GOOGLE_API_KEY"],
                                 temperature=0)

    def judge(prompt: str) -> str:
        return llm.invoke([HumanMessage(content=prompt)]).content

    return judge
