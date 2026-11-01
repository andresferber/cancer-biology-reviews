# Cancer Biology Reviews

A periodically updated page of recent review articles on basic cellular mechanisms in cancer biology, weighted to hematologic malignancies. Separate from Page 1 and from Landmark Trials. Created by Andres Ferber, MD, with the assistance of Claude (Anthropic). For education only.

## What the page shows
Each topic has a short "Mechanism in brief", "Why it matters", a clinical hook, then its reviews, then a "To watch" row. A glossary sits at the top; filters: All, Hematologic, Solid-tumor fundamentals, Saved. The summary of each review is the authors' own abstract text from PubMed (the labelled conclusion, or the abstract's final sentences, labelled as such, the same rule as the Weekly Digest). Nothing on the page is AI-written except the editorial lines you review in `config/topics.json`.

## Slots and retirement (done by `scripts/refresh.py`)
- Each topic holds 1 pinned classic plus the 2 most recent qualifying reviews.
- When a new review qualifies, the oldest unpinned one retires automatically. A retired review also retires when it is older than 24 months. Retired items show as a one-line count with Restore (a view-only reveal). Starred items stay saved in the reader's browser.
- A topic shows fewer reviews rather than padding.
- A topic with no displayed review newer than 12 months folds into a "Dormant" row of its theme.
- Quality gate: PubMed publication type Review or Systematic Review, English, has an abstract, journal on `config/journals.json`, published in the last 24 months (electronic date if there is one). Pinned classics are the only exception. Retractions, errata, comments, editorials and letters are excluded.
- If PubMed does not answer properly for a topic, that topic is left exactly as it was and the run is flagged as failed. Nothing retires on a failed run.

## Files you may want to edit (then it rebuilds by itself)
- `config/topics.json`: themes, topics, the editorial text, the PubMed search for each topic, the pinned classic (by DOI, PMID or title; the script checks first author and year), and `exclude_pmids` to remove a review that does not belong.
- `config/journals.json`: the curated journal list (starter list, for your review).
- Pharma-neutral rules are the same as the rest of the site: generic names in editorial text (a test fails if a trade name appears in `config/topics.json`); sources are peer-reviewed papers only.

To add a topic: add an entry to a theme in `config/topics.json` (copy an existing one) and push; the workflow runs, resolves the pinned classic and fills the slots.

## How it runs
`.github/workflows/refresh.yml` runs on the 1st of each month (about 2:41 am Eastern), and whenever `config/`, `template/` or `scripts/` change, or by hand from the Actions tab. It runs the tests, runs the refresh, and commits `data/` and `docs/`. Every run writes `data/last_run.json`, which also keeps the repository active so GitHub does not pause the schedule. Every change is a commit, so earlier versions can always be restored from the history.

```
python3 scripts/refresh.py --dry-run     # show what would change, write nothing
python3 scripts/refresh.py --topic ferroptosis
python3 -m unittest discover -s tests    # offline tests
```
Optional: add a repository secret `NCBI_API_KEY` for faster PubMed access. Not needed.

## GitHub Pages
Settings > Pages > Deploy from a branch > `main` / `/docs`. The page is then at https://andresferber.github.io/cancer-biology-reviews/

## Embed on andresferber.org (Weebly "Embed Code" element)
Test first on a hidden page:
```html
<div id="cancer-biology-reviews"></div>
<script src="https://andresferber.github.io/cancer-biology-reviews/embed.js"></script>
```
The script puts the page in a frame that grows to fit its content.

## Layout
`config/` editorial and settings · `data/` state, review records, last run · `scripts/` PubMed, logic, refresh, render · `template/page.html` the page design (forest green on parchment, light and dark) · `docs/` the published page · `tests/` offline tests.
