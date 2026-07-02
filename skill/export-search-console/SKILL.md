---
name: export-search-console
description: Export and analyze Google Search Console data with the bundled read-only Python client. Use when an agent needs to list Search Console properties, retrieve sitemap status, export search performance metrics by date/query/page/country/device/search appearance, inspect the indexed status of supplied URLs, or turn Search Console API exports into concrete SEO findings.
---

# Export Search Console

Use `scripts/search_console_export.py` for deterministic collection, then analyze the generated JSON and CSV files. Keep all API access read-only.

## Workflow

1. Identify the target property, date range, desired search surfaces, and whether URL inspection is needed. If the user did not give the exact property name, discover it with `--list-sites` rather than guessing.
2. Locate OAuth Desktop or service-account credentials. Never print, quote, commit, or copy secret contents into chat or reports.
3. Check for a usable Python 3.10+ executable. Install the packages from `scripts/requirements.txt` only when needed and when the environment permits dependency installation.
4. Run the bundled exporter from the user's working directory so its `exports/` folder and cached `token.json` stay with the task, not inside this skill.
5. Inspect `run_metadata.json` and its `errors` array before claiming success. Check that expected CSV files exist and contain rows.
6. Analyze results when requested: highlight material changes, high-impression/low-CTR pages, declining queries, weak average positions, device/country differences, sitemap errors, canonical mismatches, crawl/indexing problems, and rich-result issues. Support every conclusion with fields from the export.
7. Return the output location, date range, exact property, search surfaces, row counts, warnings, and concise next actions.

## Authentication

Prefer OAuth Desktop credentials for an individual website owner. A first OAuth run opens a browser and stores a refreshable `token.json`. For a service account, require its email to have access to the Search Console property.

If credentials do not exist, explain the setup steps in `references/api-boundaries.md`; do not fabricate or request secret values in chat.

## Commands

Resolve the skill directory first and use absolute paths when practical.

Install dependencies:

```powershell
python -m pip install -r <skill-dir>\scripts\requirements.txt
```

Discover accessible properties:

```powershell
python <skill-dir>\scripts\search_console_export.py `
  --credentials <credentials.json> `
  --list-sites
```

Export one property:

```powershell
python <skill-dir>\scripts\search_console_export.py `
  --credentials <credentials.json> `
  --token <workspace>\token.json `
  --site "sc-domain:example.com" `
  --start-date 2026-01-01 `
  --end-date 2026-06-30 `
  --search-types web `
  --output <workspace>\exports
```

Add `--data-state all` only when fresh, non-final data is useful. Add other surfaces from `image video news discover googleNews` only when requested or relevant.

Inspect URLs by writing one fully qualified URL per line to a text file and adding:

```powershell
--inspect-urls <workspace>\urls.txt
```

Do not automatically inspect every discovered page. Confirm scope before consuming substantial inspection quota.

## Guardrails

- Treat URL-prefix properties and domain properties as different exact identifiers. Preserve the trailing slash in URL-prefix properties.
- Never claim this is a complete Search Console database dump. Read `references/api-boundaries.md` before describing coverage or completeness.
- Do not repeatedly query long date ranges after a quota/load error. Narrow the dates, reduce grouped dimensions, or wait as appropriate.
- Do not submit or delete sitemaps, add/remove properties, or broaden OAuth scopes. The bundled client is intentionally read-only.
- Do not expose anonymized/omitted query data as zero; state that the API may omit it.

## Resources

- `scripts/search_console_export.py`: exporter for properties, sitemaps, performance reports, and URL inspections.
- `scripts/requirements.txt`: Python dependencies.
- `references/api-boundaries.md`: authentication setup, supported API surface, quotas, and interpretation limits.
