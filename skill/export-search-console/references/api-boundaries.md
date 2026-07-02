# Search Console API boundaries

## Credential setup

For OAuth Desktop access:

1. Create or select a Google Cloud project.
2. Enable **Google Search Console API**.
3. Configure the OAuth consent screen.
4. Create an **OAuth client ID** for a **Desktop app**.
5. Download the JSON file and keep it outside source control.
6. Authenticate with a Google account that can access the Search Console property.

For service-account access, create a service-account JSON and add its email address as a user of the Search Console property before running the exporter.

The required scope is `https://www.googleapis.com/auth/webmasters.readonly`.

## Exposed data

The public API exposes:

- Search Analytics performance data;
- submitted sitemap status;
- accessible properties and permission levels;
- indexed-version URL inspection results.

It does not expose every Search Console UI report or provide a full list of all indexed URLs. URL Inspection requires the caller to supply each URL, and it does not perform a live-URL test.

## Search Analytics interpretation

- Rows can contain clicks, impressions, CTR, and average position.
- Supported surfaces are `web`, `image`, `video`, `news`, `discover`, and `googleNews`.
- Pagination supports at most 25,000 rows per request.
- Results emphasize top rows and can omit anonymized or low-volume queries. Never label an export as an exhaustive database dump.
- Grouping or filtering by page and query is comparatively expensive. Long ranges and detailed combined reports can hit load quota.
- `dataState=final` excludes fresh non-final data; `dataState=all` includes it.

## URL Inspection limits

URL inspection is limited to 2,000 requests per property per day and 600 per minute. Treat those as maximum limits, not targets. The result can include verdict, coverage state, robots state, indexing state, last crawl, fetch state, canonical URLs, referring URLs, sitemaps, and rich-results findings when available.

## Safe reporting language

Say “all report families exposed by the API were requested” when accurate. Do not say “all Search Console data was downloaded.” Distinguish a zero-row report from an unsupported/failed report by checking `run_metadata.json` errors.
