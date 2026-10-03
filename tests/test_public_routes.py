"""GET-only regressions for public pricing and internal-tool access."""
import base64
import re
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

import app as site


class PublicRouteTests(unittest.TestCase):
    aliases = ("/prices", "/price-calculator", "/g3-internal/agency-price-lab")

    def setUp(self):
        self.client = site.app.test_client()

    def get(self, path, **kwargs):
        return self.client.get(path, base_url="https://www.g3industries.io", **kwargs)

    def test_calculator_is_unavailable_without_configured_password(self):
        with patch.object(site, "ADMIN_DASHBOARD_PASSWORD", ""):
            for path in self.aliases:
                with self.subTest(path=path):
                    response = self.get(path)
                    self.assertEqual(response.status_code, 404)
                    self.assertIn("noindex", response.headers["X-Robots-Tag"])
                    self.assertIn("no-store", response.headers["Cache-Control"])
                    self.assertNotIn(b"Monthly COGS", response.data)

    def test_every_calculator_alias_requires_valid_credentials(self):
        with patch.object(site, "ADMIN_DASHBOARD_USERNAME", "review"), patch.object(
            site, "ADMIN_DASHBOARD_PASSWORD", "test-only-credential"
        ):
            for path in self.aliases:
                for credentials in (None, "review:incorrect", "wrong:test-only-credential"):
                    with self.subTest(path=path, credentials=credentials):
                        headers = {}
                        if credentials:
                            token = base64.b64encode(credentials.encode()).decode()
                            headers["Authorization"] = "Basic " + token
                        response = self.get(path, headers=headers)
                        self.assertEqual(response.status_code, 401)
                        self.assertIn("Basic", response.headers["WWW-Authenticate"])
                        self.assertIn("noindex", response.headers["X-Robots-Tag"])
                        self.assertIn("no-store", response.headers["Cache-Control"])
                        self.assertNotIn(b"Monthly COGS", response.data)
                token = base64.b64encode(b"review:test-only-credential").decode()
                response = self.get(path, headers={"Authorization": "Basic " + token})
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Monthly COGS", response.data)
                self.assertIn("noindex", response.headers["X-Robots-Tag"])
                self.assertIn("no-store", response.headers["Cache-Control"])

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
                self.assertIn("Department", html)
                self.assertIn("Enterprise", html)

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
