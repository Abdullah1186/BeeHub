"""Eval runner.

Four tiers, designed so the DEFAULT cost of running evals is $0:

  Tier 0 — pure logic, no API. Runs on every commit.
  Tier 1 — cassettes: recorded responses keyed by (prompt_hash, case_id).
           An unchanged prompt replays from disk. This is the whole trick;
           if PRs cost money, evals get switched off within a month.
  Tier 2 — live, only when skills/ or config/models.yaml changed.
  Tier 3 — manual, full suite, for promoting a prompt.

A changed skill file changes its prompt_hash, which misses every cassette for
that skill and forces a re-record. That is the intended coupling: you cannot
silently tune a prompt without re-measuring it.

    python evals/runner.py --suite short_answer            # replay
    python evals/runner.py --suite short_answer --live     # spend money
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.grading.score import compute_score  # noqa: E402
from app.skills.loader import load_skill  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent
CASES_DIR = EVALS_DIR / "cases"
CASSETTES_DIR = EVALS_DIR / "cassettes"
BASELINES_DIR = EVALS_DIR / "baselines"


class MissingCassette(RuntimeError):
    """Replay was requested but no recording exists for this prompt version."""


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    detail: str
    cost_usd: float = 0.0
    replayed: bool = False


@dataclass
class SuiteResult:
    suite: str
    prompt_hash: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def cost(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def cassette_path(prompt_hash: str, case_id: str) -> Path:
    key = hashlib.sha256(f"{prompt_hash}:{case_id}".encode()).hexdigest()[:24]
    return CASSETTES_DIR / f"{key}.json"


def load_cassette(prompt_hash: str, case_id: str) -> dict | None:
    path = cassette_path(prompt_hash, case_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_cassette(prompt_hash: str, case_id: str, payload: dict) -> None:
    CASSETTES_DIR.mkdir(parents=True, exist_ok=True)
    path = cassette_path(prompt_hash, case_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _call(skill_id: str, user_content: str, case_id: str, live: bool) -> tuple[dict | None, float, bool]:
    """Return (parsed_dict, cost, replayed). Replays unless --live."""
    skill = load_skill(skill_id)
    cached = load_cassette(skill.prompt_hash, case_id)
    if cached is not None and not live:
        return cached, 0.0, True

    if not live:
        # Replay mode with no cassette: the prompt changed and was never
        # re-measured. Refuse rather than calling the API (which would spend
        # money CI is not authorised to spend) and rather than passing (which
        # would let an unmeasured prompt through).
        raise MissingCassette(
            f"no cassette for {case_id} at prompt_hash {skill.prompt_hash[:12]}. "
            f"The '{skill_id}' prompt changed since the cassettes were recorded. "
            f"Re-record with: make eval-live"
        )

    from app.ai.client import call_skill

    result = call_skill(skill_id, user_content)
    if result.status != "ok":
        return None, result.cost_usd, False

    payload = result.parsed.model_dump(mode="json")
    save_cassette(skill.prompt_hash, case_id, payload)
    return payload, result.cost_usd, False


# --- short answer ---------------------------------------------------------


def run_short_answer(live: bool) -> SuiteResult:
    spec = yaml.safe_load((CASES_DIR / "short_answer.yaml").read_text(encoding="utf-8"))
    skill = load_skill("grade-short-answer")
    suite = SuiteResult(suite="short_answer", prompt_hash=skill.prompt_hash)

    for case in spec["cases"]:
        user = json.dumps(
            {
                "question": spec["question"],
                "key_points": spec["key_points"],
                "learner_answer": case["answer"],
                "source_passage": spec["passage"],
            },
            ensure_ascii=False,
        )
        parsed, cost, replayed = _call("grade-short-answer", user, case["id"], live)
        if parsed is None:
            suite.results.append(CaseResult(case["id"], False, "API call failed", cost))
            continue

        from app.schemas.grading import ShortAnswerGrade

        grade = ShortAnswerGrade.model_validate(parsed)
        score = compute_score(grade)

        if "expect_gradable" in case and case["expect_gradable"] is False:
            ok = not grade.gradable
            detail = f"gradable={grade.gradable} (want False)"
        elif "expect_min_score" in case:
            ok = score.final_score >= case["expect_min_score"]
            detail = f"score={score.final_score:.2f} (want >= {case['expect_min_score']})"
        elif "expect_max_score" in case:
            ok = score.final_score <= case["expect_max_score"]
            detail = f"score={score.final_score:.2f} (want <= {case['expect_max_score']})"
        else:
            ok, detail = False, "case declares no expectation"

        suite.results.append(CaseResult(case["id"], ok, detail, cost, replayed))
    return suite


# --- error tagging --------------------------------------------------------


def _overlap(a: str, b: str) -> float:
    """Character-level overlap, for span matching."""
    a, b = a.strip(), b.strip()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    shared = sum((min(a.count(c), b.count(c)) for c in set(a)))
    return shared / max(len(a), len(b))


def run_error_tagging(live: bool) -> SuiteResult:
    spec = yaml.safe_load((CASES_DIR / "error_tagging.yaml").read_text(encoding="utf-8"))
    skill = load_skill("grade-short-answer")
    suite = SuiteResult(suite="error_tagging", prompt_hash=skill.prompt_hash)

    for case in spec["cases"]:
        # Tagging runs through the grading skill with a trivial key point, so
        # the tagger sees the same prompt it will see in production.
        user = json.dumps(
            {
                "question": "اكتب جملة صحيحة.",
                "key_points": [
                    {"id": "kp1", "text": "Any grammatical Arabic sentence.",
                     "source_quote": case["sentence"]}
                ],
                "learner_answer": case["sentence"],
                "source_passage": case["sentence"],
            },
            ensure_ascii=False,
        )
        parsed, cost, replayed = _call("grade-short-answer", user, case["id"], live)
        if parsed is None:
            suite.results.append(CaseResult(case["id"], False, "API call failed", cost))
            continue

        tags = parsed.get("language_errors", [])

        if case.get("expect_no_errors"):
            # FALSE POSITIVE check — the one that keeps the metrics honest.
            ok = len(tags) == 0
            detail = "no tags" if ok else f"FALSE POSITIVE: {[t['category'] for t in tags]}"
        else:
            hit = next(
                (
                    t for t in tags
                    if t["category"] == case["category"]
                    and _overlap(t["span"], case["span"]) >= 0.5
                ),
                None,
            )
            if hit:
                sub_ok = hit["subcategory"] == case["subcategory"]
                ok = True
                detail = (
                    f"found {hit['category']}/{hit['subcategory']}"
                    + ("" if sub_ok else f" (want subcategory {case['subcategory']})")
                )
            else:
                ok = False
                found = [f"{t['category']}/{t['subcategory']}:{t['span']}" for t in tags]
                detail = f"MISSED {case['category']}/{case['subcategory']} on {case['span']!r}; got {found}"

        suite.results.append(CaseResult(case["id"], ok, detail, cost, replayed))
    return suite


# --- reporting ------------------------------------------------------------


def report(suite: SuiteResult, verbose: bool) -> None:
    print(f"\n{'=' * 70}")
    print(f"{suite.suite}  (prompt {suite.prompt_hash[:12]})")
    print("=" * 70)

    for r in suite.results:
        if not r.passed or verbose:
            mark = "PASS" if r.passed else "FAIL"
            tag = " [replay]" if r.replayed else ""
            print(f"  {mark}  {r.case_id:38} {r.detail}{tag}")

    replayed = sum(1 for r in suite.results if r.replayed)
    print(f"\n  {suite.passed}/{suite.total} passed ({suite.pass_rate:.0%})")
    print(f"  {replayed} replayed from cassettes, {suite.total - replayed} live")
    print(f"  cost: ${suite.cost:.4f}")


def check_baseline(suite: SuiteResult) -> bool:
    """Compare against the recorded baseline for this prompt hash."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    path = BASELINES_DIR / f"{suite.suite}.json"
    current = {
        "prompt_hash": suite.prompt_hash,
        "pass_rate": round(suite.pass_rate, 4),
        "cases": {r.case_id: r.passed for r in suite.results},
    }

    if not path.exists():
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")
        print(f"  baseline recorded ({suite.pass_rate:.0%})")
        return True

    baseline = json.loads(path.read_text(encoding="utf-8"))
    drop = baseline["pass_rate"] - suite.pass_rate
    regressed = [
        cid for cid, was in baseline["cases"].items()
        if was and not current["cases"].get(cid, False)
    ]

    ok = True
    if drop > 0.05:
        print(f"  REGRESSION: pass rate fell {drop:.0%} "
              f"({baseline['pass_rate']:.0%} -> {suite.pass_rate:.0%})")
        ok = False
    # Catches a fix and a break cancelling out in the aggregate.
    if regressed:
        print(f"  CASES REGRESSED: {regressed}")
        ok = False
    if ok:
        print(f"  no regression vs baseline ({baseline['pass_rate']:.0%})")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="BeeHub evals")
    parser.add_argument("--suite", choices=["short_answer", "error_tagging", "all"],
                        default="all")
    parser.add_argument("--live", action="store_true",
                        help="call the API and re-record cassettes (costs money)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    suites = ["short_answer", "error_tagging"] if args.suite == "all" else [args.suite]
    runners = {"short_answer": run_short_answer, "error_tagging": run_error_tagging}

    all_ok = True
    total_cost = 0.0
    for name in suites:
        try:
            suite = runners[name](args.live)
        except MissingCassette as exc:
            print(f"\n{'=' * 70}\n{name}: CANNOT REPLAY\n{'=' * 70}")
            print(f"  {exc}")
            return 2
        report(suite, args.verbose)
        total_cost += suite.cost
        if args.update_baseline:
            (BASELINES_DIR / f"{name}.json").unlink(missing_ok=True)
        all_ok &= check_baseline(suite)

    print(f"\ntotal cost: ${total_cost:.4f}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
