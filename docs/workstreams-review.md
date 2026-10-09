# Homepage and buying-decision work streams

Implemented on `feature/operational-workflows-time-recovery` from main commit `ae75ac7`, for a pull request against main. No production deployment is part of this task.

## Changes

- A: Replaced hero copy with the supplied headline and support text. Kept the suite showcase video, poster, and media caption. Primary CTA is Request a Live Demo at `#demo`; secondary CTA is See How It Works at `#how`. Kept the original primary CTA analytics attributes and added tracking to new actions.
- B: Replaced the homepage benchmark block with six measured problem cards. Removed unsupported time and turnaround figures from that block.
- C: Replaced the homepage feature grid with Schedule, Request, Approve, Staff, and Document workflows, using existing product terminology. Kept `#products` and all product destination anchors.
- D: Added Officer, Supervisor, and Command perspectives using existing guide screenshots: `requests.png`, `time_off_approval.png`, and `dayview.png`. Long screenshots scroll within their labeled region; full images are accessible by link. No new product images or fabricated UI were created.
- E: Added the compact founder band with the existing, owner-supplied biography facts and a link to About. No agency or educational endorsement is implied.
- F: Added the time-recovery estimator at `/#time-recovery`, with labeled inputs, blank assumptions, live result updates after the initial calculation, accessible validation, keyboard access, and the required planning disclaimer. It contains no currency or payroll-savings estimates.
- G: Added only the compact vendor subsection to About. Address and Delaware license were verified against the state dataset. Unconfirmed identifiers stay in Jinja TODO comments and render as Pending owner verification.
- H: Replaced the two generic article-end action buttons with exactly one contextual resource CTA per article. Scheduling/module topics go to the appropriate product section; administrative-capacity topics go to the time estimator; the implementation/change article goes to the existing pilot section. `BLOG_POSTS`, article prose, SEO metadata, and structured-data source are unchanged.

## Files changed

- `templates/index.html`
- `templates/_home_workflows.html`
- `templates/_time_recovery_estimator.html`
- `templates/about.html`
- `templates/_vendor_information.html`
- `templates/blog_post.html`
- `templates/_blog_contextual_cta.html`
- `static/style.css`
- `static/js/time-recovery.js`
- `tests/test_workstreams.py`
- `docs/workstreams-review.md`

## Estimator assumptions

Annual scheduling hours = agency-wide supervisor/admin weekly scheduling hours × 52.

Annual recoverable hours = annual scheduling hours × visitor-supplied reducible percentage ÷ 100.

Sworn-personnel count supplies agency context and does not multiply the already agency-wide workload. The widget makes no savings-percentage claim and supplies no default reduction percentage. Zero weekly hours and reductions from zero to 100 percent are supported. Invalid or non-finite inputs clear previous results instead of retaining a stale estimate. Results are displayed to one decimal place at most.

## Vendor verification and owner TODOs

Primary source checked October 9, 2026: [Delaware Division of Revenue record](https://data.delaware.gov/resource/5zy2-grhr.json?license_number=2026709491), from the [Delaware Business Licenses dataset](https://data.delaware.gov/Licenses-and-Certifications/Delaware-Business-Licenses/5zy2-grhr).

The record lists license 2026709491, address 8 Gurnsey Dr, Newark, DE 19713, valid January 1 through December 31, 2026. Its business name is GRIGORI LOPEZGARCIA, rather than the LLC name supplied in the brief. The vendor block identifies that license holder explicitly.

- TODO(owner): Confirm the legal vendor entity and reconcile the personal-name license with G3 Industries LLC.
- TODO(owner): Verify EIN 39-4519448 belongs to that entity.
- TODO(owner): Verify New Castle County vendor number 112316 belongs to that entity.
- TODO(owner): Clarify the navigation discrepancy. The brief says Security stays out of navigation, but current main already includes Security in both desktop and mobile menus. Navigation is byte-for-byte unchanged under the explicit instruction to leave it alone. Removing those existing links requires resolution of that conflicting instruction.

All three unverified vendor values are withheld from rendered HTML. Suitable existing screenshots were available for all three perspectives, so there are no screenshot TODOs.

## Scope preservation

Verified byte-for-byte preservation of `app.py`, `templates/events.html`, packages and package cards, `templates/base.html`, `templates/products.html`, `templates/blog.html`, sitemap.xml, and robots.txt. The events page and its assets have no changes.

The homepage Built for the badge section, Data migration bullet, Pilot Program section, demo section and heading, original demo JavaScript, and hero media remain unchanged. About differs only by the vendor partial include. The blog template differs only in its article-end CTA rendering.

New CSS is scoped to the screenshot container and estimator output. Existing fonts, palette, buttons, package styling, and navigation are reused.

## Validation

- Eleven unittest regressions pass, including the seven pre-existing route regressions.
- Estimator JavaScript passes Node syntax validation.
- Thirty browser layout checks: homepage and About at 375, 768, 1280, and 1440 pixels; all eleven articles at 375 and 1280 pixels. No horizontal scrolling, clipped controls, missing loaded images, duplicate IDs, or undersized button/input targets were found.
- Browser estimator checks cover normal calculations, fractional hours/percentages, zero hours, zero/100 percent reduction, unchanged totals when only personnel count changes, missing values, negative values, fractional personnel, out-of-range percentages, and overflow. Tab order, focus styling, and keyboard activation pass.
- Hero demo/how-it-works anchors work. All 27 distinct internal links from changed pages resolve, including section anchors and screenshot assets.
- The demo succeeds through its existing browser JavaScript and the Flask handler in local QA. Email delivery, lead storage, challenge verification, and rate-limit persistence were mocked; no production forms were submitted, no emails were sent, and no leads were written.
- No browser JavaScript exceptions or console errors were recorded.
- `git diff --check` passes.

Review artifacts are local only: `/private/tmp/g3-workstreams-browser-report.json` and `/private/tmp/g3-workstreams-*.png`.

## High-impact next steps

Resolve the vendor identity/identifier TODOs before replacing pending fields with factual values. Review the scoped pull request and merge only when ready for Render's main-branch deployment.
