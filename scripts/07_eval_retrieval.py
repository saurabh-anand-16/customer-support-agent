"""
07_eval_retrieval.py - score policy search on the labelled questions (phase 3d, built in phase 10 Part A).

    python scripts/07_eval_retrieval.py                          # the five profiles that can run
    python scripts/07_eval_retrieval.py --profiles baseline_bm25 hybrid
    python scripts/07_eval_retrieval.py --variants               # embedding model and chunk size, on the best profile
    python scripts/07_eval_retrieval.py --calibrate hybrid       # score spread and threshold sweep for one profile

What it does, per profile: for every reviewed row of data/evals/retrieval_questions.csv it runs the retriever
(and fuser and reranker the profile names) WITHOUT the no-match rule, and keeps the ranked passages and each
retriever's best score. The no-match rule is then applied afterwards at any threshold, so one run can be scored
at the config thresholds and swept. Nothing in agent/ is changed; the stages are the real ones.

Measures (each reported as "n of N"): hit@1, hit@3, hit@5, mean reciprocal rank (answerable rows only),
no-match accuracy (answerable rows that got passages + unanswerable rows that got none), the out-of-scope
guard (any forbidden file in the results), average latency, and model or embedding calls.

Offline profiles (baseline_bm25) give identical numbers on every run. Profiles that embed a question or call
a chat model use the real service and cached vectors; their ranking is stable but not guaranteed identical.
The script never prints keys.
"""
import argparse
import json
import sys
import time
import tomllib
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import csv                                                               # noqa: E402

from agent.rag import load_config, load_documents                        # noqa: E402
from agent.rag.chunkers import chunk_documents                           # noqa: E402
from agent.rag.filters import Filter                                     # noqa: E402
from agent.rag.nomatch import NoMatchRule                                # noqa: E402
from agent.rag.pipeline import Pipeline                                  # noqa: E402
from agent.rag.retrievers import uses_index                              # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "evals" / "retrieval_questions.csv"
RESULTS_DIR = ROOT / "data" / "evals" / "results"
PROFILES = ["baseline_bm25", "vector_only", "hybrid", "hybrid_cross_encoder", "hybrid_llm_rerank"]
TOP_K = 5
VARIANTS_FILE = ROOT / "data" / "evals" / "retrieval_variants.toml"


# --- the answer key ---------------------------------------------------------------------------
def load_questions(path=DEFAULT_CSV, reviewed_only=True) -> tuple[list[dict], int]:
    """(rows that count, number of rows left out because they are not reviewed)."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    kept = [r for r in rows if r.get("reviewed", "").strip().lower() == "yes"] if reviewed_only else rows
    return kept, len(rows) - len(kept)


def parse_expected(text: str) -> list[list[tuple[str, str]]]:
    """'a.md::H1 | b.md::H2 && c.md::H3' -> [[(a, H1), (b, H2)], [(c, H3)]]: every group must be found, any one inside a group counts."""
    text = (text or "").strip()
    if not text or text == "NONE":
        return []
    groups = []
    for group in text.split(" && "):
        options = []
        for option in group.split(" | "):
            file, _, heading = option.strip().partition("::")
            options.append((file.strip(), heading.strip()))
        groups.append(options)
    return groups


def parse_forbidden(text: str) -> list[str]:
    return [f.strip() for f in (text or "").split("|") if f.strip()]


def result_matches(result: dict, file: str, heading: str, separator: str = " > ") -> bool:
    """A passage answers (file, heading) when it is from that page and the heading is one step of its heading path."""
    return result["source_file"] == file and heading in result["heading_path"].split(separator)


def group_found_at(results: list[dict], group, separator=" > ") -> int | None:
    """1-based position of the first passage matching any option of the group, or None."""
    for position, result in enumerate(results, start=1):
        if any(result_matches(result, f, h, separator) for f, h in group):
            return position
    return None


# --- scoring ----------------------------------------------------------------------------------
def best_scores_rule(cfg, record) -> bool:
    """Would the no-match rule let this record through? Uses the real NoMatchRule on the stored best scores."""
    if record["n_hits"] == 0:
        stubs = []
    else:
        retrievers = {}
        if record["bm25_best"] is not None:
            retrievers["bm25"] = {"score": record["bm25_best"]}
        if record["vector_best"] is not None:
            retrievers["vector"] = {"score": record["vector_best"]}
        stubs = [SimpleNamespace(provenance={"retrievers": retrievers})] * record["n_hits"]
    return NoMatchRule(cfg).decide(cfg.retrieval.strategy, stubs).matched


def score(records: list[dict], cfg, separator=" > ") -> dict:
    """All measures for one profile's records at cfg's thresholds. Pure: no search happens here."""
    by_cat = defaultdict(lambda: {"rows": 0, "answerable": 0, "hit1": 0, "hit3": 0, "hit5": 0, "rr": 0.0,
                                  "matched": 0, "nomatch_ok": 0, "guard_breaks": 0})
    forbidden_hits = []
    for rec in records:
        c = by_cat[rec["category"]]
        c["rows"] += 1
        groups = parse_expected(rec["expected"])
        matched = best_scores_rule(cfg, rec)
        c["matched"] += matched
        if groups:                                    # answerable
            c["answerable"] += 1
            found = [group_found_at(rec["results"], g, separator) for g in groups]
            # a question counts at depth k when EVERY group is found within the first k passages
            for k, key in ((1, "hit1"), (3, "hit3"), (5, "hit5")):
                c[key] += all(p is not None and p <= k for p in found)
            first = [p for p in found if p is not None]
            c["rr"] += 1 / min(first) if first else 0.0
            c["nomatch_ok"] += matched                # an answerable question should get passages
        else:
            c["nomatch_ok"] += not matched            # an unanswerable one should get none
        bad = [r["source_file"] for r in rec["results"] if r["source_file"] in parse_forbidden(rec["forbidden_files"])]
        if bad and matched:                           # forbidden pages only matter when they would be shown
            c["guard_breaks"] += 1
            forbidden_hits.append({"id": rec["id"], "files": sorted(set(bad))})
    total = defaultdict(float)
    for c in by_cat.values():
        for key, value in c.items():
            total[key] += value
    return {"by_category": {k: dict(v) for k, v in sorted(by_cat.items())}, "total": dict(total),
            "forbidden_hits": forbidden_hits}


def sweep(records: list[dict], cfg, retriever: str) -> list[dict]:
    """For one retriever's score, every cut-off that changes an answer, with kept answerable / refused unanswerable counts."""
    key = f"{retriever}_best"
    values = sorted({r[key] for r in records if r[key] is not None})
    cuts = [0.0] + [(a + b) / 2 for a, b in zip(values, values[1:])] + ([values[-1] + 1e-6] if values else [])
    field = "bm25_min_score" if retriever == "bm25" else "vector_min_score"
    out = []
    for cut in cuts:
        trial = replace(cfg, no_match=replace(cfg.no_match, **{field: cut}))
        answerable = unanswerable = kept = refused = gap_kept = gap_n = 0
        for rec in records:
            ok = best_scores_rule(trial, rec)
            if parse_expected(rec["expected"]):
                answerable += 1
                kept += ok
                if rec["category"] == "policy_gap":
                    gap_n += 1
                    gap_kept += ok
            else:
                unanswerable += 1
                refused += not ok
        out.append({"cut": round(cut, 4), "answerable_kept": kept, "answerable": answerable,
                    "unanswerable_refused": refused, "unanswerable": unanswerable,
                    "policy_gap_kept": gap_kept, "policy_gap": gap_n})
    return out


# --- running a profile --------------------------------------------------------------------------
def make_pipeline(cfg, chunks, store=None, embedder=None):
    return Pipeline.build(cfg, chunks, store, embedder)


def run_profile(cfg, rows, chunks=None, store=None, embedder=None, say=print) -> tuple[list[dict], dict]:
    """Search every row with no no-match rule. Returns (records, cost) where cost counts calls and time."""
    chunks = chunks or chunk_documents(cfg, load_documents(cfg))
    pipeline = make_pipeline(cfg, chunks, store, embedder)
    flt = Filter.from_config(cfg, False)
    embedder = getattr(pipeline.retriever, "embedder", None) or embedder
    before = embedder.embedded_count if embedder is not None else 0
    records, started, model_calls = [], time.perf_counter(), 0
    for row in rows:
        t0 = time.perf_counter()
        hits = pipeline.retriever.retrieve(row["question"], cfg.retrieval.candidate_k, flt)
        bests = {}
        for name in ("bm25", "vector"):
            scores = [h.provenance["retrievers"][name]["score"] for h in hits if name in h.provenance["retrievers"]]
            bests[name] = max(scores) if scores else None
        pool = hits[:cfg.rerank.candidates]
        status = "ok"
        try:
            ranked = pipeline.reranker.rerank(row["question"], pool)
            if cfg.rerank.method != "none":
                model_calls += 1 if cfg.rerank.method == "llm" else 0
            if pipeline.reranker.limits_output:
                ranked = ranked[:cfg.rerank.top_n]
        except Exception as err:                       # a reranker failure keeps the fused order, as in the pipeline
            ranked, status = [(h, None) for h in pool], f"failed: {type(err).__name__}: {str(err)[:120]}"
        ranked = ranked[:TOP_K]
        records.append({
            "id": row["id"], "category": row["category"], "expected": row["expected"],
            "forbidden_files": row.get("forbidden_files", ""), "n_hits": len(hits),
            "bm25_best": bests["bm25"], "vector_best": bests["vector"], "rerank_status": status,
            "results": [{"source_file": h.source_file, "heading_path": h.heading_path,
                         "score": (s if s is not None else h.score)} for h, s in ranked],
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1)})
    failed = [r["rerank_status"] for r in records if r["rerank_status"] != "ok"]
    if failed and len(failed) == len(records):         # a profile whose reranker never ran is not a result: its numbers would equal the fused list's
        raise RuntimeError(f"the reranker failed on every question ({failed[0]})")
    cost = {"seconds": round(time.perf_counter() - started, 2), "questions": len(rows),
            "embedding_texts_sent": (embedder.embedded_count - before) if embedder is not None else 0,
            "rerank_model_calls": model_calls,
            "mean_latency_ms": round(sum(r["latency_ms"] for r in records) / max(1, len(records)), 1),
            "rerank_failures": sum(1 for r in records if r["rerank_status"] != "ok")}
    return records, cost


def build_memory_pipeline_parts(cfg):
    """A throwaway in-memory index for a variant config (other chunk size or embedding model). The real index is not touched."""
    from agent.rag.embedders import get_embedder
    from agent.rag.index import build_index
    from agent.rag.stores import get_store
    cfg = replace(cfg, store=replace(cfg.store, kind="memory"))
    chunks = chunk_documents(cfg, load_documents(cfg))
    embedder, store = get_embedder(cfg), get_store(cfg)
    report = build_index(cfg, chunks, embedder, store, meta_path=Path(RESULTS_DIR) / "_variant_meta.json")
    return cfg, chunks, store, embedder, report


# --- printing -------------------------------------------------------------------------------------
def frac(n, d) -> str:
    return f"{int(n)} of {int(d)}"


def format_profile(name: str, result: dict, cost: dict, reviewed: int, unreviewed: int) -> str:
    t = result["total"]
    lines = [f"== {name}  ({reviewed} reviewed rows; {unreviewed} not reviewed and left out) ==",
             f"  hit@1 {frac(t['hit1'], t['answerable'])}   hit@3 {frac(t['hit3'], t['answerable'])}   "
             f"hit@5 {frac(t['hit5'], t['answerable'])}   MRR {t['rr'] / max(1, t['answerable']):.3f} "
             f"(answerable rows only)",
             f"  no-match accuracy {frac(t['nomatch_ok'], t['rows'])}   out-of-scope guard breaks {int(t['guard_breaks'])}",
             f"  latency {cost['mean_latency_ms']} ms per question; embedding texts sent {cost['embedding_texts_sent']}; "
             f"rerank model calls {cost['rerank_model_calls']}; reranker failures {cost['rerank_failures']}; "
             f"total {cost['seconds']} s",
             "  by category:   rows  hit@1  hit@3  hit@5   nomatch-ok"]
    for cat, c in result["by_category"].items():
        if c["answerable"]:
            lines.append(f"    {cat:<22}{int(c['rows']):>4}  {int(c['hit1']):>2}/{int(c['answerable']):<3} {int(c['hit3']):>2}/{int(c['answerable']):<3} "
                         f"{int(c['hit5']):>2}/{int(c['answerable']):<3}   {int(c['nomatch_ok'])}/{int(c['rows'])}")
        else:
            lines.append(f"    {cat:<22}{int(c['rows']):>4}   (no answer expected)               {int(c['nomatch_ok'])}/{int(c['rows'])}")
    for h in result["forbidden_hits"]:
        lines.append(f"  FORBIDDEN FILE SHOWN: {h['id']} {h['files']}")
    return "\n".join(lines)


def distribution(records, retriever: str) -> str:
    """Min, median and max of the best score per group of rows, so the overlap can be seen."""
    key = f"{retriever}_best"
    groups = {"answerable (not gap)": lambda r: parse_expected(r["expected"]) and r["category"] != "policy_gap",
              "policy_gap": lambda r: r["category"] == "policy_gap",
              "unanswerable_related": lambda r: r["category"] == "unanswerable_related",
              "scope_guard": lambda r: r["category"] == "scope_guard",
              "off_topic": lambda r: r["category"] == "off_topic"}
    lines = [f"  best {retriever} score by group (min / median / max, rows with no result count as none):"]
    for label, test in groups.items():
        vals = sorted(r[key] for r in records if test(r) and r[key] is not None)
        none = sum(1 for r in records if test(r) and r[key] is None)
        if vals:
            lines.append(f"    {label:<24} n={len(vals) + none:<3} {vals[0]:.3f} / {vals[len(vals) // 2]:.3f} / {vals[-1]:.3f}   (none: {none})")
        else:
            lines.append(f"    {label:<24} n={none:<3} all none")
    return "\n".join(lines)


def choose_cut(table: list[dict]) -> dict:
    """The cut-off with the most right answers (kept answerable + refused unanswerable); ties go to keeping answerable rows."""
    return max(table, key=lambda t: (t["answerable_kept"] + t["unanswerable_refused"], t["answerable_kept"], -t["cut"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--profiles", nargs="*", default=None)
    parser.add_argument("--variants", metavar="PROFILE", nargs="?", const="hybrid", default=None,
                        help="run embedding-model and chunk-size variations of this profile (default hybrid)")
    parser.add_argument("--calibrate", metavar="PROFILE", default=None, help="score spread and threshold sweep for this profile")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    rows, unreviewed = load_questions(args.csv)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{len(rows)} reviewed questions used; {unreviewed} not reviewed and left out.\n")
    out = {"reviewed_rows": len(rows), "unreviewed_rows": unreviewed, "profiles": {}}

    if args.calibrate:
        cfg = load_config(args.calibrate)
        records, cost = run_profile(cfg, rows)
        print(f"profile {cfg.profile}: thresholds now bm25 {cfg.no_match.bm25_min_score}, vector {cfg.no_match.vector_min_score}, "
              f"hybrid_require {cfg.no_match.hybrid_require}")
        for r in ("bm25", "vector"):
            if any(rec[f"{r}_best"] is not None for rec in records):
                print(distribution(records, r))
                table = sweep(records, cfg, r)
                best = choose_cut(table)
                print(f"  {r} sweep, only the cut-offs that are best for their number of kept answerable rows "
                      f"(cut, answerable kept, unanswerable refused, policy_gap kept):")
                frontier = {}
                for t in table:                       # per kept-count, the cut-off that refuses the most
                    if t["answerable_kept"] not in frontier or t["unanswerable_refused"] >= frontier[t["answerable_kept"]]["unanswerable_refused"]:
                        frontier[t["answerable_kept"]] = t
                for t in sorted(frontier.values(), key=lambda x: x["cut"]):
                    if t["answerable_kept"] < best["answerable_kept"] - 12:
                        continue
                    mark = "  <- best" if t["cut"] == best["cut"] else ""
                    print(f"    {t['cut']:>8}  {t['answerable_kept']}/{t['answerable']}  {t['unanswerable_refused']}/{t['unanswerable']}  "
                          f"{t['policy_gap_kept']}/{t['policy_gap']}{mark}")
        path = Path(args.output) if args.output else RESULTS_DIR / f"retrieval_calibration_{cfg.profile}.json"
        path.write_text(json.dumps({"profile": cfg.profile, "cost": cost, "records": records}, indent=1) + "\n", encoding="utf-8")
        print(f"\nwrote {path}")
        return 0

    started = time.perf_counter()
    if args.variants:
        base = load_config(args.variants)
        plan = []
        for v in tomllib.loads(VARIANTS_FILE.read_text(encoding="utf-8"))["variant"]:
            cfg = base
            if "embedding_model" in v:
                cfg = replace(cfg, embedding=replace(cfg.embedding, model=v["embedding_model"]))
            if "max_chars" in v:
                cfg = replace(cfg, chunking=replace(cfg.chunking, max_chars=v["max_chars"]))
            plan.append((v["label"], cfg))
        for label, cfg in plan:
            try:
                cfg2, chunks, store, embedder, report = build_memory_pipeline_parts(cfg)
                records, cost = run_profile(cfg2, rows, chunks, store, embedder)
                cost["index_texts_embedded"] = report.embedded
            except Exception as err:                       # never prints a key: the embedders scrub their messages
                print(f"== {label}: SKIPPED ({type(err).__name__}: {str(err)[:200]})\n")
                out["profiles"][label] = {"skipped": f"{type(err).__name__}: {str(err)[:200]}"}
                continue
            result = score(records, cfg2, cfg2.metadata.heading_path_separator)
            print(format_profile(label, result, cost, len(rows), unreviewed) + f"\n  chunks {len(chunks)}, index texts embedded now {report.embedded}\n")
            out["profiles"][label] = {"result": result, "cost": cost, "chunks": len(chunks)}
    else:
        for name in args.profiles or PROFILES:
            try:
                cfg = load_config(name)
                records, cost = run_profile(cfg, rows)
            except Exception as err:
                print(f"== {name}: SKIPPED ({type(err).__name__}: {str(err)[:200]})\n")
                out["profiles"][name] = {"skipped": f"{type(err).__name__}: {str(err)[:200]}"}
                continue
            result = score(records, cfg, cfg.metadata.heading_path_separator)
            print(format_profile(name, result, cost, len(rows), unreviewed) + "\n")
            out["profiles"][name] = {"result": result, "cost": cost,
                                     "thresholds": {"bm25_min_score": cfg.no_match.bm25_min_score,
                                                    "vector_min_score": cfg.no_match.vector_min_score,
                                                    "hybrid_require": cfg.no_match.hybrid_require}}
            (RESULTS_DIR / f"retrieval_records_{name}.json").write_text(json.dumps(records, indent=1) + "\n", encoding="utf-8")
    out["total_seconds"] = round(time.perf_counter() - started, 1)
    path = Path(args.output) if args.output else RESULTS_DIR / ("retrieval_variants.json" if args.variants else "retrieval_profiles.json")
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"total {out['total_seconds']} s; wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
