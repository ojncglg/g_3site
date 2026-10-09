"""Scoped marketing regressions, with demo side effects mocked locally."""
from html.parser import HTMLParser
import re
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import app as site

class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

class WorkstreamTests(unittest.TestCase):
    def setUp(self):
        self.client = site.app.test_client()
    def get(self, path):
        return self.client.get(path, base_url='https://www.g3industries.io')
    def test_home_media_ctas_and_estimator_semantics(self):
        response = self.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        tags = Markup(html).tags
        self.assertEqual(sum(tag == 'h1' for tag, attrs in tags), 1)
        self.assertIn('Stop Managing Your Police Department With Spreadsheets.', html)
        self.assertIn('Scheduling shouldn&#39;t consume your command staff&#39;s time.'.replace('&#39;', "'"), html)
        self.assertIn('/static/img/thumbnail/suiteshowcase.png', html)
        self.assertIn('/static/videos/showcase.webm', html)
        self.assertIn('/static/videos/showcase.mp4', html)
        hero = re.search(r'<section class="hero-bg.*?</section>', html, re.S).group()
        for target in ('#demo', '#how'):
            self.assertIn('href="' + target + '"', hero)
        self.assertIn('data-track-label="request_demo"', hero)
        self.assertNotIn('32 hrs/mo', html)
        ids = [attrs['id'] for tag, attrs in tags if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        labels = {attrs['for'] for tag, attrs in tags if tag == 'label' and 'for' in attrs}
        for field in ('sworn-personnel', 'scheduling-hours', 'reducible-time'):
            self.assertIn(field, labels)
            input_attrs = next(attrs for tag, attrs in tags if tag == 'input' and attrs.get('id') == field)
            self.assertIn('required', input_attrs)
            self.assertNotIn('value', input_attrs)
        estimator = re.search(r'<section id="time-recovery".*?</section>', html, re.S).group()
        self.assertNotRegex(estimator, r'\$|USD|salary|hourly rate')
        self.assertIn('not reduced payroll expenditure', estimator)
        self.assertIn('not guaranteed savings', estimator)
    def test_every_blog_has_one_contextual_cta_with_resolving_destination(self):
        self.assertEqual(len(site.BLOG_POSTS), 11)
        expected_special = {
            'why-change-is-so-hard-in-policing': '/#pilot',
            'how-much-time-are-administrative-tasks-worth': '/#time-recovery',
            'court-overtime-is-a-scheduling-problem': '/#time-recovery',
        }
        for post in site.BLOG_POSTS:
            with self.subTest(slug=post['slug']):
                response = self.get('/blog/' + post['slug'])
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertEqual(html.count('data-contextual-cta='), 1)
                cta = re.search(r'<div data-contextual-cta=.*?</div>', html, re.S).group()
                links = [attrs for tag, attrs in Markup(cta).tags if tag == 'a']
                self.assertEqual(len(links), 1)
                href = links[0]['href']
                if post['slug'] in expected_special:
                    self.assertEqual(href, expected_special[post['slug']])
                else:
                    self.assertTrue(href.startswith('/products'))
                self.assertEqual(links[0]['data-track-event'], 'cta_click')
                self.assertIn('data-track-label', links[0])
                self.assertNotIn('\u2014', cta)
                destination = urlsplit(href)
                target = self.get(destination.path)
                self.assertEqual(target.status_code, 200)
                if destination.fragment:
                    self.assertIn('id="' + destination.fragment + '"', target.get_data(as_text=True))
    def test_unverified_vendor_identifiers_are_not_published(self):
        html = self.get('/about').get_data(as_text=True)
        self.assertIn('id="vendor-information"', html)
        self.assertIn('2026709491, issued to Grigori LopezGarcia', html)
        self.assertIn('8 Gurnsey Dr, Newark, DE 19713', html)
        for unverified in ('G3 Industries LLC', '39-4519448', '112316'):
            self.assertNotIn(unverified, html)
        self.assertEqual(html.count('Pending owner verification'), 3)
    def test_demo_handler_accepts_local_submission_with_mocked_side_effects(self):
        with patch.object(site, 'append_lead') as store, patch.object(site, 'send_demo_email', return_value=(True, '')) as email, patch.object(site, 'check_and_record_rate_limit', return_value=(True, '')), patch.object(site, 'verify_turnstile_token', return_value=(True, '')):
            response = self.client.post('/demo', base_url='https://www.g3industries.io', headers={'Accept':'application/json'}, data={'name':'Local QA', 'agency':'Example Agency', 'email':'qa@example.invalid', 'agency_size':site.AGENCY_SIZE_OPTIONS[1], 'interest':site.INTEREST_OPTIONS[0], 'form_start':str(site.utc_now_ms() - 5000)})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()['ok'])
            store.assert_called_once()
            email.assert_called_once()
            self.assertEqual(store.call_args.args[0]['email'], 'qa@example.invalid')
            self.assertEqual(store.call_args.args[0]['agency_size'], site.AGENCY_SIZE_OPTIONS[1])
            self.assertEqual(store.call_args.args[0]['interest'], site.INTEREST_OPTIONS[0])
            store.reset_mock(); email.reset_mock()
            response = self.client.post('/demo', base_url='https://www.g3industries.io', headers={'Accept':'application/json'}, data={'name':'Local QA'})
            self.assertEqual(response.status_code, 400)
            store.assert_not_called(); email.assert_not_called()

if __name__ == '__main__':
    unittest.main()
