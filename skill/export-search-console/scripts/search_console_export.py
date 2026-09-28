#!/usr/bin/env python3
"""Export the data made available by the Google Search Console API (read-only)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
ROW_LIMIT = 25_000
SEARCH_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
# Surfaces for which the API may reject some dimensions (e.g. query); such
# rejections are recorded as "unsupported" rather than as errors.
LIMITED_SEARCH_TYPES = ("discover", "googleNews")
REPORTS = {
    "dates": ["date"],
    "queries": ["query"],
    "pages": ["page"],
    "countries": ["country"],
    "devices": ["device"],
    "appearances": ["searchAppearance"],
    "details": ["date", "query", "page", "country", "device"],
    "hours": ["hour"],
}
DEFAULT_REPORTS = [name for name in REPORTS if name != "hours"]
HOURLY_DAYS = 10
FILTER_DIMENSIONS = ("query", "page", "country", "device", "searchAppearance")
FILTER_OPERATORS = ("equals", "notEquals", "contains", "notContains", "includingRegex", "excludingRegex")
UNUSABLE_PERMISSIONS = ("siteUnverifiedUser",)
MAX_INSPECTIONS_PER_DAY = 2_000


def pacific_today() -> date:
    """Search Console dates are expressed in Pacific Time."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Los_Angeles")).date()
    except Exception:  # zoneinfo/tzdata unavailable: approximate with UTC-8.
        return datetime.now(timezone(timedelta(hours=-8))).date()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    yesterday = pacific_today() - timedelta(days=1)
    default_start = yesterday - timedelta(days=89)
    parser = argparse.ArgumentParser(
        description="Export Search Console properties, sitemaps, performance, and optional URL inspections."
    )
    parser.add_argument("--credentials", default="client_secret.json", type=Path)
    parser.add_argument("--token", default="token.json", type=Path)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the OAuth URL instead of opening a browser (the redirect still targets localhost).",
    )
    parser.add_argument(
        "--auth-timeout", type=int, default=300, help="Seconds to wait for the OAuth redirect (default: 300)."
    )
    parser.add_argument("--site", help="Exact property name, e.g. https://example.com/ or sc-domain:example.com")
    parser.add_argument("--start-date", default=default_start.isoformat(), help="YYYY-MM-DD, Pacific Time.")
    parser.add_argument("--end-date", default=yesterday.isoformat(), help="YYYY-MM-DD, Pacific Time.")
    parser.add_argument(
        "--search-types",
        nargs="+",
        choices=SEARCH_TYPES,
        default=["web"],
        help="Search surfaces to export (default: web).",
    )
    parser.add_argument(
        "--reports",
        nargs="+",
        choices=tuple(REPORTS),
        default=DEFAULT_REPORTS,
        help="Performance reports to export (default: all except hours). "
        "'hours' uses dataState=hourly_all and only covers the last 10 days.",
    )
    parser.add_argument(
        "--filter",
        dest="filters",
        nargs=3,
        action="append",
        default=[],
        metavar=("DIMENSION", "OPERATOR", "EXPRESSION"),
        help=f"Filter performance rows; repeatable, combined with AND. "
        f"DIMENSION: {', '.join(FILTER_DIMENSIONS)}. OPERATOR: {', '.join(FILTER_OPERATORS)}.",
    )
    parser.add_argument("--data-state", choices=("final", "all"), default="final")
    parser.add_argument("--inspect-urls", type=Path, help="Text file containing one fully-qualified URL per line.")
    parser.add_argument("--inspection-language", default="en-US")
    parser.add_argument(
        "--max-inspections",
        type=int,
        default=500,
        help=f"Inspect at most this many URLs (default: 500; API quota: {MAX_INSPECTIONS_PER_DAY}/property/day).",
    )
    parser.add_argument(
        "--inspection-delay",
        type=float,
        default=0.2,
        help="Seconds to wait between URL inspections (default: 0.2).",
    )
    parser.add_argument("--output", type=Path, default=Path("exports"))
    parser.add_argument("--list-sites", action="store_true", help="List accessible properties and exit.")
    args = parser.parse_args(argv)

    for dimension, operator, _ in args.filters:
        if dimension not in FILTER_DIMENSIONS:
            parser.error(f"--filter dimension must be one of: {', '.join(FILTER_DIMENSIONS)}")
        if operator not in FILTER_OPERATORS:
            parser.error(f"--filter operator must be one of: {', '.join(FILTER_OPERATORS)}")
    if not 1 <= args.max_inspections <= MAX_INSPECTIONS_PER_DAY:
        parser.error(f"--max-inspections must be between 1 and {MAX_INSPECTIONS_PER_DAY}.")
    if args.inspection_delay < 0:
        parser.error("--inspection-delay must not be negative.")
    return args


def validate_dates(start: str, end: str) -> None:
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise SystemExit("Dates must use YYYY-MM-DD.") from exc
    if start_date > end_date:
        raise SystemExit("--start-date must be before or equal to --end-date.")


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_credentials(credentials_path: Path, token_path: Path, open_browser: bool = True, timeout: int = 300):
    if not credentials_path.exists():
        raise SystemExit(
            f"Missing credentials file: {credentials_path}\n"
            "Download OAuth Desktop credentials from Google Cloud and save them at that path."
        )

    config = json.loads(credentials_path.read_text(encoding="utf-8"))
    if config.get("type") == "service_account":
        return ServiceAccountCredentials.from_service_account_file(str(credentials_path), scopes=SCOPES)

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            print(f"Stored token could not be refreshed ({exc}); starting a new sign-in.", file=sys.stderr)
            credentials = None
    if not credentials or not credentials.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        try:
            credentials = flow.run_local_server(port=0, open_browser=open_browser, timeout_seconds=timeout)
        except AttributeError as exc:  # WSGITimeoutError subclasses AttributeError.
            raise SystemExit(
                f"OAuth sign-in did not complete within {timeout} seconds. On a headless machine, sign in once "
                "on a computer with a browser and copy token.json, or use a service account."
            ) from exc
    write_private(token_path, credentials.to_json())
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


def build_filter_groups(filters: list[list[str]]) -> list[dict[str, Any]]:
    if not filters:
        return []
    return [
        {
            "groupType": "and",
            "filters": [
                {"dimension": dimension, "operator": operator, "expression": expression}
                for dimension, operator, expression in filters
            ],
        }
    ]


def fetch_all_rows(service, site_url: str, body: dict[str, Any], label: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Page through a Search Analytics query; return rows and response context."""
    rows: list[dict[str, Any]] = []
    context: dict[str, Any] = {}
    start_row = 0
    while True:
        page_body = {**body, "rowLimit": ROW_LIMIT, "startRow": start_row}
        response = service.searchanalytics().query(siteUrl=site_url, body=page_body).execute(num_retries=3)
        if "responseAggregationType" in response:
            context["responseAggregationType"] = response["responseAggregationType"]
        if response.get("metadata"):
            context["metadata"] = response["metadata"]
        batch = response.get("rows", [])
        rows.extend(batch)
        print(f"  {label}: {len(rows):,} rows", flush=True)
        if len(batch) < ROW_LIMIT:
            return rows, context
        start_row += ROW_LIMIT


def is_unsupported(exc: HttpError, search_type: str, dimensions: list[str]) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    return search_type in LIMITED_SEARCH_TYPES and status == 400 and "query" in dimensions


def export_performance(service, site_url: str, args: argparse.Namespace, output: Path) -> tuple[list, list, list]:
    reports: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    warnings: list[str] = []
    filter_groups = build_filter_groups(args.filters)
    hourly_floor = (pacific_today() - timedelta(days=HOURLY_DAYS)).isoformat()

    for search_type in args.search_types:
        for report_name in args.reports:
            dimensions = REPORTS[report_name]
            data_state = "hourly_all" if report_name == "hours" else args.data_state
            label = f"{search_type}/{report_name}"
            if report_name == "hours" and args.start_date < hourly_floor:
                warnings.append(
                    f"{label}: hourly data only covers about the last {HOURLY_DAYS} days; "
                    f"rows before {hourly_floor} will be missing."
                )
            body: dict[str, Any] = {
                "startDate": args.start_date,
                "endDate": args.end_date,
                "dimensions": dimensions,
                "type": search_type,
                "dataState": data_state,
            }
            if filter_groups:
                body["dimensionFilterGroups"] = filter_groups
            entry: dict[str, Any] = {
                "report": label,
                "searchType": search_type,
                "dimensions": dimensions,
                "dataState": data_state,
            }
            try:
                rows, context = fetch_all_rows(service, site_url, body, label)
            except HttpError as exc:
                if is_unsupported(exc, search_type, dimensions):
                    entry.update(status="unsupported", detail=str(exc))
                    print(f"  {label}: not supported for this search type", flush=True)
                else:
                    entry.update(status="error", detail=str(exc))
                    print(f"WARNING: {label}: {exc}", file=sys.stderr)
                    errors.append({"report": label, "error": str(exc)})
                reports.append(entry)
                continue
            filename = f"performance_{search_type}_{report_name}.csv"
            write_csv(output / filename, dimensions, rows)
            entry.update(status="ok", file=filename, rows=len(rows), **context)
            reports.append(entry)
    return reports, errors, warnings


def list_sitemaps(service, site_url: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """List submitted sitemaps and, recursively, the children of sitemap indexes."""
    sitemaps: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    pending: list[str | None] = [None]
    while pending:
        index = pending.pop(0)
        request = {"siteUrl": site_url}
        if index:
            request["sitemapIndex"] = index
        try:
            response = service.sitemaps().list(**request).execute(num_retries=3)
        except HttpError as exc:
            errors.append({"report": f"sitemaps/{index or 'root'}", "error": str(exc)})
            continue
        for item in response.get("sitemap", []):
            path = item.get("path", "")
            if path in seen:
                continue
            seen.add(path)
            sitemaps.append({**item, "parentIndex": index})
            if item.get("isSitemapsIndex"):
                pending.append(path)
    return sitemaps, errors


def clean_urls(lines: Iterable[str]) -> list[str]:
    urls = []
    for line in lines:
        value = line.strip()
        if value and not value.startswith("#"):
            urls.append(value)
    return list(dict.fromkeys(urls))


def inspect_urls(service, site_url: str, args: argparse.Namespace, output: Path) -> tuple[dict, list, list]:
    urls = clean_urls(args.inspect_urls.read_text(encoding="utf-8-sig").splitlines())
    warnings: list[str] = []
    if len(urls) > args.max_inspections:
        warnings.append(
            f"url_inspections: {len(urls)} URLs supplied, only the first {args.max_inspections} were inspected "
            "(--max-inspections)."
        )
        urls = urls[: args.max_inspections]

    path = output / "url_inspections.json"
    inspections: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for index, url in enumerate(urls, start=1):
        if index > 1 and args.inspection_delay:
            time.sleep(args.inspection_delay)
        print(f"  inspecting {index}/{len(urls)}: {url}", flush=True)
        try:
            result = (
                service.urlInspection()
                .index()
                .inspect(body={"inspectionUrl": url, "siteUrl": site_url, "languageCode": args.inspection_language})
                .execute(num_retries=3)
            )
            inspections.append({"url": url, **result})
        except HttpError as exc:
            inspections.append({"url": url, "error": str(exc)})
            errors.append({"report": f"url_inspection/{url}", "error": str(exc)})
        # Written after every URL so an interrupted run keeps its progress.
        write_json(path, inspections)

    summary = {
        "file": path.name,
        "requested": len(urls),
        "succeeded": len(urls) - len(errors),
        "failed": len(errors),
    }
    return summary, errors, warnings


def safe_site_name(site_url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.-]+", "_", site_url).strip("_") or "site"


def usable(item: dict[str, Any]) -> bool:
    return item.get("permissionLevel") not in UNUSABLE_PERMISSIONS


def choose_site(properties: list[dict[str, Any]], requested: str | None) -> str:
    by_url = {item["siteUrl"]: item for item in properties}
    usable_urls = [url for url, item in by_url.items() if usable(item)]
    choices = "\n".join(f"  - {url}" for url in usable_urls) or "  (none)"
    if requested:
        if requested not in by_url:
            raise SystemExit(f"Property not accessible: {requested}\nAccessible properties:\n{choices}")
        if not usable(by_url[requested]):
            raise SystemExit(
                f"Property is not verified for this account: {requested}\n"
                "Verify it in Search Console or ask an owner for access.\n"
                f"Usable properties:\n{choices}"
            )
        return requested
    if len(usable_urls) == 1:
        return usable_urls[0]
    raise SystemExit(f"Choose a property with --site. Accessible properties:\n{choices}")


def run_directory(base: Path, site_url: str, args: argparse.Namespace, started: datetime) -> Path:
    """A fresh folder per run, so files from earlier runs are never mistaken for current results."""
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    return base / safe_site_name(site_url) / f"{args.start_date}_to_{args.end_date}" / f"{stamp}_{args.data_state}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    validate_dates(args.start_date, args.end_date)
    credentials = load_credentials(args.credentials, args.token, not args.no_browser, args.auth_timeout)
    service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)

    properties_response = service.sites().list().execute(num_retries=3)
    properties = properties_response.get("siteEntry", [])
    if args.list_sites:
        for item in properties:
            note = "  (unverified: cannot be queried)" if not usable(item) else ""
            print(f"{item.get('permissionLevel', '?'):20} {item['siteUrl']}{note}")
        return 0

    site_url = choose_site(properties, args.site)
    started = datetime.now(timezone.utc)
    output = run_directory(args.output, site_url, args, started)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "properties.json", properties_response)

    sitemaps, errors = list_sitemaps(service, site_url)
    write_json(output / "sitemaps.json", {"sitemap": sitemaps})

    reports, report_errors, warnings = export_performance(service, site_url, args, output)
    errors.extend(report_errors)

    inspection_summary = None
    if args.inspect_urls:
        inspection_summary, inspection_errors, inspection_warnings = inspect_urls(service, site_url, args, output)
        errors.extend(inspection_errors)
        warnings.extend(inspection_warnings)

    write_json(
        output / "run_metadata.json",
        {
            "generatedAt": started.isoformat(timespec="seconds"),
            "siteUrl": site_url,
            "startDate": args.start_date,
            "endDate": args.end_date,
            "timeZone": "America/Los_Angeles",
            "searchTypes": args.search_types,
            "dataState": args.data_state,
            "filters": build_filter_groups(args.filters),
            "sitemapCount": len(sitemaps),
            "reports": reports,
            "rowCounts": {entry["report"]: entry["rows"] for entry in reports if entry["status"] == "ok"},
            "urlInspections": inspection_summary,
            "warnings": warnings,
            "errors": errors,
        },
    )
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    status = "with errors" if errors else "successfully"
    print(f"\nExport finished {status}: {output.resolve()}")
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HttpError as exc:
        raise SystemExit(f"Google API error: {exc}") from exc
