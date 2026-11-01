"""PubMed E-utilities helpers. Standard library only.

Nothing here is written by AI: records carry the authors' own title and abstract as indexed by PubMed.
"""
import calendar
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EU = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TOOL = "cancer-biology-reviews"
EMAIL = "andresferber@hotmail.com"
UA = "andresferber.org cancer biology reviews (andresferber@hotmail.com)"

MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _post(endpoint, params, tries=5):
    """POST (so long queries work). Polite spacing, retry with back-off on rate limits and network errors."""
    p = dict(params)
    p.update(tool=TOOL, email=EMAIL)
    key = os.environ.get("NCBI_API_KEY")
    if key:
        p["api_key"] = key
    data = urllib.parse.urlencode(p).encode()
    gap = 0.12 if key else 0.4
    err = None
    for i in range(tries):
        time.sleep(gap if i == 0 else 2 * i)
        try:
            req = urllib.request.Request(EU + endpoint, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - any failure is retried, then reported
            err = e
    raise RuntimeError("PubMed request failed (%s): %s" % (endpoint, err))


def esearch(term, retmax=1000):
    """Return (total_count, [pmids newest first]). Raises if PubMed does not answer properly."""
    raw = _post("esearch.fcgi", dict(db="pubmed", term=term, retmode="json", retmax=retmax, sort="pub_date"))
    try:
        res = json.loads(raw)["esearchresult"]
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("PubMed returned an unreadable answer to a search: %s" % e)
    if res.get("ERROR") or "idlist" not in res:
        raise RuntimeError("PubMed search error: %s" % (res.get("ERROR") or "no idlist"))
    return int(res.get("count", 0)), [str(x) for x in res["idlist"]]


def efetch(pmids):
    """Fetch full records for the PMIDs. Returns {pmid: record}."""
    out = {}
    pmids = [str(p) for p in pmids]
    for i in range(0, len(pmids), 150):
        raw = _post("efetch.fcgi", dict(db="pubmed", id=",".join(pmids[i:i + 150]), retmode="xml"))
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise RuntimeError("PubMed returned unreadable XML: %s" % e)
        for art in root.findall("PubmedArticle"):
            rec = parse_article(art)
            out[rec["pmid"]] = rec
    return out


def _txt(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _month(s):
    s = (s or "").strip()
    if s.isdigit():
        return max(1, min(12, int(s)))
    return MONTHS.get(s[:3].lower(), 1)


def _ymd(y, m, d):
    y, mo = int(y), _month(m)
    day = int(d) if d and str(d).isdigit() else 1
    day = max(1, min(day, calendar.monthrange(y, mo)[1]))
    return "%04d-%02d-%02d" % (y, mo, day)


def author_string(names):
    """'Lei G, Zhuang L, Gan B'. Long lists: first three then 'et al.'"""
    if len(names) > 6:
        return ", ".join(names[:3]) + ", et al."
    return ", ".join(names)


def parse_article(art):
    mc = art.find("MedlineCitation")
    a = mc.find("Article")
    j = a.find("Journal")
    names, lasts = [], []
    for au in a.findall("AuthorList/Author"):
        last = au.findtext("LastName") or au.findtext("CollectiveName") or ""
        ini = au.findtext("Initials") or ""
        if last:
            names.append((last + " " + ini).strip())
            lasts.append(last)
    # date: the electronic publication date when present (first date a reader could see it), else the issue date
    pubdate = ""
    for ad in a.findall("ArticleDate"):
        if ad.get("DateType") == "Electronic" and ad.findtext("Year"):
            pubdate = _ymd(ad.findtext("Year"), ad.findtext("Month"), ad.findtext("Day"))
    pd = j.find("JournalIssue/PubDate")
    year = ""
    if pd is not None:
        if pd.findtext("Year"):
            year = pd.findtext("Year")
            if not pubdate:
                pubdate = _ymd(year, pd.findtext("Month"), pd.findtext("Day"))
        elif pd.findtext("MedlineDate"):
            m = re.search(r"(19|20)\d\d", pd.findtext("MedlineDate"))
            if m:
                year = m.group(0)
                if not pubdate:
                    pubdate = _ymd(year, "1", "1")
    if not year and pubdate:
        year = pubdate[:4]
    pages = _txt(a.find("Pagination/MedlinePgn"))
    if not pages:
        for el in a.findall("ELocationID"):
            if el.get("EIdType") == "pii":
                pages = _txt(el)
    ids = {x.get("IdType"): (x.text or "").strip() for x in art.findall("PubmedData/ArticleIdList/ArticleId")}
    secs = []
    for at in a.findall("Abstract/AbstractText"):
        lb = at.get("Label") or ""
        secs.append({"label": lb.title() if lb.isupper() else lb, "text": _txt(at)})
    return {
        "pmid": mc.findtext("PMID").strip(),
        "title": _txt(a.find("ArticleTitle")).rstrip("."),
        "authors": author_string(names),
        "first_author": lasts[0] if lasts else "",
        "journal": (mc.findtext("MedlineJournalInfo/MedlineTA") or "").strip(),
        "journal_full": _txt(j.find("Title")),
        "year": year,
        "volume": _txt(j.find("JournalIssue/Volume")),
        "pages": pages,
        "doi": ids.get("doi", ""),
        "pubtypes": [t.text for t in a.findall("PublicationTypeList/PublicationType")],
        "language": [x.text for x in a.findall("Language")],
        "pubdate": pubdate,
        "abstract": secs,
    }
