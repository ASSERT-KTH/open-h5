# open-h5

Open science implementation of `h5-index` and `h5-median` for Google using Semantic Scholar.

## Outputs:

Comparison for [Software Systems](https://scholar.google.com/citations?view_op=top_venues&hl=en&vq=eng_softwaresystems): <https://gistpreview.github.io/?48a57825d306f86eaf2b2c062e30674a>

## Contents

- `impact_factor.py`
  Shared API, caching, and venue-matching helpers.
- `collect_h5_median_timeseries.py`
  Recomputes a rolling 5-year `h5-index` and `h5-median` analogue from Semantic Scholar.
- `compare_h5_median.py`
  Compares the recomputed values against the saved Google Scholar HTML snapshot and draws an interactive scatter plot.
- `render_h5_median_figure.py`
  Renders the transcribed Google Scholar snapshot as an interactive HTML chart.
- `data/software_systems_google_scholar.json`
  Venue definitions and aliases used for Semantic Scholar collection.
- `data/software_systems_google_scholar_h5.json`
  Transcribed Google Scholar `h5-index` and `h5-median` values.
- `Software Systems - Google Scholar Metrics - 20260630.html`
  Saved Google Scholar snapshot used for verification.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Recommended: get and configure a Semantic Scholar API key in the system keyring (data collection goes much faster):
  - service: `login2`
  - username: `semanticscholar_key`

The scripts also accept `--api-key` explicitly.


