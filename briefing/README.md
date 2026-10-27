# Energy Market Briefing — generator

Builds the monthly *Energy Market Briefing* PDF of AD International Consulting from the dashboard data (`../data/data.json`) and a Markdown text file.

```bash
pip install -r requirements.txt && python -m playwright install chromium
python build_briefing.py --data ../data/data.json \
  --content issues/2026-11/content.md --out issues/2026-11/ADIC_Energy_Market_Briefing_2026-11.pdf
```

**Writing an issue** — `content.md` starts with front matter (`title`, `issue`, `subtitle`, `asof`, `jkm`, `jkm_date`), then pages separated by `<!-- page -->`.
- Numbers come from the data, never typed: `{{brent.last}}`, `{{brent.chg_ytd}}`, `{{eurusd.vol_30d}}`, `{{spread.last}}`, `{{fc.brent.lo80}}`, `{{corr.recent.eurusd.usdcny}}`, `{{volrank.brent}}`.
- Exhibits on their own line: `[[chart:oil]]`, `[[chart:spread]]`, `[[chart:gas]]`, `[[chart:fx]]`, `[[chart:vol]]`, `[[chart:fan]]`, `[[table:kpis]]`, `[[table:ranges]]`, `[[table:brent_ccy]]`.
- Every outside fact carries a numbered reference to the Sources list at the end.

`issues/2026-11` is the public sample issue. Fonts: Montserrat and IBM Plex Mono (SIL Open Font License).
