#!/usr/bin/env python3
"""Monthly refresh for Cancer Biology Reviews.

For each topic: find review articles on PubMed, apply the quality gate, fill the slots
(1 pinned classic + the 2 most recent qualifying reviews), retire what is displaced or aged out,
then rebuild docs/index.html.

Safety: if PubMed does not answer properly for a topic, that topic is left exactly as it was
(nothing is retired on a failed run). The run exits with an error so GitHub flags it.

  python3 scripts/refresh.py                  normal run
  python3 scripts/refresh.py --dry-run        show what would change, write nothing
  python3 scripts/refresh.py --topic ferroptosis
  python3 scripts/refresh.py --today 2026-11-01
"""
import argparse
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import logic  # noqa: E402
import pubmed  # noqa: E402

NOT_TYPES = ('NOT ("retracted publication"[pt] OR "retraction of publication"[pt] OR "published erratum"[pt] OR '
             'comment[pt] OR editorial[pt] OR letter[pt] OR news[pt] OR "expression of concern"[pt])')


def load(rel, default):
    p = os.path.join(ROOT, rel)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(rel, obj):
    with open(os.path.join(ROOT, rel), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def build_term(topic, journals, cutoff_iso):
    jq = " OR ".join('"%s"[ta]' % j for j in journals)
    return ('(%s) AND (review[pt] OR "systematic review"[pt]) AND (%s) AND ("%s"[dp] : "3000"[dp]) '
            'AND hasabstract AND english[la] %s') % (topic["query"], jq, cutoff_iso.replace("-", "/"), NOT_TYPES)


def resolve_pinned(spec):
    """Find a pinned classic by DOI, PMID or exact title, and verify first author and year."""
    if spec.get("pmid"):
        ids = [str(spec["pmid"])]
    else:
        if spec.get("doi"):
            term = '"%s"[aid]' % spec["doi"]
        else:  # quoted phrase search misses hyphenated titles; match loosely, then verify author and year below
            term = "%s[ti]" % spec["title"] + (" AND %s[1au]" % spec["author"] if spec.get("author") else "")
        _, ids = pubmed.esearch(term, retmax=10)
    recs = pubmed.efetch(ids) if ids else {}
    for pid, rec in recs.items():
        if spec.get("author") and not rec["first_author"].lower().startswith(spec["author"].lower()):
            continue
        if spec.get("year") and rec["year"] != str(spec["year"]) and not rec["pubdate"].startswith(str(spec["year"])):
            continue
        return pid, rec
    raise RuntimeError("pinned classic not found or did not match author/year: %s" % json.dumps(spec))


def refresh_topic(topic, st, records, journals, settings, today):
    """Returns (new_state, new_records, events, info). Raises on any PubMed problem."""
    new_records = {}
    window = settings["window_months"]
    cutoff = logic.add_months(today, -window).isoformat()
    st = json.loads(json.dumps(st))  # work on a copy so a failure leaves the original untouched

    if st.get("pinned_spec") != topic["pinned"]:
        pins = []
        for spec in topic["pinned"]:
            pid, rec = resolve_pinned(spec)
            new_records[pid] = rec
            pins.append(pid)
        st["pinned"], st["pinned_spec"] = pins, topic["pinned"]
    missing = [p for p in st["pinned"] if p not in records and p not in new_records]
    if missing:
        new_records.update(pubmed.efetch(missing))

    total, ids = pubmed.esearch(build_term(topic, journals, cutoff), retmax=settings["max_results"])
    need = [i for i in ids if i not in records and i not in new_records]
    fetched = pubmed.efetch(need) if need else {}
    pool = dict(records)
    pool.update(new_records)
    pool.update(fetched)

    jn = {logic.norm_journal(j) for j in journals}
    cands, reasons = [], collections.Counter()
    for pid in ids:
        rec = pool.get(pid)
        if not rec:
            reasons["not returned by PubMed"] += 1
            continue
        ok, why = logic.qualifies(rec, jn, today, window, topic.get("exclude_pmids", []))
        if ok:
            cands.append(pid)
        else:
            reasons[why] += 1

    for p in st.get("active", []):
        if p not in pool:
            pool.update(pubmed.efetch([p]))
    new_st, events = logic.apply_refresh(st, cands, pool, today, settings["slots_recent"], window,
                                         topic.get("exclude_pmids", []))
    new_st["pinned_spec"] = st["pinned_spec"]
    for p in new_st["active"]:
        new_records[p] = pool[p]
    info = {"searched": total, "returned": len(ids), "qualified": len(cands), "rejected": dict(reasons)}
    return new_st, new_records, events, info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--topic")
    ap.add_argument("--today")
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()

    today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    cfg = load("config/topics.json", None)
    journals = load("config/journals.json", {"journals": []})["journals"]
    state = load("data/state.json", {"topics": {}})
    records = load("data/reviews.json", {})
    settings = cfg["settings"]

    errors, log, changed = {}, {}, False
    for th in cfg["themes"]:
        for t in th["topics"]:
            if args.topic and t["id"] != args.topic:
                continue
            tid = t["id"]
            st = state["topics"].get(tid) or {"pinned": [], "active": [], "retired": []}
            try:
                new_st, new_recs, events, info = refresh_topic(t, st, records, journals, settings, today)
            except Exception as e:  # noqa: BLE001 - keep the topic exactly as it was
                errors[tid] = str(e)
                print("!! %s: %s (topic left unchanged)" % (tid, e))
                continue
            state["topics"][tid] = new_st
            records.update(new_recs)
            lines = []
            for kind, pid, note in events:
                r = records.get(pid, {})
                lines.append("%s %s: %s (%s %s)%s" % (kind.upper(), pid, r.get("title", "?")[:90], r.get("journal", ""),
                                                      r.get("pubdate", "")[:7], " - " + note if note else ""))
            log[tid] = {"info": info, "events": lines}
            print("== %s: %d found, %d qualify; slots: %d recent" % (tid, info["returned"], info["qualified"], len(new_st["active"])))
            for ln in lines:
                print("   " + ln)
            if info["rejected"]:
                print("   rejected: " + ", ".join("%s %d" % (k, v) for k, v in sorted(info["rejected"].items())))

    # keep only records that something still points to
    used = set()
    for st in state["topics"].values():
        used.update(st.get("pinned", []) + st.get("active", []) + st.get("retired", []))
    records = {p: r for p, r in records.items() if p in used}

    if args.dry_run:
        print("\n(dry run: nothing written)")
    else:
        save("data/state.json", state)
        save("data/reviews.json", records)
        # always changes, so the repository sees activity every month (GitHub pauses idle scheduled workflows)
        save("data/last_run.json", {"date": today.isoformat(), "topics": log, "errors": errors})
        if not args.no_render:
            import render
            render.build(ROOT, today)
            print("\nRebuilt docs/index.html")
    if errors:
        print("\n%d topic(s) failed; see messages above." % len(errors))
        sys.exit(1)


if __name__ == "__main__":
    main()
