"""GET-only regressions for public pricing and internal-tool access."""
import re
import unittest
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

    def test_calculator_is_accessible_without_credentials_and_not_indexed(self):
        for password in ("", "test-only-credential"):
            with patch.object(site, "ADMIN_DASHBOARD_PASSWORD", password):
                for path in self.aliases:
                    with self.subTest(path=path, password_configured=bool(password)):
                        response = self.get(path)
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn("WWW-Authenticate", response.headers)
                        self.assertIn(b"Monthly COGS", response.data)
                        self.assertIn(b'<meta name="robots" content="noindex,nofollow,noarchive">', response.data)
                        self.assertIn("noindex", response.headers["X-Robots-Tag"])
                        self.assertIn("no-store", response.headers["Cache-Control"])
                        self.assertIn("private", response.headers["Cache-Control"])

    def test_robots_allows_reading_calculator_noindex_and_still_blocks_admin(self):
        response = self.get("/robots.txt")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        robots = RobotFileParser()
        robots.parse(response.get_data(as_text=True).splitlines())
        for agent in ("Googlebot", "Bingbot"):
            for path in self.aliases:
                self.assertTrue(robots.can_fetch(agent, path))
            self.assertFalse(robots.can_fetch(agent, "/admin/leads"))

    def test_public_package_pages_expose_no_dollar_figures_or_price_tables(self):
        for path in ("/sales", "/packages"):
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIsNone(re.search(r"\$\s*\d", html))
                for internal_name in ("const prices", "monthlyFloor", "setupFee", "addonPrice"):
                    self.assertNotIn(internal_name, html)
                self.assertIn("Founding Pilot", html)
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
