# Google Search Console exporter (Python)

[![skills.sh](https://skills.sh/b/GatienBoquet/export-search-console)](https://skills.sh/GatienBoquet/export-search-console)

This small program exports the information available through the official Search Console API:

- accessible properties and permission levels (`properties.json`);
- submitted sitemap details, including the children of sitemap indexes (`sitemaps.json`);
- Search performance as CSV files, grouped by date, query, page, country, device, search appearance, a detailed combined report, and optionally by hour, with optional filters;
- optional Google index inspections for a list of URLs (`url_inspections.json`);
- a run summary with row counts, data-freshness metadata, warnings, and errors (`run_metadata.json`).

The exporter lives in `skills/export-search-console/scripts/`; the root `search_console_export.py` simply runs it.

The repository also contains an agent skill under
`skills/export-search-console` that works with Claude Code, Codex, Cursor, and
other agents supporting the [Agent Skills](https://agentskills.io) format. See
[Install the agent skill](#install-the-agent-skill).

## 1. Configure Google Cloud

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable **Google Search Console API**.
4. Configure the OAuth consent screen.
5. Create **OAuth client ID > Desktop app** credentials.
6. Download the JSON file and save it beside this program as `client_secret.json`.

Use the same Google account that has access to the property in Search Console. The program requests read-only access and stores the local login token in `token.json` (readable only by you). The first sign-in opens a browser on the machine running the program; on a headless machine, sign in once on your own computer and copy `token.json` over, or use a service account.

Alternatively, use a service-account JSON with `--credentials service-account.json`, after adding that service account's email address as a user of the Search Console property.

## 2. Install

Python 3.9 or later is required.

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The commands below are single lines and work in any shell.

## 3. Find the exact property name

```
python search_console_export.py --list-sites
```

Property names must match Search Console exactly:

- URL-prefix property: `https://www.example.com/` (including the final slash)
- Domain property: `sc-domain:example.com`

## 4. Export the website

The default period is the last 90 days and the default search surface is Web:

```
python search_console_export.py --site "sc-domain:example.com"
```

Choose dates and export every supported search surface:

```
python search_console_export.py --site "sc-domain:example.com" --start-date 2026-01-01 --end-date 2026-06-30 --search-types web image video news discover googleNews
```

Dates are in Pacific Time, like Search Console itself. Other options:

- `--data-state all` includes recent, not-yet-finalized data. `run_metadata.json` then records `firstIncompleteDate`; figures from that day on may still change.
- `--reports dates pages` exports only some reports (`dates queries pages countries devices appearances details hours`; default: all except `hours`). `details` is the heaviest; skip it for long ranges.
- `--reports hours` groups by hour. Google only keeps hourly data for about the last 10 days.
- `--filter page contains /blog/` filters rows; repeat it to combine filters with AND. Dimensions: `query page country device searchAppearance`; operators: `equals notEquals contains notContains includingRegex excludingRegex`.

Each run writes to a new folder, `exports/<property>/<start>_to_<end>/<UTC timestamp>_<data state>/`, so results from different runs never mix. The program exits with code 1 if any report, sitemap listing, or inspection failed; check `errors` in `run_metadata.json`. Discover and Google News do not support every dimension; those reports are marked `unsupported`, not failed.

## 5. Inspect specific URLs

Copy `urls.txt.example` to `urls.txt`, put one URL per line in it, then run:

```
python search_console_export.py --site "sc-domain:example.com" --inspect-urls urls.txt
```

Google currently limits URL inspection to 2,000 requests per property per day. The program inspects at most 500 URLs per run by default (`--max-inspections`, up to 2,000), waits 0.2 seconds between requests (`--inspection-delay`), and saves results after every URL. Issue messages are in English by default (`--inspection-language fr-FR` for French). The API only inspects URLs you supply; it does not provide an endpoint that enumerates every indexed URL.

## Important limitation

“All information” means all read-only report families exposed by the API, not a database dump of Search Console. Search Analytics returns the top rows available through the API and may omit anonymized or low-volume queries. It does not expose every report found in the Search Console interface. CSV pagination uses Google's maximum batch size of 25,000 rows.

## Run the tests

```
python -m unittest discover -s tests
```

The tests use a fake API service and need no credentials.

## Install the agent skill

Install it with the [`skills`](https://skills.sh) CLI (Node.js required):

```
npx skills add GatienBoquet/export-search-console
```

Add `-g` to install it for all projects, or `-a claude-code` / `-a codex` to pick an agent.

To install it manually for Codex instead, copy the folder into your Codex skills directory.

On Windows PowerShell:

```powershell
Copy-Item -Recurse `
  .\skills\export-search-console `
  "$HOME\.codex\skills\export-search-console"
```

On macOS / Linux:

```bash
cp -R skills/export-search-console ~/.codex/skills/export-search-console
```

Then start a new agent session and use a prompt such as the following (in Claude Code, write `/export-search-console` instead of `$export-search-console`):

```text
Use $export-search-console to export and analyze the last 90 days of Search Console data for sc-domain:example.com.
```
