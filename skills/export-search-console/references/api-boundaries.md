# Search Console API boundaries

Checked against the Search Console API v1 discovery document (revision 20260923). Quotas come from Google's published usage limits and are not part of that document.

## Credential setup

For OAuth Desktop access:

1. Create or select a Google Cloud project.
2. Enable **Google Search Console API**.
3. Configure the OAuth consent screen.
4. Create an **OAuth client ID** for a **Desktop app**.
5. Download the JSON file and keep it outside source control.
6. Authenticate with a Google account that can access the Search Console property. The first sign-in must happen on a machine with a browser that can reach `localhost` on the machine running the script; copy the resulting `token.json` to headless machines.

For service-account access, create a service-account JSON and add its email address as a user of the Search Console property before running the exporter.

The required scope is `https://www.googleapis.com/auth/webmasters.readonly`.

## API coverage

| API method | Exporter | Notes |
|---|---|---|
| `sites.list` | Used | `properties.json`; permission levels included. |
| `sites.get` | Not needed | Same data as `sites.list`. |
| `sitemaps.list` | Used, recursively | Top-level sitemaps plus the children of every sitemap index (`sitemapIndex` parameter). Each entry carries `parentIndex` (`null` at top level). |
| `sitemaps.get` | Not needed | Same object as in `sitemaps.list`. |
| `searchanalytics.query` | Used | Daily and hourly reports, all six search types, optional dimension filters. `aggregationType` is left at `auto` (required when grouping or filtering by page). |
| `urlInspection.index.inspect` | Used | Indexed-version inspection of URLs you supply. |
| `sites.add`, `sites.delete`, `sitemaps.submit`, `sitemaps.delete` | Excluded | Write operations; require the full `webmasters` scope. |
| `urlTestingTools.mobileFriendlyTest.run` | Excluded | Still in the API definition, but Google retired the Mobile-Friendly Test. |

The API does not expose every Search Console UI report (for example the Page indexing, Core Web Vitals, Links, or Manual actions reports), does not list all indexed URLs, and does not run live URL tests. Say "all read-only report families exposed by the API were requested" only when every relevant search type and report ran; never say "all Search Console data was downloaded."

## Search Analytics interpretation

- Rows contain `clicks`, `impressions`, `ctr`, and `position`. `ctr` is a ratio from 0 to 1, not a percentage. `position` is an average: when combining rows, weight it by impressions; never average positions directly.
- Dates and hours are in Pacific Time (`America/Los_Angeles`). The exporter's default range ends yesterday in Pacific Time.
- When grouping by date, days without data are omitted. A missing day means no data for that day, not a failed export.
- Supported search types: `web`, `image`, `video`, `news` (News tab in Search), `discover`, `googleNews` (news.google.com and the Google News app). Discover and Google News do not report every dimension; the exporter marks rejected combinations as `unsupported`.
- Pagination returns at most 25,000 rows per request; the exporter pages until a short page.
- Results emphasize top rows and omit anonymized or low-volume queries. Totals from query- or page-grouped reports are therefore lower than totals from the `dates` report.
- Aggregation: with `auto`, reports grouped or filtered by page are aggregated **by page** (canonical URL); other reports are aggregated **by property**. By-page and by-property totals differ by design. Each report's `responseAggregationType` is recorded in `run_metadata.json`; do not compare totals across different aggregation types.
- Data retention is about 16 months; older start dates silently return partial data.
- Grouping or filtering by page and query is comparatively expensive. Long ranges and the `details` report can hit load quota.
- Data state:
  - `final`: finalized data only (default).
  - `all`: includes fresh, partial data. The response `metadata.firstIncompleteDate` marks the first day still being processed; values from that day on may change noticeably.
  - `hourly_all`: required for the `hour` dimension, which covers about the last 10 days. `metadata.firstIncompleteHour` marks the first incomplete hour.
- Filters: dimensions `query`, `page`, `country` (ISO 3166-1 alpha-3), `device` (`desktop`, `mobile`, `tablet`), `searchAppearance`; operators `equals`, `notEquals`, `contains`, `notContains`, `includingRegex`, `excludingRegex`. All filters in a run are combined with AND and are recorded in `run_metadata.json`. Filtered exports describe only the filtered subset.

## Sitemap fields

- `errors` and `warnings` are counts returned as strings; convert them before comparing.
- `contents[].submitted` is the number of URLs of that content type. `contents[].indexed` is **deprecated**; never report it.
- `isPending: true` means the sitemap has not been processed yet, not that it is broken.
- `isSitemapsIndex: true` marks an index; its children appear as separate entries with `parentIndex` set.

## URL Inspection

Google limits URL inspection to 2,000 requests per property per day and 600 per minute. Treat those as maximum limits, not targets. The exporter caps a run with `--max-inspections` (default 500) and waits `--inspection-delay` seconds between calls.

Each result's `inspectionResult` can contain:

- `inspectionResultLink`: link to the report in Search Console.
- `indexStatusResult`:
  - `verdict`: `PASS` = valid/indexed, `NEUTRAL` = **excluded** (not an error, but not indexed), `FAIL` = error. `PARTIAL` is no longer used.
  - `coverageState`: human-readable state (e.g. "Submitted and indexed").
  - `robotsTxtState`: `ALLOWED` / `DISALLOWED`. Use this for robots.txt blocking; the `indexingState` value `BLOCKED_BY_ROBOTS_TXT` is no longer used.
  - `indexingState`: `INDEXING_ALLOWED`, `BLOCKED_BY_META_TAG`, `BLOCKED_BY_HTTP_HEADER`.
  - `pageFetchState`: `SUCCESSFUL`, `SOFT_404`, `BLOCKED_ROBOTS_TXT`, `NOT_FOUND`, `ACCESS_DENIED` (401), `ACCESS_FORBIDDEN` (403), `BLOCKED_4XX`, `SERVER_ERROR`, `REDIRECT_ERROR`, `INTERNAL_CRAWL_ERROR`, `INVALID_URL`.
  - `lastCrawlTime`, `crawledAs` (`DESKTOP` / `MOBILE`): absent if never crawled successfully.
  - `userCanonical` (absent if none declared) and `googleCanonical` (absent if the page is not indexed). Report a canonical mismatch only when both are present and differ.
  - `sitemap`: sitemaps known to list the URL; not guaranteed to be exhaustive.
  - `referringUrls`: URLs linking to the inspected URL, directly or indirectly.
- `richResultsResult`: `verdict` and `detectedItems` with per-item issues; absent when no rich results are found.
- `ampResult`: only for AMP pages.
- `mobileUsabilityResult`: Google retired the Mobile Usability report; do not base findings on this field.

Entries with an `error` key failed and are also listed in `run_metadata.json` `errors`.

## Safe reporting language

Say "all read-only report families exposed by the API were requested" only when accurate. Distinguish:

- a zero-row report (`status: ok`, `rows: 0`),
- an unsupported report (`status: unsupported`),
- a failed report (`status: error`, also in `errors`),
- partial data (dates on or after `firstIncompleteDate`).
