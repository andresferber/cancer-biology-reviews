#!/usr/bin/env python3
"""Build docs/index.html from config/topics.json + data/*.json + template/page.html. No network."""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import logic  # noqa: E402

KEEP = ("pmid", "title", "authors", "journal", "year", "volume", "pages", "doi", "pubdate")


def _load(root, rel, default):
    p = os.path.join(root, rel)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default


def payload(root, today):
    cfg = _load(root, "config/topics.json", None)
    state = _load(root, "data/state.json", {"topics": {}})
    records = _load(root, "data/reviews.json", {})
    s = cfg["settings"]
    out_recs, themes = {}, []
    for th in cfg["themes"]:
        topics = []
        for t in th["topics"]:
            st = state["topics"].get(t["id"], {"pinned": [], "active": [], "retired": []})
            ids = st.get("pinned", []) + st.get("active", []) + st.get("retired", [])
            for p in ids:
                if p in records and p not in out_recs:
                    r = records[p]
                    d = {k: r.get(k, "") for k in KEEP}
                    d.update(logic.split_abstract(r.get("abstract", [])))
                    out_recs[p] = d
            topics.append({
                "id": t["id"], "name": t["name"], "scope": t["scope"], "plain": t["plain"], "why": t["why"],
                "hook": t["hook"], "hook_draft": bool(t.get("hook_draft")), "watch": t["watch"],
                "pinned": [p for p in st.get("pinned", []) if p in records],
                "recent": [p for p in st.get("active", []) if p in records],
                "retired": [p for p in st.get("retired", []) if p in records],
                "dormant": logic.is_dormant(st, records, today, s["dormant_months"]),
            })
        themes.append({"id": th["id"], "name": th["name"], "blurb": th["blurb"], "topics": topics})
    return {"updated": today.isoformat(), "slots": s["slots_pinned"] + s["slots_recent"],
            "glossary": cfg["glossary"], "themes": themes, "records": out_recs}


def build(root, today=None):
    today = today or datetime.date.today()
    with open(os.path.join(root, "template", "page.html"), encoding="utf-8") as f:
        html = f.read()
    data = json.dumps(payload(root, today), ensure_ascii=False, separators=(",", ":"))
    # every "<" becomes \u003c (valid inside JSON strings), so nothing in a title or abstract can ever
    # open or close a tag inside the data block
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = html.replace("__DATA__", data).replace("__UPDATED__", today.strftime("%B %Y"))
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    with open(os.path.join(root, "docs", "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    build(os.path.dirname(HERE))
    print("Rebuilt docs/index.html")
