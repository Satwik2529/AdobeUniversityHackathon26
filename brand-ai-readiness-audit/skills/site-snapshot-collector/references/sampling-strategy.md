# Deterministic sampling, clustering and classification

Random or first-N sampling defeats generalisation: the first 25 sitemap URLs of a media
site are 25 near-identical articles, and the product, about and contact templates are
never tested. Sampling is therefore template-aware and reproducible.

## 1. URL normalisation
Lowercase the host, drop the default port, drop the fragment, strip tracking parameters
(`utm_*`, `gclid`, `fbclid`, `msclkid`, `ref`, `mc_cid`, session-id style keys), collapse
duplicate slashes, resolve `.` and `..`, and pick one trailing-slash form per host based
on which form the site's own canonical tags use. Keep the pre-normalisation URL alongside,
because a redirect chain is evidence.

## 2. Path skeletons
Replace variable segments to get a template key:

| Segment looks like | Replaced with |
| --- | --- |
| all digits | `{n}` |
| UUID or long hex | `{id}` |
| contains a hyphen and is longer than 12 characters | `{slug}` |
| date-shaped (`2026`, `2026-09`) | `{date}` |

`/products/velocity-x9` becomes `/products/{slug}`. `/blog/2026/09/a-long-title` becomes
`/blog/{date}/{n}/{slug}`.

## 3. Second clustering pass: sibling leaves
Skeletons alone under-cluster. `/products/alpha` and `/products/beta` are one template to
any human reader, but neither segment looks like a slug by shape. The structural signal is
co-occurrence: several leaf pages sharing a parent directory are one template. Guards keep
it from over-merging - only below the root, only leaves sharing a file extension, never
when a leaf name is a known section word, and at least two members. So
`/products/alpha.html` and `/products/beta.html` merge; `/about.html` and `/contact.html`
do not, and neither do `/docs/api` and `/docs/guide`.

## 4. Cluster ranking
Ordered by, in priority: linked from the primary navigation, then not faceted, then
population, then shallowness, then the skeleton itself as a deterministic tie-break.

Navigation-linked clusters rank up deliberately. About, contact and press pages are tiny
clusters that carry most of a brand's canonical facts, and a purely size-ranked sample
would never look at them.

Faceted and filtered URLs rank down. They stay eligible, because some sites publish them
deliberately, but they are variants of content that already exists elsewhere.

## 5. Sampling, in two passes
**Pass one, fairness.** The homepage always. Then up to `per_cluster_cap` (3) URLs from
each cluster, breadth-first in rank order, so a 200-page catalogue cannot crowd out the
about page.

**Pass two, fill.** `per_cluster_cap` is a fairness floor, not a ceiling on the sample.
Once every template is represented, the remaining budget is spent round-robin in rank
order. A template claim like "0 of 14 product pages carry markup" is far stronger evidence
than the same claim over 3 pages, and the request budget is already paid for.

Faceted clusters are excluded from pass two and stay at the fairness floor: three variants
are enough to characterise them, and sampling more would also manufacture spurious
duplicate-content findings.

Within a cluster, members are chosen in sorted order, so a rerun over an unchanged site
picks exactly the same pages.

## 6. Page-type classification
A weighted vote over observed signals only. Never a domain list, never a hard-coded
selector.

| Type | Signals |
| --- | --- |
| `homepage` | normalised path is `/` |
| `product` | `Product` or `Offer` structured data; price-shaped text plus a purchase control; skeleton under a repeated commerce path |
| `category` | many links to a single sibling cluster; `ItemList` structured data |
| `article` | `Article`/`BlogPosting`; byline plus a date; skeleton under a dated path |
| `docs` | deep heading hierarchy plus in-page anchor navigation |
| `about`/`contact`/`press`/`legal` | `AboutPage`, `ContactPage`, `PostalAddress`, `ContactPoint`, or a nav link whose target is one of these clusters |
| `utility` | search, cart, account, checkout, login, filter or parameter-only URLs |
| `unknown` | no signal reaches the confidence floor |

Record `page_type_confidence`. When it is `low`, only type-agnostic checks run against
that page. Guessing a page type is how a detector ends up demanding `Product` markup from
a blog post.

## 7. Site archetype
Derived from the page-type distribution, not from the domain. `mixed` and `unknown` are
first-class outcomes and simply narrow the check set.

## 8. Determinism guarantee
Given the same site state, the sample, the cluster ids and their ordering are identical
across runs. Cluster ids are assigned after sorting skeletons lexicographically, never in
discovery order.
