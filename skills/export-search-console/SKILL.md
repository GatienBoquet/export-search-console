---
name: export-search-console
description: Export and analyze Google Search Console data with the bundled read-only Python client. Use when an agent needs to list Search Console properties, retrieve sitemap status (including sitemap-index children), export search performance metrics by date/hour/query/page/country/device/search appearance with optional filters, inspect the indexed status of supplied URLs, or turn Search Console API exports into concrete SEO findings.
license: MIT
---

# Export Search Console

Use `scripts/search_console_export.py` for deterministic collection, then analyze the generated JSON and CSV files. Keep all API access read-only.

## Workflow

1. Identify the target property, date range, search surfaces, reports, filters, and whether URL inspection is needed. If the user did not give the exact property name, discover it with `--list-sites` rather than guessing.
2. Locate OAuth Desktop or service-account credentials. Never print, quote, commit, or copy secret contents into chat or reports.
3. Check for a usable Python 3.9+ executable. Install the packages from `scripts/requirements.txt` only when needed and when the environment permits dependency installation.
4. Run the bundled exporter from the user's working directory so its `exports/` folder and cached `token.json` stay with the task, not inside this skill. Each run writes to a new folder, printed on the last line.
5. Verify the run before claiming success (see **Verify a run**).
6. Analyze results when requested: highlight material changes, high-impression/low-CTR pages, declining queries, weak average positions, device/country differences, sitemap errors, canonical mismatches, crawl/indexing problems, and rich-result issues. Support every conclusion with fields from the export and follow `references/api-boundaries.md` when interpreting them.
7. Return the output folder, date range (Pacific Time), exact property, search surfaces, reports and filters, row counts, warnings, unsupported reports, errors, and concise next actions.

## Authentication

Prefer OAuth Desktop credentials for an individual website owner. A first OAuth run opens a browser on the machine running the script, waits up to `--auth-timeout` seconds (default 300) for the redirect to `localhost`, and stores a refreshable `token.json` (owner-only permissions). A revoked or expired token automatically triggers a new sign-in.

On a headless or remote machine the browser redirect cannot reach the script. Either ask the user to run the first sign-in on their own computer and supply the resulting `token.json`, or use a service account. `--no-browser` only prints the URL; the redirect still has to reach `localhost` on the machine running the script.

For a service account, require its email to have access to the Search Console property. If credentials do not exist, explain the setup steps in `references/api-boundaries.md`; do not fabricate or request secret values in chat.

## Commands

Resolve the skill directory first and use absolute paths. The commands below are single lines, so they work unchanged in bash, zsh, and PowerShell; use `python3` instead of `python` where that is the interpreter's name.

Install dependencies:

```
python -m pip install -r <skill-dir>/scripts/requirements.txt
```

Discover accessible properties (unverified ones are flagged and cannot be queried):

```
python <skill-dir>/scripts/search_console_export.py --credentials <credentials.json> --token <workspace>/token.json --list-sites
```

Export one property:

```
python <skill-dir>/scripts/search_console_export.py --credentials <credentials.json> --token <workspace>/token.json --site "sc-domain:example.com" --start-date 2026-01-01 --end-date 2026-06-30 --search-types web --output <workspace>/exports
```

Options:

- `--reports dates queries pages countries devices appearances details hours` selects performance reports. The default is every report except `hours`. `details` (date+query+page+country+device) is the most expensive; drop it first for long ranges or after a load-quota error.
- `hours` groups by hour, always uses `dataState=hourly_all`, and only has data for about the last 10 days. Use it with a short, recent date range.
- `--filter DIMENSION OPERATOR EXPRESSION` narrows performance rows; repeat it to AND several filters. Dimensions: `query page country device searchAppearance`. Operators: `equals notEquals contains notContains includingRegex excludingRegex`. Country uses ISO 3166-1 alpha-3 codes (e.g. `fra`); device is `desktop`, `mobile`, or `tablet`. Example: `--filter page contains /blog/ --filter country equals fra`.
- `--data-state all` includes fresh, non-final data. Use it only when recent days matter, and always report `metadata.firstIncompleteDate` from `run_metadata.json` (see below).
- `--search-types web image video news discover googleNews`: add surfaces beyond `web` only when requested or relevant.

Inspect URLs by writing one fully qualified URL per line to a text file and adding:

```
--inspect-urls <workspace>/urls.txt
```

Inspection is capped by `--max-inspections` (default 500, maximum 2,000, Google's daily per-property quota) and paced by `--inspection-delay` (default 0.2 s). Results are saved after every URL, so an interrupted run keeps its progress. `--inspection-language` (default `en-US`) sets the language of issue messages. Do not automatically inspect every discovered page. Confirm scope before consuming substantial inspection quota.

## Verify a run

Read `run_metadata.json` in the run folder before reporting anything:

- Exit code `0` means no errors; `1` means at least one report, sitemap listing, or inspection failed. The run folder is still usable for whatever succeeded.
- `errors`: failed API calls. Never present a failed report as empty.
- `reports[]`: one entry per search type and report with `status` (`ok`, `unsupported`, or `error`), `rows`, `file`, `dataState`, `responseAggregationType`, and `metadata`. `unsupported` means the API rejected that dimension for that surface (e.g. `query` for Discover or Google News); state that the report is unavailable, not that it is empty or failed.
- `rowCounts`: rows per successful report. Zero rows is a valid result, distinct from an error.
- `metadata.firstIncompleteDate` / `firstIncompleteHour`: data on or after this point is still being processed and may change noticeably. Never report a drop in these days as a real decline.
- `warnings`: e.g. hourly range older than 10 days, or inspection list truncated by `--max-inspections`.
- `urlInspections`: requested, succeeded, and failed counts.

## Guardrails

- Treat URL-prefix properties and domain properties as different exact identifiers. Preserve the trailing slash in URL-prefix properties.
- Never claim this is a complete Search Console database dump. Read `references/api-boundaries.md` before describing coverage or completeness.
- Do not repeatedly query long date ranges after a quota/load error. Narrow the dates, reduce reports with `--reports`, add filters, or wait as appropriate.
- Do not submit or delete sitemaps, add/remove properties, or broaden OAuth scopes. The bundled client is intentionally read-only, and the `webmasters.readonly` scope makes Google reject write calls.
- Do not expose anonymized/omitted query data as zero; state that the API may omit it.
- Do not mix files from different run folders in one analysis unless the user asked for a comparison.

## Resources

- `scripts/search_console_export.py`: exporter for properties, sitemaps (with sitemap-index children), performance reports (daily and hourly, optionally filtered), and URL inspections.
- `scripts/requirements.txt`: Python dependencies.
- `references/api-boundaries.md`: authentication setup, API coverage, quotas, field meanings, and interpretation limits.
