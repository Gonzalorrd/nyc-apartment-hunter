## How the share site is built

This is the documentation for the pipeline behind the
[apartment search page](https://gonzalorrd.github.io/nyc-apartment-hunter/). It started as a
data-pipeline class exercise: automate the flow from a private local database to a
public, visual page, using GitHub Actions.

```
laptop:  apartments.db --apartment-hunter publish--> site_data/snapshot.json --git push-->
Actions: validate -> enrich -> transform -> render -> chartbook -> GitHub Pages
```

| Step | What it does | Code |
|---|---|---|
| publish | Writes an allowlisted snapshot: buildings, units, commutes and risks only. Notes are redacted; contacts, tours, tasks and evaluations never leave the laptop. | `publishing.py` |
| validate | Data contract (the app's Pydantic schemas, foreign keys, unique ids) and privacy gate (allowlist, redaction, email/phone patterns). Fails the build on any problem. | `share_pipeline.validate` |
| enrich | Map coordinates from the US Census Geocoder, cached between runs. Matches on a different street are rejected. Outages never block a deploy. | `share_pipeline.enrich` |
| transform | Ranks units with the app's own `scoring.rank_unit` and writes parquet tables. Freshness depends on the date, so a daily scheduled run keeps it accurate. | `share_pipeline.transform` |
| render | Plotly charts, the phone-first landing page and CSV downloads. | `share_render.py` |
| chartbook | This documentation site, with a page for every chart and table. | `share/chartbook.toml` |

Run everything locally with `uv run doit` from the repository root, and list the
tasks with `uv run doit list`. The output is written to `share/public/`.

Limits: "checked" means a public source was looked at on that date. It is not a
confirmed December offer, an inspection or a measured commute. Household ratings are
never published, so rankings here leave out the deal-breaker and preference scores
that the private app uses. Units marked as deal breakers are removed before publishing.
