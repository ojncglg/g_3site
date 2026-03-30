# Search Ops Playbook (SEO, AEO, GEO)

This playbook covers the weekly process for indexing and query performance tracking.

## 1) Bing Webmaster Setup

1. Go to `https://www.bing.com/webmasters/` and add `https://g3industries.io`.
2. Verify ownership (DNS TXT is preferred).
3. Submit your sitemap URL:
   - `https://g3industries.io/sitemap.xml`

## 2) IndexNow Setup

This app now supports an IndexNow key endpoint at:
- `/indexnow-key.txt`

Configure your key as an environment variable:
- `INDEXNOW_KEY=<your-key>`

Then run the submit script:

```bash
python scripts/submit_indexnow.py --base-url https://g3industries.io
```

Dry run preview:

```bash
python scripts/submit_indexnow.py --base-url https://g3industries.io --dry-run
```

Optional: submit a custom URL list:

```bash
python scripts/submit_indexnow.py --base-url https://g3industries.io --urls-file urls.txt
```

## 3) Weekly Query-Level Tracking

Export two Search Console query CSV files:
- Current week
- Previous week

Generate a report:

```bash
python scripts/weekly_query_report.py \
  --current data/gsc/current_week_queries.csv \
  --previous data/gsc/previous_week_queries.csv \
  --output reports/weekly-query-report.md
```

The report highlights:
- Top impression queries
- Biggest click drops
- High-impression / low-CTR opportunities
- New queries worth watching

## 4) Weekly Review Checklist

- Update title/meta copy for low-CTR pages with high impressions.
- Improve internal links from blog posts to:
  - `/products`
  - `/security`
  - `/#demo`
- Request indexing for materially changed pages.
- Log the week’s wins and losses in your report file.

## 5) Fast URL Targets After Major Updates

- `https://g3industries.io/`
- `https://g3industries.io/products`
- `https://g3industries.io/security`
- `https://g3industries.io/grants`
- `https://g3industries.io/blog`

