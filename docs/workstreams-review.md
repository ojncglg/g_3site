# Homepage and buying-decision work streams

Implemented on `feature/operational-workflows-time-recovery` from main commit `ae75ac7`, for a pull request against main. No production deployment is part of this task.

## Changes

- A: Replaced hero copy with the supplied headline and support text. Kept the suite showcase video, poster, and media caption. Primary CTA is Request a Live Demo at `#demo`; secondary CTA is See How It Works at `#how`. Kept the original primary CTA analytics attributes and added tracking to new actions.
- B: Replaced the homepage benchmark block with six measured problem cards. Removed unsupported time and turnaround figures from that block.
- C: Replaced the homepage feature grid with Schedule, Request, Approve, Staff, and Document workflows, using existing product terminology. Kept `#products` and all product destination anchors.
- D: Added Officer, Supervisor, and Command perspectives using existing guide screenshots: `requests.png`, `time_off_approval.png`, and `dayview.png`. Long screenshots scroll within their labeled region; full images are accessible by link. No new product images or fabricated UI were created.
- E: Added the compact founder band with the existing, owner-supplied biography facts and a link to About. No agency or educational endorsement is implied.
- F: Added the time-recovery estimator at `/#time-recovery`, with labeled inputs, blank assumptions, live result updates after the initial calculation, accessible validation, keyboard access, and the required planning disclaimer. It contains no currency or payroll-savings estimates.
- G: Added only the compact vendor subsection to About. All five vendor details match the owner's confirmed records, including the supplied identifier prefixes.
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

## Owner-confirmed details and scope

The owner confirmed these details from their records on October 9, 2026:

- Legal name: G3 Industries LLC
- EIN: 39-4519448
- Delaware business license: #2026709491
- New Castle County vendor: #112316
- Address: 8 Gurnsey Dr, Newark, DE 19713

The owner also confirmed that navigation must remain exactly as it is. No navigation links were added, removed, or renamed. Security navigation is out of scope for this PR.

Suitable existing screenshots were available for all three perspectives. No owner-input or screenshot TODOs remain.

## Scope preservation

Verified byte-for-byte preservation against the starting commit `ae75ac7` of `app.py`, `templates/events.html`, packages and package cards, `templates/base.html`, `templates/products.html`, `templates/blog.html`, sitemap.xml, and robots.txt. The events page and its assets have no changes in this branch.

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
- After the owner confirmed vendor details and navigation scope, reran all eleven tests, the protected-scope comparison against the starting commit, all 27 internal-link checks, and `git diff --check`. All pass.

Review artifacts are local only: `/private/tmp/g3-workstreams-browser-report.json` and `/private/tmp/g3-workstreams-*.png`.

## High-impact next steps

Review the scoped pull request and merge only when ready for Render's main-branch deployment.
