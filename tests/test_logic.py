"""Offline tests: python3 -m unittest discover -s tests -v"""
import copy
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import logic  # noqa: E402
import pubmed  # noqa: E402
import refresh  # noqa: E402
import render  # noqa: E402

TODAY = datetime.date(2026, 11, 1)
JN = {logic.norm_journal(j) for j in ["Nat Rev Cancer", "Leukemia", "Cell Oncol (Dordr)"]}


def jl(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def jd(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def mk(pmid, date, journal="Leukemia", **kw):
    r = {"pmid": str(pmid), "title": "T%s" % pmid, "authors": "A B", "first_author": "A", "journal": journal,
         "year": date[:4], "volume": "1", "pages": "1", "doi": "10.1/%s" % pmid, "pubtypes": ["Journal Article", "Review"],
         "language": ["eng"], "pubdate": date, "abstract": [{"label": "", "text": "Some abstract text here."}]}
    r.update(kw)
    return r


def recs(*rs):
    return {r["pmid"]: r for r in rs}


EMPTY = {"pinned": ["900"], "active": [], "retired": []}


class Dates(unittest.TestCase):
    def test_add_months(self):
        self.assertEqual(logic.add_months(datetime.date(2026, 11, 1), -24), datetime.date(2024, 11, 1))
        self.assertEqual(logic.add_months(datetime.date(2026, 3, 31), -1), datetime.date(2026, 2, 28))
        self.assertEqual(logic.add_months(datetime.date(2026, 1, 15), -12), datetime.date(2025, 1, 15))

    def test_ymd_handles_odd_dates(self):
        self.assertEqual(pubmed._ymd("2025", "Feb", "30"), "2025-02-28")
        self.assertEqual(pubmed._ymd("2025", "", ""), "2025-01-01")
        self.assertEqual(pubmed._ymd("2025", "11", "5"), "2025-11-05")


class Gate(unittest.TestCase):
    def ok(self, r, **kw):
        return logic.qualifies(r, JN, TODAY, **kw)

    def test_good(self):
        self.assertTrue(self.ok(mk(1, "2026-05-01"))[0])
        self.assertTrue(self.ok(mk(1, "2026-05-01", pubtypes=["Systematic Review"]))[0])
        self.assertTrue(self.ok(mk(1, "2026-05-01", journal="Cell Oncol (Dordr)"))[0])

    def test_rejections(self):
        self.assertEqual(self.ok(mk(1, "2026-05-01", pubtypes=["Journal Article"]))[1], "not a review")
        self.assertEqual(self.ok(mk(1, "2026-05-01", pubtypes=["Review", "Retracted Publication"]))[1], "retracted/erratum/comment type")
        self.assertEqual(self.ok(mk(1, "2026-05-01", journal="Some Other J"))[1], "journal not on list")
        self.assertEqual(self.ok(mk(1, "2026-05-01", abstract=[]))[1], "no abstract")
        self.assertEqual(self.ok(mk(1, "2026-05-01", language=["fre"]))[1], "not English")
        self.assertEqual(self.ok(mk(1, "2024-10-31"))[1], "older than window")
        self.assertTrue(self.ok(mk(1, "2024-11-01"))[0])
        self.assertEqual(self.ok(mk(1, "2027-06-01"))[1], "date too far ahead")
        self.assertEqual(self.ok(mk(1, "2026-05-01"), exclude=["1"])[1], "excluded by editor")

    def test_journal_name_variants(self):
        self.assertEqual(logic.norm_journal("Cell Oncol (Dordr)"), logic.norm_journal("cell oncol  dordr"))


class Abstracts(unittest.TestCase):
    def test_labelled_conclusion(self):
        a = logic.split_abstract([{"label": "Background", "text": "B."}, {"label": "Conclusions", "text": "C."}])
        self.assertEqual(a["con"], "C.")
        self.assertEqual(a["con_label"], "Authors’ conclusion")
        self.assertEqual([s["label"] for s in a["abs"]], ["Background"])

    def test_unstructured_long_uses_final_sentences(self):
        a = logic.split_abstract([{"label": "", "text": "One is here. Two is here. Three is here. Four is here."}])
        self.assertEqual(a["con"], "Three is here. Four is here.")
        self.assertEqual(a["con_label"], "From the abstract (final sentences)")
        self.assertEqual(len(a["abs"]), 1)

    def test_short_abstract_is_shown_whole(self):
        a = logic.split_abstract([{"label": "", "text": "Only one sentence."}])
        self.assertEqual((a["con"], a["con_label"], a["abs"]), ("Only one sentence.", "Abstract", []))

    def test_lone_summary_label_is_not_a_conclusion(self):
        a = logic.split_abstract([{"label": "Summary", "text": "One. Two. Three. Four."}])
        self.assertEqual(a["con_label"], "From the abstract (final sentences)")

    def test_empty(self):
        self.assertEqual(logic.split_abstract([]), {"abs": [], "con": "", "con_label": ""})


class Slots(unittest.TestCase):
    def run_it(self, st, cands, rs, **kw):
        return logic.apply_refresh(st, [c["pmid"] for c in cands], recs(*rs), TODAY, **kw)

    def test_fill_takes_two_newest_and_does_not_retire_extras(self):
        c = [mk(1, "2026-01-10"), mk(2, "2026-03-10"), mk(3, "2025-12-10")]
        st, ev = self.run_it(EMPTY, c, c)
        self.assertEqual(st["active"], ["2", "1"])
        self.assertEqual(st["retired"], [])
        self.assertEqual([e[0] for e in ev], ["entered", "entered"])

    def test_new_review_retires_oldest_unpinned(self):
        a, b, n = mk(1, "2026-01-10"), mk(2, "2026-03-10"), mk(3, "2026-10-10")
        st0 = {"pinned": ["900"], "active": ["2", "1"], "retired": []}
        st, ev = self.run_it(st0, [a, b, n], [a, b, n])
        self.assertEqual(st["active"], ["3", "2"])
        self.assertEqual(st["retired"], ["1"])
        self.assertIn(("retired", "1", "displaced by a newer review"), ev)
        self.assertIn(("entered", "3", ""), ev)

    def test_fewer_shown_not_padded(self):
        c = [mk(1, "2026-01-10")]
        st, _ = self.run_it(EMPTY, c, c)
        self.assertEqual(st["active"], ["1"])

    def test_aged_out_active_retires(self):
        old = mk(1, "2024-06-01")
        st0 = {"pinned": ["900"], "active": ["1"], "retired": []}
        st, ev = self.run_it(st0, [], [old])
        self.assertEqual((st["active"], st["retired"]), ([], ["1"]))
        self.assertEqual(ev[0][2], "aged out of the window")

    def test_retired_stays_retired(self):
        r1, r2, r3 = mk(1, "2026-01-10"), mk(2, "2026-03-10"), mk(3, "2026-10-10")
        st0 = {"pinned": [], "active": ["3", "2"], "retired": ["1"]}
        st, ev = self.run_it(st0, [r1, r2, r3], [r1, r2, r3])
        self.assertEqual(st["active"], ["3", "2"])
        self.assertEqual(st["retired"], ["1"])
        self.assertEqual(ev, [])

    def test_pinned_never_in_slots(self):
        p = mk(900, "2026-09-01")
        st, _ = self.run_it(EMPTY, [p], [p])
        self.assertEqual(st["active"], [])
        self.assertEqual(st["pinned"], ["900"])

    def test_exclude_removes_everywhere(self):
        a, b = mk(1, "2026-01-10"), mk(2, "2026-03-10")
        st0 = {"pinned": [], "active": ["2", "1"], "retired": ["5"]}
        st, _ = self.run_it(st0, [a, b], [a, b], exclude=["2", "5"])
        self.assertEqual(st["active"], ["1"])
        self.assertEqual(st["retired"], [])

    def test_same_date_tie_is_stable(self):
        c = [mk(10, "2026-03-01"), mk(11, "2026-03-01"), mk(12, "2026-03-01")]
        s1, _ = self.run_it(EMPTY, c, c)
        s2, _ = self.run_it(EMPTY, list(reversed(c)), c)
        self.assertEqual(s1["active"], s2["active"])
        self.assertEqual(s1["active"], ["12", "11"])

    def test_idempotent(self):
        c = [mk(1, "2026-01-10"), mk(2, "2026-03-10"), mk(3, "2026-10-10")]
        s1, _ = self.run_it(EMPTY, c, c)
        s2, ev = self.run_it(s1, c, c)
        self.assertEqual(s1, s2)
        self.assertEqual(ev, [])

    def test_retire_order_most_recent_first(self):
        a, b, c, d = mk(1, "2026-01-01"), mk(2, "2026-02-01"), mk(3, "2026-03-01"), mk(4, "2026-04-01")
        s, _ = self.run_it(EMPTY, [a, b], [a, b])
        s, _ = self.run_it(s, [a, b, c], [a, b, c])
        s, _ = self.run_it(s, [a, b, c, d], [a, b, c, d])
        self.assertEqual(s["active"], ["4", "3"])
        self.assertEqual(s["retired"], ["2", "1"])


class Dormant(unittest.TestCase):
    def test_dormant_rules(self):
        r = recs(mk(1, "2026-06-01"), mk(2, "2025-09-01"), mk(3, "2025-11-01"))
        self.assertFalse(logic.is_dormant({"active": ["1"]}, r, TODAY))
        self.assertTrue(logic.is_dormant({"active": ["2"]}, r, TODAY))
        self.assertTrue(logic.is_dormant({"active": []}, r, TODAY))
        self.assertFalse(logic.is_dormant({"active": ["3"]}, r, TODAY))  # exactly 12 months old: still live
        self.assertFalse(logic.is_dormant({"active": ["2", "1"]}, r, TODAY))


class Safety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for d in ("config", "template", "data"):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(self.tmp, d), dirs_exist_ok=True)
        os.makedirs(os.path.join(self.tmp, "docs"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_failed_pubmed_leaves_state_alone(self):
        seed = {"topics": {"ferroptosis": {"pinned": ["900"], "active": ["1", "2"], "retired": ["3"],
                                           "pinned_spec": jl(os.path.join(ROOT, "config/topics.json"))
                                           ["themes"][1]["topics"][0]["pinned"]}}}
        r = {p: mk(p, "2026-05-01") for p in ("1", "2", "3", "900")}
        jd(seed, os.path.join(self.tmp, "data/state.json"))
        jd(r, os.path.join(self.tmp, "data/reviews.json"))
        orig_root, orig_post = refresh.ROOT, pubmed._post
        refresh.ROOT = self.tmp
        pubmed._post = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        old_argv = sys.argv
        sys.argv = ["refresh.py", "--topic", "ferroptosis", "--today", "2026-11-01"]
        try:
            with self.assertRaises(SystemExit) as cm:
                refresh.main()
            self.assertEqual(cm.exception.code, 1)
        finally:
            refresh.ROOT, pubmed._post, sys.argv = orig_root, orig_post, old_argv
        after = jl(os.path.join(self.tmp, "data/state.json"))
        self.assertEqual(after["topics"]["ferroptosis"]["active"], ["1", "2"])
        self.assertEqual(after["topics"]["ferroptosis"]["retired"], ["3"])
        self.assertIn("ferroptosis", jl(os.path.join(self.tmp, "data/last_run.json"))["errors"])

    def test_rendered_page_neutralizes_markup_in_titles(self):
        cfg = jl(os.path.join(ROOT, "config/topics.json"))
        tid = cfg["themes"][0]["topics"][0]["id"]
        evil = mk(5, "2026-05-01", title="</script><script>alert(1)</script> <!-- x")
        jd({"topics": {tid: {"pinned": [], "active": ["5"], "retired": []}}}, os.path.join(self.tmp, "data/state.json"))
        jd({"5": evil}, os.path.join(self.tmp, "data/reviews.json"))
        render.build(self.tmp, TODAY)
        with open(os.path.join(self.tmp, "docs/index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertEqual(html.count("</script>"), 2)  # data block + code block only
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("November 2026", html)


class Editorial(unittest.TestCase):
    BRANDS = ["venclexta", "imbruvica", "calquence", "brukinsa", "jaypirca", "revlimid", "pomalyst", "darzalex",
              "kyprolis", "velcade", "xpovio", "tibsovo", "idhifa", "rydapt", "xospata", "vanflyta", "onureg",
              "dacogen", "vidaza", "mylotarg", "besponsa", "blincyto", "kymriah", "yescarta", "tecartus", "breyanzi",
              "abecma", "carvykti", "tecvayli", "elrexfio", "talvey", "columvi", "epkinly", "lunsumio", "adcetris",
              "polivy", "gazyva", "rituxan", "jakafi", "revuforj", "inqovi", "rezlidhia"]

    def test_no_trade_names_in_editorial_text(self):
        with open(os.path.join(ROOT, "config/topics.json"), encoding="utf-8") as f:
            text = f.read().lower()
        found = [b for b in self.BRANDS if re.search(r"\b%s\b" % b, text)]
        self.assertEqual(found, [], "trade names in editorial text: %s" % found)

    def test_config_is_complete(self):
        cfg = jl(os.path.join(ROOT, "config/topics.json"))
        ids = []
        for th in cfg["themes"]:
            for t in th["topics"]:
                ids.append(t["id"])
                for k in ("id", "name", "scope", "plain", "why", "hook", "watch", "query", "pinned"):
                    self.assertIn(k, t)
                self.assertIn(t["scope"], ("heme", "solid", "both"))
                self.assertEqual(len(t["pinned"]), cfg["settings"]["slots_pinned"])
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
