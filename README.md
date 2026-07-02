# Google Search Console exporter (Python)

This small program exports the information available through the official Search Console API:

- accessible properties and permission levels (`properties.json`);
- submitted sitemap details (`sitemaps.json`);
- Search performance as CSV files, grouped by date, query, page, country, device, search appearance, and a detailed combined report;
- optional Google index inspections for a list of URLs (`url_inspections.json`).

The repository also contains an agent-ready Codex skill under
`skill/export-search-console`. Invoke it as `$export-search-console` after
copying that folder into your Codex skills directory.

## 1. Configure Google Cloud

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable **Google Search Console API**.
4. Configure the OAuth consent screen.
5. Create **OAuth client ID > Desktop app** credentials.
6. Download the JSON file and save it beside this program as `client_secret.json`.

Use the same Google account that has access to the property in Search Console. The program requests read-only access and stores the local login token in `token.json`.

Alternatively, use a service-account JSON with `--credentials service-account.json`, after adding that service account's email address as a user of the Search Console property.

## 2. Install

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 3. Find the exact property name

```powershell
python search_console_export.py --list-sites
```

Property names must match Search Console exactly:

- URL-prefix property: `https://www.example.com/` (including the final slash)
- Domain property: `sc-domain:example.com`

## 4. Export the website

The default period is the last 90 days and the default search surface is Web:

```powershell
python search_console_export.py --site "sc-domain:example.com"
```

Choose dates and export every supported search surface:

```powershell
python search_console_export.py `
  --site "sc-domain:example.com" `
  --start-date 2026-01-01 `
  --end-date 2026-06-30 `
  --search-types web image video news discover googleNews
```

To include recent, not-yet-finalized data, add `--data-state all`.

## 5. Inspect specific URLs

Copy `urls.txt.example` to `urls.txt`, put one URL per line in it, then run:

```powershell
python search_console_export.py `
  --site "sc-domain:example.com" `
  --inspect-urls urls.txt
```

Google currently limits URL inspection to 2,000 requests per property per day. The API only inspects URLs you supply; it does not provide an endpoint that enumerates every indexed URL.

## Important limitation

“All information” means all report families exposed by the API, not a database dump of Search Console. Search Analytics returns the top rows available through the API and may omit anonymized or low-volume queries. It does not expose every report found in the Search Console interface. CSV pagination uses Google's maximum batch size of 25,000 rows.

## Install the Codex skill

On Windows PowerShell:

```powershell
Copy-Item -Recurse `
  .\skill\export-search-console `
  "$HOME\.codex\skills\export-search-console"
```

Then start a new Codex session and use a prompt such as:

```text
Use $export-search-console to export and analyze the last 90 days of Search Console data for sc-domain:example.com.
```
