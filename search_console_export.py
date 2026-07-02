#!/usr/bin/env python3
"""Export the data made available by the Google Search Console API."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
ROW_LIMIT = 25_000
SEARCH_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
REPORTS = {
    "dates": ["date"],
    "queries": ["query"],
    "pages": ["page"],
    "countries": ["country"],
    "devices": ["device"],
    "appearances": ["searchAppearance"],
    "details": ["date", "query", "page", "country", "device"],
}


def parse_args() -> argparse.Namespace:
    yesterday = date.today() - timedelta(days=1)
    default_start = yesterday - timedelta(days=89)
    parser = argparse.ArgumentParser(
        description="Export Search Console properties, sitemaps, performance, and optional URL inspections."
    )
    parser.add_argument("--credentials", default="client_secret.json", type=Path)
    parser.add_argument("--token", default="token.json", type=Path)
    parser.add_argument("--site", help="Exact property name, e.g. https://example.com/ or sc-domain:example.com")
    parser.add_argument("--start-date", default=default_start.isoformat())
    parser.add_argument("--end-date", default=yesterday.isoformat())
    parser.add_argument(
        "--search-types",
        nargs="+",
        choices=SEARCH_TYPES,
        default=["web"],
        help="Search surfaces to export (default: web).",
    )
    parser.add_argument("--data-state", choices=("final", "all"), default="final")
    parser.add_argument("--inspect-urls", type=Path, help="Text file containing one fully-qualified URL per line.")
    parser.add_argument("--inspection-language", default="fr-FR")
    parser.add_argument("--output", type=Path, default=Path("exports"))
    parser.add_argument("--list-sites", action="store_true", help="List accessible properties and exit.")
    return parser.parse_args()


def validate_dates(start: str, end: str) -> None:
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise SystemExit("Dates must use YYYY-MM-DD.") from exc
    if start_date > end_date:
        raise SystemExit("--start-date must be before or equal to --end-date.")


def load_credentials(credentials_path: Path, token_path: Path):
    if not credentials_path.exists():
        raise SystemExit(
            f"Missing credentials file: {credentials_path}\n"
            "Download OAuth Desktop credentials from Google Cloud and save them at that path."
        )

    config = json.loads(credentials_path.read_text(encoding="utf-8"))
    if config.get("type") == "service_account":
        return ServiceAccountCredentials.from_service_account_file(
            str(credentials_path), scopes=SCOPES
        )

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        credentials = flow.run_local_server(port=0)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, dimensions: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = dimensions + ["clicks", "impressions", "ctr", "position"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            keys = row.get("keys", [])
            writer.writerow(
                {
                    **{dimension: keys[index] if index < len(keys) else "" for index, dimension in enumerate(dimensions)},
                    **{metric: row.get(metric, "") for metric in fields if metric not in dimensions},
                }
            )


def fetch_all_rows(
    service, site_url: str, start: str, end: str, dimensions: list[str], search_type: str, data_state: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start_row = 0
    while True:
        body = {
            "startDate": start,
            "endDate": end,
            "dimensions": dimensions,
            "type": search_type,
            "dataState": data_state,
            "rowLimit": ROW_LIMIT,
            "startRow": start_row,
        }
        response = (
            service.searchanalytics()
            .query(siteUrl=site_url, body=body)
            .execute(num_retries=3)
        )
        batch = response.get("rows", [])
        rows.extend(batch)
        print(f"  {search_type}/{'+'.join(dimensions)}: {len(rows):,} rows", flush=True)
        if len(batch) < ROW_LIMIT:
            return rows
        start_row += ROW_LIMIT


def clean_urls(lines: Iterable[str]) -> list[str]:
    urls = []
    for line in lines:
        value = line.strip()
        if value and not value.startswith("#"):
            urls.append(value)
    return list(dict.fromkeys(urls))


def safe_site_name(site_url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.-]+", "_", site_url).strip("_") or "site"


def choose_site(properties: list[dict[str, Any]], requested: str | None) -> str:
    site_urls = [item["siteUrl"] for item in properties]
    if requested:
        if requested not in site_urls:
            choices = "\n".join(f"  - {url}" for url in site_urls)
            raise SystemExit(f"Property not accessible: {requested}\nAccessible properties:\n{choices}")
        return requested
    if len(site_urls) == 1:
        return site_urls[0]
    choices = "\n".join(f"  - {url}" for url in site_urls) or "  (none)"
    raise SystemExit(f"Choose a property with --site. Accessible properties:\n{choices}")


def main() -> int:
    args = parse_args()
    validate_dates(args.start_date, args.end_date)
    credentials = load_credentials(args.credentials, args.token)
    service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)

    properties_response = service.sites().list().execute(num_retries=3)
    properties = properties_response.get("siteEntry", [])
    if args.list_sites:
        for item in properties:
            print(f"{item.get('permissionLevel', '?'):20} {item['siteUrl']}")
        return 0

    site_url = choose_site(properties, args.site)
    output = args.output / safe_site_name(site_url) / f"{args.start_date}_to_{args.end_date}"
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "properties.json", properties_response)
    write_json(
        output / "sitemaps.json",
        service.sitemaps().list(siteUrl=site_url).execute(num_retries=3),
    )

    errors: list[dict[str, str]] = []
    for search_type in args.search_types:
        for report_name, dimensions in REPORTS.items():
            try:
                rows = fetch_all_rows(
                    service,
                    site_url,
                    args.start_date,
                    args.end_date,
                    dimensions,
                    search_type,
                    args.data_state,
                )
                write_csv(output / f"performance_{search_type}_{report_name}.csv", dimensions, rows)
            except HttpError as exc:
                message = f"{search_type}/{report_name}: {exc}"
                print(f"WARNING: {message}", file=sys.stderr)
                errors.append({"report": f"{search_type}/{report_name}", "error": str(exc)})

    if args.inspect_urls:
        urls = clean_urls(args.inspect_urls.read_text(encoding="utf-8-sig").splitlines())
        inspections = []
        for index, url in enumerate(urls, start=1):
            print(f"  inspecting {index}/{len(urls)}: {url}", flush=True)
            try:
                result = (
                    service.urlInspection()
                    .index()
                    .inspect(
                        body={
                            "inspectionUrl": url,
                            "siteUrl": site_url,
                            "languageCode": args.inspection_language,
                        }
                    )
                    .execute(num_retries=3)
                )
                inspections.append({"url": url, **result})
            except HttpError as exc:
                inspections.append({"url": url, "error": str(exc)})
        write_json(output / "url_inspections.json", inspections)

    write_json(
        output / "run_metadata.json",
        {
            "siteUrl": site_url,
            "startDate": args.start_date,
            "endDate": args.end_date,
            "searchTypes": args.search_types,
            "dataState": args.data_state,
            "errors": errors,
        },
    )
    print(f"\nExport complete: {output.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HttpError as exc:
        raise SystemExit(f"Google API error: {exc}") from exc

