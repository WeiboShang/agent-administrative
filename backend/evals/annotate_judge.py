"""Terminal annotator for the judge-validation labels (docs/evaluation.md §4).

    python -m backend.evals.annotate_judge          # label from where you left off
    python -m backend.evals.annotate_judge --review # re-read what you already labelled

Editing the JSONL by hand means reading 25-turn threads escaped onto one line. This renders
each item, shows the claims the judges extracted from the summary, and takes one keypress.
It **saves after every answer**, so stopping halfway costs nothing.

The question for each item is the one the judge answered:

    does the SUMMARY state anything the THREAD does not support?

y = yes, something is unsupported (``human_supported = true``)
n = no, every claim is grounded  (``human_supported = false``)

Note on ordering: items are presented in file order, NOT disagreement-first. Labelling only
the items the judges disagreed on would sample exactly where the judge is least certain and
inflate the disagreement rate — κ needs an unbiased subset. Disagreements are marked inline
so you can see them, not so you can cherry-pick them.
"""
import json
import os
import sys

LABEL_PATH = "data/eval_datasets/judge_labelling.jsonl"

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
RED, GREEN, YELLOW, CYAN = "\033[31m", "\033[32m", "\033[33m", "\033[36m"


def _judge_names(rows: list[dict]) -> list[str]:
    return sorted({k[len("judge_"):] for r in rows for k in r if k.startswith("judge_")})


def _load() -> list[dict]:
    if not os.path.exists(LABEL_PATH):
        sys.exit(f"{LABEL_PATH} not found — run `run_judge_validation judge` first")
    with open(LABEL_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _save(rows: list[dict]) -> None:
    tmp = LABEL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, LABEL_PATH)          # atomic: a crash mid-write cannot truncate labels


def _render(row: dict, names: list[str], idx: int, total: int) -> None:
    os.system("clear" if os.name != "nt" else "cls")   # noqa: S605 — fixed literal
    done = "labelled" if isinstance(row.get("human_supported"), bool) else "unlabelled"
    print(f"{BOLD}Item {row['i'] + 1} / {total}{RESET}  {DIM}({idx} left · {done}){RESET}\n")

    print(f"{BOLD}{CYAN}THREAD (the source of truth){RESET}")
    for line in row["source"].split("\n"):
        print(f"  {DIM}{line}{RESET}")

    print(f"\n{BOLD}{CYAN}SUMMARY (what the agent wrote){RESET}")
    for line in row["output"].split("\n"):
        if line.strip():
            print(f"  {line}")

    print(f"\n{BOLD}{CYAN}CLAIMS the judges pulled out of that summary{RESET}")
    seen: dict[str, list[str]] = {}
    for name in names:
        for c in row.get(f"claims_{name}", []):
            text = str(c.get("claim", "")).strip()
            if text:
                mark = f"{GREEN}supported{RESET}" if c.get("supported") is True \
                    else f"{RED}UNSUPPORTED{RESET}"
                seen.setdefault(text, []).append(f"{name.split('/')[-1]}:{mark}")
    for text, marks in seen.items():
        print(f"  • {text}\n      {DIM}{' · '.join(marks)}{RESET}")

    verdicts = {n: row.get(f"judge_{n}") for n in names}
    if len(set(verdicts.values())) > 1:
        print(f"\n  {YELLOW}⚠ the judges DISAGREED on this item{RESET}")
    print(f"  {DIM}judge verdicts (has unsupported claim): "
          f"{', '.join(f'{n.split(chr(47))[-1]}={v}' for n, v in verdicts.items())}{RESET}")


def main() -> None:
    review = "--review" in sys.argv
    rows = _load()
    names = _judge_names(rows)
    todo = [r for r in rows
            if review or not isinstance(r.get("human_supported"), bool)]

    if not todo:
        n = sum(1 for r in rows if isinstance(r.get("human_supported"), bool))
        print(f"all {n}/{len(rows)} items already labelled — "
              "run `python -m backend.evals.run_judge_validation score`")
        return

    print(f"{len(todo)} item(s) to label. y = a claim is unsupported · n = all grounded · "
          "s = skip · q = save and quit\n")
    input("press Enter to start… ")

    for k, row in enumerate(todo):
        while True:
            _render(row, names, len(todo) - k, len(rows))
            print(f"\n{BOLD}Does the SUMMARY state anything the THREAD does not support?"
                  f"{RESET}")
            ans = input("  [y]es / [n]o / [s]kip / [q]uit > ").strip().lower()
            if ans in ("y", "n", "s", "q"):
                break
        if ans == "q":
            break
        if ans == "s":
            continue
        row["human_supported"] = (ans == "y")
        _save(rows)                                    # save after every answer

    labelled = sum(1 for r in rows if isinstance(r.get("human_supported"), bool))
    print(f"\nsaved → {LABEL_PATH}  ({labelled}/{len(rows)} labelled)")
    if labelled:
        print("next: python -m backend.evals.run_judge_validation score")


if __name__ == "__main__":  # pragma: no cover
    main()
