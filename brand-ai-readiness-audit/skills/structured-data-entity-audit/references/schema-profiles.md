# Type profiles and page-type gating

A type is only expected on a page type that warrants it, and only when
`page_type_confidence` is `high` or `medium`. When confidence is `low`, run type-agnostic
checks only.

| Page type | Expected type | Required properties | Recommended |
| --- | --- | --- | --- |
| `homepage` | `Organization` or `LocalBusiness`, plus `WebSite` | `name`, `url` | `logo`, `description`, `sameAs`, `foundingDate`, `address` |
| `product` | `Product` with an `Offer` | `name`, `offers.price`, `offers.priceCurrency`, `offers.availability` | `sku` or `mpn`, `brand`, `image`, `description` |
| `article` | `Article` or `BlogPosting` | `headline`, `datePublished` | `author`, `dateModified`, `publisher` |
| `category` | `ItemList` or `CollectionPage` | `itemListElement` | `name` |
| any non-homepage | `BreadcrumbList` | `itemListElement` with `position` and `name` | — |
| a page with genuine question-and-answer content | `FAQPage` | `mainEntity` with `Question` and `acceptedAnswer` | — |
| `contact` | `ContactPoint` or `PostalAddress` | `telephone` or `address` | `areaServed` |
| `local-business` archetype homepage | `LocalBusiness` | `address` with `postalCode`, `telephone` | `geo`, `openingHoursSpecification` |

## Gating rules

1. **Never demand `FAQPage` where there is no question-and-answer content.** Detect the
   content first, then check the markup. Recommending FAQ markup for content that does
   not exist is a content recommendation dressed as a technical finding, and marking up
   questions that are not on the page is misrepresentation.
2. **Never demand `Product` outside `product` pages.**
3. **`BreadcrumbList` on the homepage is not expected.**
4. **A missing recommended property is at most `low`.** Only required properties reach
   `medium`.
5. **Legitimately absent types are not findings.** A brochure site with no products is
   complete without `Product`.

## Identity profile

One canonical organization node should exist with:

- a stable identifier so other nodes can reference it rather than duplicating it,
- `name` matching the brand name used in the page title, the homepage h1 and the
  copyright line, after normalising case, punctuation and legal suffixes,
- `url` pointing at the canonical origin,
- `sameAs` listing independent profiles the brand actually controls or is represented on.

The mechanism is entity resolution: linking a site to profiles a system already trusts
makes "probably this company" into "this company". Inconsistent profiles introduce
disambiguation errors instead of resolving them, so consistency across those profiles is
part of the fix, not an optional extra.
