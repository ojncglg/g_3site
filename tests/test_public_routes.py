"""GET-only regressions for public pricing and internal-tool access."""
import re
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree
from urllib.robotparser import RobotFileParser

import app as site


class PublicRouteTests(unittest.TestCase):
    aliases = ("/prices", "/price-calculator", "/g3-internal/agency-price-lab")

    def setUp(self):
        self.client = site.app.test_client()

    def get(self, path, **kwargs):
        return self.client.get(path, base_url="https://www.g3industries.io", **kwargs)

    def test_calculator_routes_and_deployed_file_are_removed(self):
        routes = {rule.rule for rule in site.app.url_map.iter_rules()}
        for path in self.aliases:
            with self.subTest(path=path):
                self.assertNotIn(path, routes)
                response = self.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b"Monthly COGS", response.data)
                self.assertNotIn(b"breakEvenPPOM", response.data)
        self.assertFalse((Path(site.BASE_DIR) / "templates/price_calculator.html").exists())
        self.assertEqual(self.get("/static/price_calculator.html").status_code, 404)

    def test_robots_blocks_retired_calculator_urls_and_admin(self):
        response = self.get("/robots.txt")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        robots = RobotFileParser()
        robots.parse(response.get_data(as_text=True).splitlines())
        for agent in ("Googlebot", "Bingbot"):
            for path in (*self.aliases, "/admin/leads"):
                self.assertFalse(robots.can_fetch(agent, path))
            self.assertTrue(robots.can_fetch(agent, "/packages"))

    def test_public_pages_and_assets_have_no_retired_calculator_references(self):
        sitemap = ElementTree.fromstring(self.get("/sitemap.xml").data)
        urls = {node.text for node in sitemap.findall("{*}url/{*}loc")}
        paths = {url.removeprefix("https://www.g3industries.io") for url in urls}
        for path in sorted(paths | {"/sales", "/pitch", "/events", "/sticker-2026"}):
            with self.subTest(path=path):
                with patch.object(site, "public_guest_list", return_value=([], 0)):
                    response = self.get(path)
                self.assertEqual(response.status_code, 200)
                for retired in self.aliases:
                    self.assertNotIn(retired, response.get_data(as_text=True))
        for directory in ("templates", "static"):
            for file in (Path(site.BASE_DIR) / directory).rglob("*"):
                if file.is_file() and file.suffix in (".html", ".js", ".css", ".json", ".xml", ".txt"):
                    text = file.read_text()
                    for retired in (*self.aliases, "price_calculator"):
                        self.assertNotIn(retired, text, str(file))
                    for calculation in ("const VAR_RATE", "breakEvenPPOM", "modeledAnnual", "monthlyCogs"):
                        self.assertNotIn(calculation, text, str(file))

    def test_public_package_pages_expose_no_dollar_figures_or_price_tables(self):
        for path in ("/sales", "/packages"):
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIsNone(re.search(r"\$\s*\d", html))
                for internal_name in ("const prices", "monthlyFloor", "setupFee", "addonPrice"):
                    self.assertNotIn(internal_name, html)
                self.assertIn("Essential", html)
                self.assertIn("Operations", html)
                self.assertIn("Command Suite", html)
                self.assertNotIn("Enterprise", html)
                self.assertIn(
                    "G3 is priced per sworn officer per month, billed annually. "
                    "Final quotes are confirmed after scope review.", html
                )
                self.assertNotRegex(html, r'<article[^>]*id="founding-pilot"')
                essential = re.search(r'<article[^>]*id="essential"[^>]*>(.*?)</article>', html, re.S).group(1)
                self.assertEqual(essential.count("<li>"), 2)
                for feature in ("Vacation Bidding", "Training Day", "Extra Duty", "Anonymous Tips", "Tow Logs", "add-on"):
                    self.assertNotIn(feature, essential)
                if path == "/sales":
                    self.assertIn("Founding Pilot", html)
                    selector = re.search(r'<select id="agencyPackage"[^>]*>(.*?)</select>', html, re.S).group(1)
                    self.assertEqual(re.findall(r'<option value="([^"]+)"', selector), ["essential", "operations", "command"])

    def test_sitemap_contains_public_additions_and_excludes_unlisted_pages(self):
        response = self.get("/sitemap.xml")
        root = ElementTree.fromstring(response.data)
        urls = {node.text for node in root.findall("{*}url/{*}loc")}
        prefix = "https://www.g3industries.io"
        for path in ("/packages", "/contact"):
            self.assertIn(prefix + path, urls)
        for path in (*self.aliases, "/sales", "/pitch", "/events", "/sticker-2026", "/admin/leads", "/pricing"):
            self.assertNotIn(prefix + path, urls)

    def test_pricing_redirect_and_unknown_route(self):
        response = self.get("/pricing")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/packages")
        self.assertEqual(self.get("/unknown-review-route").status_code, 404)

    def test_map_permission_is_limited_to_contact(self):
        contact = self.get("/contact").headers["Content-Security-Policy"]
        other = self.get("/packages").headers["Content-Security-Policy"]
        self.assertIn("frame-src 'self' https://challenges.cloudflare.com https://www.google.com;", contact)
        self.assertEqual(other, site.DEFAULT_CSP)
        self.assertEqual(contact.replace(" https://www.google.com;", ";"), other)


if __name__ == "__main__":
    unittest.main()
