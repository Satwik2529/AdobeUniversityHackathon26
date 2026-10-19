# AI-readiness audit: books.toscrape.com

Audited 2026-10-08T08:51:42Z. This audit is read-only and recommend-only: **no changes were made to the site.** Everything below is advice for whoever owns it.

It looks at two things. First, whether AI assistants can find, read, understand and quote this brand at all. Second, whether a person who arrives from one of those answers can find what they came for.

## What we found

| Severity | Count | What it means |
| --- | --- | --- |
| Critical | 0 | Structurally blocks the brand from being found, read or cited |
| High | 2 | Badly degrades a key page type, or a key fact is contradicted |
| Medium | 6 | Real degradation on part of the site |
| Low | 2 | Hygiene, small compounding effects |
| Info | 0 | Deliberate configuration or context, not a defect |

## Do these first

1. **Publish a robots.txt that declares the sitemap and states an explicit policy for training and retrieval crawlers.**
   Owner: engineering. Effort: trivial. (Finding F-004)
2. **Publish a sitemap with accurate lastmod values and declare it in robots.txt.**
   Owner: engineering. Effort: config. (Finding F-005)
3. **Add one Organization (or LocalBusiness, if there is a physical location) node to the homepage, in JSON-LD, with a stable identifier.**
   Owner: engineering. Effort: template-change. (Finding F-001)

## Findings

### Can a machine find it

#### F-003 — Content pages declare no canonical URL (MEDIUM)

**What we observed.** 21 of 21 sampled content pages carry no rel=canonical link. Without one, a crawler that reaches the same content through a different URL, for example with a tracking parameter or a trailing slash, has to guess which address is the real one. Examples: https://books.toscrape.com/, https://books.toscrape.com/catalogue/1000-places-to-see-before-you-die_1/index.html, https://books.toscrape.com/catalogue/category/books/add-a-comment_18/index.html.

**Why it matters.** A canonical consolidates the signals for one piece of content onto one address. Without it, parameterised and duplicated variants compete with each other and none accumulates the full weight.

**What to do.** Add a self-referencing rel=canonical to every content template, pointing at the absolute preferred URL of that page.

- Emit the canonical from the route's own definition so it is always the page's preferred absolute URL.
- Use the same scheme, host and trailing-slash form as the sitemap, so the two do not disagree.

Priority: medium. Effort: template-change. Owner: engineering. Check it worked: Request each URL and confirm the canonical matches the URL that was requested.

Affected pages (sample): `https://books.toscrape.com/`, `https://books.toscrape.com/catalogue/1000-places-to-see-before-you-die_1/index.html`, `https://books.toscrape.com/catalogue/category/books/add-a-comment_18/index.html`, `https://books.toscrape.com/catalogue/category/books/art_25/index.html`, `https://books.toscrape.com/catalogue/category/books/autobiography_27/index.html`

#### F-004 — No robots.txt is published (MEDIUM)

**What we observed.** A request for https://books.toscrape.com/robots.txt returned 404. No robots.txt means no crawler restrictions, so this does not block anything. It does mean there is nowhere to declare a sitemap or to state a deliberate policy for training versus retrieval crawlers.

**Why it matters.** Absence does not shut the discovered gate, but it forfeits the one place to declare a sitemap and to record an intentional crawler policy, so a future change can silently remove citation eligibility.

**What to do.** Publish a robots.txt that declares the sitemap and states an explicit policy for training and retrieval crawlers.

- Serve /robots.txt as text/plain.
- Add a Sitemap: line pointing at the sitemap index.
- Decide deliberately whether to allow training crawlers; leaving it undeclared is a decision made by default rather than on purpose.
- Keep retrieval and user-triggered agents allowed unless there is a specific reason not to.

Priority: high. Effort: trivial. Owner: engineering. Check it worked: Request /robots.txt and confirm a 200 with text/plain and a resolvable Sitemap line.

Affected pages (sample): `https://books.toscrape.com/robots.txt`

#### F-005 — No usable sitemap was found (MEDIUM)

**What we observed.** No sitemap could be read. Locations tried: https://books.toscrape.com/sitemap.xml (status 404), https://books.toscrape.com/sitemap_index.xml (status 404), https://books.toscrape.com/sitemap-index.xml (status 404). Discovery fell back to following links, which found 412 URLs. This is a crawl-efficiency problem rather than a block: pages linked from the site are still reachable.

**Why it matters.** A sitemap does not unblock anything; it tells a crawler which URLs exist and which have changed, so pages that are weakly linked internally get discovered and changed pages get recrawled sooner.

**What to do.** Publish a sitemap with accurate lastmod values and declare it in robots.txt.

- Generate a sitemap from the publishing pipeline so lastmod reflects the real content change date rather than the build clock.
- Segment it by template (products, articles, static pages) so a crawler can recrawl the fast-changing parts without refetching the rest.
- Add a `Sitemap:` line to robots.txt pointing at the index.

Priority: high. Effort: config. Owner: engineering. Check it worked: Fetch the sitemap URL and confirm it returns 200, parses, and lists the canonical URL of every template.

Affected pages (sample): `https://books.toscrape.com/sitemap-index.xml`, `https://books.toscrape.com/sitemap.xml`, `https://books.toscrape.com/sitemap_index.xml`

### Can a machine read it

#### F-006 — Content appears to exist only after JavaScript runs (MEDIUM)

**What we observed.** 4 pages show the structural signature of a client-rendered shell in the raw HTML: https://books.toscrape.com/catalogue/category/books/academic_40/index.html (empty-or-thin-main-content/high, external-bundle-with-no-text/medium). No headless browser was available in this run to confirm directly by comparison, so this is inferred from structure rather than measured against a render.

**Why it matters.** The same mechanism as a confirmed shell: crawlers that do not execute JavaScript receive only what is in the raw response. This is flagged at reduced confidence because it was inferred from structure, not measured directly.

**What to do.** Confirm with a real browser render comparison, then server-render or pre-render the core content if confirmed.

- Run this audit with a headless browser available, or manually compare `curl` output against a browser's view-source for these URLs.
- If confirmed, enable server-side rendering or static pre-rendering for the template.
- Keep interactive enhancement client-side.

Priority: low. Effort: platform-change. Owner: engineering. Check it worked: Re-run with a browser available and confirm the raw versus rendered comparison.

Affected pages (sample): `https://books.toscrape.com/catalogue/category/books/academic_40/index.html`, `https://books.toscrape.com/catalogue/category/books/crime_51/index.html`, `https://books.toscrape.com/catalogue/category/books/cultural_49/index.html`, `https://books.toscrape.com/catalogue/category/books/erotica_50/index.html`

#### F-009 — Heading levels skip, breaking the outline (LOW)

**What we observed.** 17 pages with 4 or more headings have at least one level jump of more than one step, for example h2 directly to h4. Example: https://books.toscrape.com/.

**Why it matters.** A skipped level breaks the outline a machine would otherwise use to navigate straight to the section that answers a question.

**What to do.** Fill in the skipped heading levels so the outline descends one step at a time.

- Replace a jump such as h2 to h4 with h2 to h3 to h4, or demote the deeper heading if no intermediate section exists.

Priority: low. Effort: template-change. Owner: content. Check it worked: List the heading levels on the page and confirm no step exceeds one.

Affected pages (sample): `https://books.toscrape.com/`, `https://books.toscrape.com/catalogue/category/books/add-a-comment_18/index.html`, `https://books.toscrape.com/catalogue/category/books/art_25/index.html`, `https://books.toscrape.com/catalogue/category/books/autobiography_27/index.html`, `https://books.toscrape.com/catalogue/category/books/biography_36/index.html`

### Can a machine tell what it is

#### F-001 — The homepage declares no organization or local-business entity (HIGH)

**What we observed.** The homepage (https://books.toscrape.com/) has no Organization, LocalBusiness or equivalent entity in its JSON-LD, Microdata or RDFa, after traversing any @graph fully. There is no explicit machine-readable statement of which brand this site belongs to.

**Why it matters.** This is the single node a system uses to resolve 'this site' into 'this real-world brand'. Without it, every other page's content is attributed to an inferred entity rather than a declared one.

**What to do.** Add one Organization (or LocalBusiness, if there is a physical location) node to the homepage, in JSON-LD, with a stable identifier.

- Include at minimum name, url, and logo.
- Give it an @id so other structured data on the site can reference it rather than duplicating it.
- Add sameAs links to profiles the brand actually controls.

Priority: high. Effort: template-change. Owner: engineering. Check it worked: Fetch the homepage and confirm an Organization node with a name and url parses successfully.

Affected pages (sample): `https://books.toscrape.com/`

#### F-002 — No structured data of any kind was found on the sampled pages (HIGH)

**What we observed.** None of the 21 sampled content pages carry JSON-LD, Microdata or RDFa. A machine can read the text but has no explicit signal for what kind of thing each page describes or which entity it belongs to.

**Why it matters.** Structured data lets a machine classify content and resolve which real-world entity a page is about, without inferring it from prose. Its absence does not block reading the page, but it leaves classification to inference, which is less reliable.

**What to do.** Add structured data for at least the organisation identity and the page types this site actually has, in JSON-LD.

- Start with an Organization node on the homepage.
- Add the type each template warrants: Product for product pages, Article for editorial content, and so on.
- JSON-LD in a single script block in the page head is the easiest to maintain and validate.

Priority: high. Effort: template-change. Owner: engineering. Check it worked: Run the page through a structured-data validator and confirm at least one recognised type is detected.

Affected pages (sample): `https://books.toscrape.com/`, `https://books.toscrape.com/catalogue/1000-places-to-see-before-you-die_1/index.html`, `https://books.toscrape.com/catalogue/category/books/add-a-comment_18/index.html`, `https://books.toscrape.com/catalogue/category/books/art_25/index.html`, `https://books.toscrape.com/catalogue/category/books/autobiography_27/index.html`

#### F-010 — Pages below the homepage carry no breadcrumb markup (LOW)

**What we observed.** 20 of 20 sampled non-homepage pages have no BreadcrumbList markup. Examples: https://books.toscrape.com/catalogue/1000-places-to-see-before-you-die_1/index.html, https://books.toscrape.com/catalogue/category/books/add-a-comment_18/index.html, https://books.toscrape.com/catalogue/category/books/art_25/index.html.

**Why it matters.** Breadcrumb markup gives a machine an explicit statement of where a page sits in the site's structure, which is otherwise only inferable from the URL path.

**What to do.** Add BreadcrumbList markup reflecting each page's position in the site hierarchy.

- Generate it from the same navigation hierarchy the template already renders as a visible breadcrumb, if one exists.
- Each ListItem needs position, name and item (the URL).

Priority: low. Effort: template-change. Owner: engineering. Check it worked: Re-check the page and confirm BreadcrumbList markup parses and matches the page's actual position.

Affected pages (sample): `https://books.toscrape.com/catalogue/1000-places-to-see-before-you-die_1/index.html`, `https://books.toscrape.com/catalogue/category/books/add-a-comment_18/index.html`, `https://books.toscrape.com/catalogue/category/books/art_25/index.html`, `https://books.toscrape.com/catalogue/category/books/autobiography_27/index.html`, `https://books.toscrape.com/catalogue/category/books/biography_36/index.html`

### Does the right version win

#### F-007 — The copyright year lags the site's own newest content by more than a year (MEDIUM)

**What we observed.** 1 pages show a copyright year of 2003, while the newest date signal observed anywhere in the sample is 2023 -- a gap of 20 years. Example: https://books.toscrape.com/catalogue/1000-places-to-see-before-you-die_1/index.html.

**Why it matters.** A lagging copyright year is a weak but real signal a system may use when judging how actively a site is maintained, independent of whether the content itself is still accurate.

**What to do.** Update the copyright year, ideally driven automatically from the current date rather than a hand-maintained value.

- Generate the footer copyright year from the server's own clock at render time, so it never needs manual updating.

Priority: medium. Effort: trivial. Owner: engineering. Check it worked: Re-check the footer and confirm the year matches or exceeds the site's own newest content date.

Affected pages (sample): `https://books.toscrape.com/catalogue/1000-places-to-see-before-you-die_1/index.html`

### Does the visitor who arrives stay

#### F-008 — Sampled pages have no inbound link from any other sampled page (MEDIUM)

**What we observed.** 1 sampled pages are not linked to by any other page in this sample -- orphan-like within the sampled graph. This does not establish that the page is globally unreachable, only that no other page this audit observed points to it. Examples: https://books.toscrape.com/catalogue/1000-places-to-see-before-you-die_1/index.html.

**Why it matters.** A page with no inbound link from anything else this audit sampled is reachable only through a sitemap or direct URL knowledge, which is a weaker discovery and continuation path than an in-content link from a related page.

**What to do.** Link to these pages from at least one other relevant page in the site's own content or navigation.

- Identify a relevant category, hub or related-content page for each listed URL.
- Add a direct link to it from there.

Priority: low. Effort: content. Owner: content. Check it worked: Re-check the site's sampled link graph and confirm at least one other page now links to this URL.

Affected pages (sample): `https://books.toscrape.com/catalogue/1000-places-to-see-before-you-die_1/index.html`

## Worth doing anyway

These are not defects. They are improvements that would strengthen how this brand is found, cited and experienced.

- **Establish one canonical entity/fact source and propagate it** — Decide which value is current and correct. *(template-change effort, mixed; A fact contradicted across the site's own pages, alongside structured data that does not agree with itself either, means there is no single version of this fact a machine could trust even if it wanted to.)*
- **Treat access and render problems on the same template as one compound gate** — Confirm both issues affect the same template cluster, not merely the same site. *(template-change effort, mixed; A page an agent cannot reach and a page it can reach but cannot read are two different symptoms of the same outcome: the content never reaches an answer. Fixing access without fixing render, or the reverse, still leaves the gate shut.)*
- **Deferred: Actual AI referral traffic and citation frequency** — Run a fixed panel of prompts across assistants in clean sessions, repeated, and record the rate at which the brand is named and cited. *(platform-change effort, mixed; Without this data, the audit can recommend but cannot confirm outcome, only mechanism.)*
- **Deferred: Actual behavioural engagement (click-through, conversion, bounce, time on page)** — Track conversion or engagement from answer-bearing pages to the relevant action, segmented by referrer, after implementing any recommended action pathway. *(platform-change effort, mixed; Without this data, the audit can recommend but cannot confirm outcome, only mechanism.)*
- **Deferred: External/off-site corroboration of key facts** — Periodically check whether independent sources still state a superseded value for each canonical fact. *(platform-change effort, mixed; Without this data, the audit can recommend but cannot confirm outcome, only mechanism.)*

## How you will know it worked

- **Whether the brand is named, and cited, in assistant answers to category, brand-direct, comparison and long-tail questions** (monthly): A fixed panel of 30 to 50 prompts, run across several assistants in clean sessions, several repeats each; record the rate the brand is named and cited, not a single outcome
- **Whether the agents that matter are actually reaching the site** (weekly): Server-log monitoring of crawler activity (request counts, status codes and paths per agent), verified against each operator's published address ranges rather than the user-agent header alone
- **Whether the current version of each canonical fact is the one that exists in the world** (monthly): For each canonical fact, check independent sources state the current value; alert when a superseded version resurfaces
- **Whether the fixes from this audit held** (monthly): Re-run this audit on a schedule and diff the reports by check_id: resolved, new, regressed
- **Whether representative high-value pages continue to expose an observable next step** (monthly): Re-run the engagement check on a schedule against the same sampled page set and diff by check_id

Assistants personalise: two people asking the same question can get different brands and framing. A single prompt on a single day is not a measurement. Run clean sessions, repeat each prompt, and report rates with the sample size attached. The report carries a stable check_id on every finding precisely so consecutive audits can be diffed; the sequential id shifts as findings are added or resolved, check_id does not.

## What we did not assess

Pages discovered: 412. Sampled: 25. Fetched: 25. Rendered in a browser: 0.

- **inbound parameter preservation** — no sampled URL redirected, so there was nothing to probe
- **browser render comparison** — a headless browser is installed but would not start: BrowserType.launch: Executable doesn't exist at C:\Users\patha\AppData\Local\ms-playwright\chromium_headless_shell-1234\chrome-headless-shell-win64\chrome-headless-shell.exe
╔═════════════════════════
- **off-site corroboration** — no external search capability was made available to this run
- **content behind interaction** — this marketplace's collector never clicks, submits or interacts with a page by design, so content that only appears after a tab, accordion or similar interaction cannot be distinguished from content that was never going to appear at all. This is a permanent architectural limit, not a capability that a browser being available would remove.

A dimension listed here was **not** checked. It is not a pass.

---

*Technical measures such as structured data and server-side rendering improve whether a machine can reach, read, understand and quote this brand. They raise eligibility; no technique guarantees that an assistant will cite you.*
