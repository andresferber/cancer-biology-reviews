"""Pure logic: quality gate, slot filling, retirement, dormancy, abstract handling.

No network and no file access here, so everything can be tested with fixtures.
"""
import calendar
import datetime
import re


def add_months(d, n):
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return datetime.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def norm_journal(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


REVIEW_TYPES = {"Review", "Systematic Review"}
BAD_TYPES = {"Retracted Publication", "Retraction of Publication", "Published Erratum", "Comment",
             "Editorial", "Letter", "News", "Expression of Concern", "Preprint"}


def qualifies(rec, journals_norm, today, window_months=24, exclude=()):
    """Quality gate. Returns (ok, reason). Pinned classics never go through this."""
    if rec["pmid"] in set(exclude):
        return False, "excluded by editor"
    types = set(rec.get("pubtypes", []))
    if not types & REVIEW_TYPES:
        return False, "not a review"
    if types & BAD_TYPES:
        return False, "retracted/erratum/comment type"
    if norm_journal(rec.get("journal")) not in journals_norm:
        return False, "journal not on list"
    if not any(s["text"] for s in rec.get("abstract", [])):
        return False, "no abstract"
    if "eng" not in [x.lower() for x in rec.get("language", ["eng"])]:
        return False, "not English"
    pd = rec.get("pubdate") or ""
    if not pd:
        return False, "no date"
    if pd < add_months(today, -window_months).isoformat():
        return False, "older than window"
    if pd > (today + datetime.timedelta(days=62)).isoformat():
        return False, "date too far ahead"
    return True, ""


# ---- abstract: the authors' own words only ----
CONC = re.compile(r"conclu|interpretation|implication|significance|summary", re.I)


def sentences(t):
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])", t.strip()) if s]


def split_abstract(secs):
    """Return {'abs': [{label,text}], 'con': str, 'con_label': str}.
    Labelled conclusion section -> "Authors' conclusion". Unstructured abstract with 3+ sentences ->
    final two sentences, labelled as such. Short abstract -> the whole abstract as the summary.
    Same rules as the Weekly Digest. Nothing is written by AI."""
    secs = [s for s in secs if s.get("text")]
    if not secs:
        return {"abs": [], "con": "", "con_label": ""}
    con, label, con_idx = "", "", set()
    for i, s in enumerate(secs):
        lb = s.get("label") or ""
        if lb and CONC.search(lb) and (len(secs) > 1 or not re.fullmatch(r"summary|abstract", lb.strip(), re.I)):
            con, label = (con + " " + s["text"]).strip() if label else s["text"], "Authors’ conclusion"
            con_idx.add(i)
    if con:
        return {"abs": [s for i, s in enumerate(secs) if i not in con_idx], "con": con, "con_label": label}
    full = " ".join(s["text"] for s in secs)
    ss = sentences(full)
    if len(ss) >= 3:
        return {"abs": secs, "con": " ".join(ss[-2:]), "con_label": "From the abstract (final sentences)"}
    return {"abs": [], "con": full, "con_label": "Abstract"}


# ---- slots, retirement, dormancy ----
def apply_refresh(st, candidate_ids, records, today, recent_slots=2, window_months=24, exclude=()):
    """Update one topic's state.

    st: {'pinned': [pmid], 'active': [pmid], 'retired': [pmid]}  (active = displayed recent reviews, newest first)
    candidate_ids: pmids that passed the quality gate this run
    records: {pmid: record} covering every pmid in st and in candidate_ids
    Returns (new_state, events) where events = [(kind, pmid, note)].

    Rules: pinned classics are never touched. The recent slots hold the newest qualifying reviews; when a new
    one qualifies the oldest displayed one retires. Fewer qualify -> fewer shown (no padding). An active review
    that falls outside the date window retires. Items already retired stay retired. Nothing is retired
    unless this function runs, and refresh.py only runs it after PubMed answered properly.
    """
    ex = set(exclude)
    pinned = list(st.get("pinned", []))
    active = [p for p in st.get("active", []) if p not in ex and p not in pinned]
    retired = [p for p in st.get("retired", []) if p not in ex and p not in pinned]
    cutoff = add_months(today, -window_months).isoformat()
    events = []
    pool, aged = {}, set()
    for p in active:
        if records[p]["pubdate"] >= cutoff:
            pool[p] = records[p]
        else:
            aged.add(p)
    for p in candidate_ids:
        if p in ex or p in pinned or p in retired or p in pool or p in aged:
            continue
        pool[p] = records[p]
    ranked = sorted(pool, key=lambda p: (records[p]["pubdate"], int(p)), reverse=True)
    new_active = ranked[:recent_slots]
    for p in new_active:
        if p not in active:
            events.append(("entered", p, ""))
    displaced = [p for p in active if p not in new_active]
    for p in displaced:
        events.append(("retired", p, "aged out of the window" if p in aged else "displaced by a newer review"))
    new_retired = displaced + [p for p in retired if p not in displaced]
    return {"pinned": pinned, "active": new_active, "retired": new_retired}, events


def newest_recent(st, records):
    dates = [records[p]["pubdate"] for p in st.get("active", []) if p in records]
    return max(dates) if dates else None


def is_dormant(st, records, today, months=12):
    """Dormant: no displayed recent review newer than `months` months old (or none at all)."""
    n = newest_recent(st, records)
    return n is None or n < add_months(today, -months).isoformat()
