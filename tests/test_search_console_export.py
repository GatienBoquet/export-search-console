"""Offline tests for the exporter, using a fake Search Console service."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "export-search-console" / "scripts" / "search_console_export.py"
spec = importlib.util.spec_from_file_location("search_console_export", SCRIPT)
exporter = importlib.util.module_from_spec(spec)
sys.modules["search_console_export"] = exporter
spec.loader.exec_module(exporter)


class Response:
    status = 400
    reason = "Bad Request"


class Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self, num_retries=0):
        return self.fn()


class FakeService:
    def __init__(self, sites, sitemaps=None, failing=(), inspection_failures=(), bad_filters=False):
        self.sites_entries = sites
        self.sitemap_tree = sitemaps or {None: []}
        self.failing = failing
        self.inspection_failures = inspection_failures
        self.bad_filters = bad_filters
        self.queries = []
        self.inspected = []

    def sites(self):
        return mock.Mock(list=lambda: Call(lambda: {"siteEntry": self.sites_entries}))

    def sitemaps(self):
        def list_(siteUrl, sitemapIndex=None):
            return Call(lambda: {"sitemap": self.sitemap_tree.get(sitemapIndex, [])})

        return mock.Mock(list=list_)

    def searchanalytics(self):
        def query(siteUrl, body):
            self.queries.append(body)

            def run():
                if (body["type"], tuple(body["dimensions"])) in self.failing or (
                    self.bad_filters and "dimensionFilterGroups" in body
                ):
                    raise HttpError(Response(), b'{"error": "unsupported"}')
                response = {"responseAggregationType": "byProperty", "rows": [{"keys": ["k"] * len(body["dimensions"]), "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 2.5}]}
                if body["dataState"] == "all" and "date" in body["dimensions"]:
                    response["metadata"] = {"firstIncompleteDate": "2026-09-27"}
                return response

            return Call(run)

        return mock.Mock(query=query)

    def urlInspection(self):
        def inspect(body):
            self.inspected.append(body)

            def run():
                if body["inspectionUrl"] in self.inspection_failures:
                    raise HttpError(Response(), b"{}")
                return {"inspectionResult": {"indexStatusResult": {"verdict": "PASS"}}}

            return Call(run)

        return mock.Mock(index=lambda: mock.Mock(inspect=inspect))


SITE = "sc-domain:example.com"
OWNER = [{"siteUrl": SITE, "permissionLevel": "siteOwner"}]


class ExporterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, service, *extra):
        argv = ["--site", SITE, "--start-date", "2026-09-01", "--end-date", "2026-09-10", "--output", str(self.dir), *extra]
        with mock.patch.object(exporter, "load_credentials"), mock.patch.object(exporter, "build", return_value=service):
            code = exporter.main(argv)
        runs = list(self.dir.glob("*/*/*/run_metadata.json"))
        self.assertEqual(len(runs), 1)
        return code, runs[0].parent, json.loads(runs[0].read_text(encoding="utf-8"))

    def test_metadata_row_counts_and_aggregation(self):
        code, out, meta = self.run_main(FakeService(OWNER), "--data-state", "all", "--reports", "dates", "pages")
        self.assertEqual(code, 0)
        self.assertEqual(meta["rowCounts"], {"web/dates": 1, "web/pages": 1})
        dates = next(r for r in meta["reports"] if r["report"] == "web/dates")
        self.assertEqual(dates["metadata"], {"firstIncompleteDate": "2026-09-27"})
        self.assertEqual(dates["responseAggregationType"], "byProperty")
        self.assertTrue((out / "performance_web_pages.csv").exists())
        self.assertFalse((out / "performance_web_details.csv").exists())

    def test_filters_and_hourly_state(self):
        service = FakeService(OWNER)
        _, _, meta = self.run_main(service, "--reports", "hours", "--filter", "page", "contains", "/blog/")
        body = service.queries[0]
        self.assertEqual(body["dataState"], "hourly_all")
        self.assertEqual(body["dimensionFilterGroups"][0]["filters"][0], {"dimension": "page", "operator": "contains", "expression": "/blog/"})
        self.assertTrue(any("hourly" in w for w in meta["warnings"]))

    def test_unsupported_dimension_is_not_an_error(self):
        service = FakeService(OWNER, failing={("discover", ("query",)), ("web", ("page",))})
        code, _, meta = self.run_main(service, "--search-types", "web", "discover", "--reports", "queries", "pages")
        statuses = {r["report"]: r["status"] for r in meta["reports"]}
        self.assertEqual(statuses["discover/queries"], "unsupported")
        self.assertEqual(statuses["web/pages"], "error")
        self.assertEqual([e["report"] for e in meta["errors"]], ["web/pages"])
        self.assertEqual(code, 1)

    def test_bad_filter_on_limited_surface_is_an_error(self):
        service = FakeService(OWNER, bad_filters=True)
        code, _, meta = self.run_main(
            service, "--search-types", "discover", "--reports", "queries", "--filter", "query", "includingRegex", "("
        )
        self.assertEqual(meta["reports"][0]["status"], "error")
        self.assertEqual([e["report"] for e in meta["errors"]], ["discover/queries"])
        self.assertEqual(code, 1)

    def test_unsupported_dimension_with_filter_is_still_unsupported(self):
        service = FakeService(OWNER, failing={("discover", ("query",))})
        code, _, meta = self.run_main(
            service, "--search-types", "discover", "--reports", "queries", "--filter", "page", "contains", "/blog/"
        )
        self.assertEqual(meta["reports"][0]["status"], "unsupported")
        self.assertEqual(meta["errors"], [])
        self.assertEqual(code, 0)

    def test_run_directories_are_unique(self):
        args = exporter.parse_args(["--start-date", "2026-09-01", "--end-date", "2026-09-10"])
        started = exporter.datetime(2026, 9, 28, tzinfo=exporter.timezone.utc)
        first = exporter.create_run_directory(self.dir, SITE, args, started)
        second = exporter.create_run_directory(self.dir, SITE, args, started)
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir() and second.is_dir())

    def test_empty_inspection_list_still_writes_file(self):
        urls = self.dir / "urls.txt"
        urls.write_text("# only a comment\n", encoding="utf-8")
        code, out, meta = self.run_main(FakeService(OWNER), "--reports", "dates", "--inspect-urls", str(urls))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((out / "url_inspections.json").read_text(encoding="utf-8")), [])
        self.assertEqual(meta["urlInspections"]["requested"], 0)

    def test_sitemap_indexes_are_expanded(self):
        tree = {
            None: [{"path": "https://example.com/index.xml", "isSitemapsIndex": True}],
            "https://example.com/index.xml": [{"path": "https://example.com/a.xml", "errors": "2"}],
        }
        _, out, meta = self.run_main(FakeService(OWNER, sitemaps=tree), "--reports", "dates")
        sitemaps = json.loads((out / "sitemaps.json").read_text(encoding="utf-8"))["sitemap"]
        self.assertEqual([s["path"] for s in sitemaps], ["https://example.com/index.xml", "https://example.com/a.xml"])
        self.assertEqual(sitemaps[1]["parentIndex"], "https://example.com/index.xml")
        self.assertEqual(meta["sitemapCount"], 2)

    def test_inspection_errors_cap_and_language(self):
        urls = self.dir / "urls.txt"
        urls.write_text("# comment\nhttps://example.com/a\nhttps://example.com/b\nhttps://example.com/c\n", encoding="utf-8")
        service = FakeService(OWNER, inspection_failures={"https://example.com/b"})
        code, out, meta = self.run_main(
            service, "--reports", "dates", "--inspect-urls", str(urls), "--max-inspections", "2", "--inspection-delay", "0"
        )
        self.assertEqual(code, 1)
        self.assertEqual(len(service.inspected), 2)
        self.assertEqual(service.inspected[0]["languageCode"], "en-US")
        self.assertEqual(meta["urlInspections"], {"file": "url_inspections.json", "requested": 2, "succeeded": 1, "failed": 1})
        self.assertEqual(meta["errors"][0]["report"], "url_inspection/https://example.com/b")
        self.assertTrue(any("--max-inspections" in w for w in meta["warnings"]))
        self.assertEqual(len(json.loads((out / "url_inspections.json").read_text(encoding="utf-8"))), 2)

    def test_unverified_property_rejected(self):
        props = [{"siteUrl": SITE, "permissionLevel": "siteUnverifiedUser"}]
        with self.assertRaises(SystemExit) as ctx:
            exporter.choose_site(props, SITE)
        self.assertIn("not verified", str(ctx.exception))
        with self.assertRaises(SystemExit):
            exporter.choose_site(props, None)

    def test_invalid_filter_rejected(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            exporter.parse_args(["--filter", "date", "equals", "x"])

    def test_refresh_error_falls_back_to_sign_in(self):
        secrets = self.dir / "client_secret.json"
        secrets.write_text('{"installed": {}}', encoding="utf-8")
        token = self.dir / "token.json"
        token.write_text("{}", encoding="utf-8")
        stale = mock.Mock(expired=True, refresh_token="r")
        stale.refresh.side_effect = exporter.RefreshError("revoked")
        fresh = mock.Mock(valid=True)
        fresh.to_json.return_value = "{}"
        flow = mock.Mock()
        flow.run_local_server.return_value = fresh
        with mock.patch.object(exporter.Credentials, "from_authorized_user_file", return_value=stale), mock.patch.object(
            exporter.InstalledAppFlow, "from_client_secrets_file", return_value=flow
        ), mock.patch("sys.stderr"):
            self.assertIs(exporter.load_credentials(secrets, token, open_browser=False, timeout=5), fresh)
        flow.run_local_server.assert_called_once_with(port=0, open_browser=False, timeout_seconds=5)
        if sys.platform != "win32":
            self.assertEqual(token.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
