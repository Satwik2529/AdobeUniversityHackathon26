# Fact candidates and normalisation

**Scope note:** only the rows marked *(implemented)* below have a corresponding check in
`check_freshness.py`. The others were part of earlier, broader planning; postal address
and telephone cross-page comparison are `structured-data-entity-audit`'s territory
(`SDE.ORG_IDENTITY_CONFLICT`, matched by a shared `@id`) and are not duplicated here.
Brand/legal name and founding year comparison were not built this milestone. The
normalisation principles below remain accurate design guidance for what is implemented.

Only extract facts with high extraction confidence and low ambiguity. A wrong fact
comparison produces a confident, wrong finding, which is worse than no finding.

| Fact | Sources compared | Status |
| --- | --- | --- |
| Tagline or positioning line | an explicit "tagline is..."/"slogan is..." phrase in page text | *(implemented, English-only)* |
| Price and currency | `Product.offers.price`/`priceCurrency`, matched by `sku` | *(implemented)* |
| Availability | `offers.availability`, JSON-LD or Microdata | *(implemented, presence-only)* |
| Last-modified signals | structured `dateModified`, response header, sitemap entry | *(implemented)* |
| Brand or legal name | organization node name, site name, title suffix, copyright line | not implemented this milestone |
| Postal address | postal-address markup, contact page, footer | owned by `SDE.ORG_IDENTITY_CONFLICT` |
| Telephone | contact-point markup, contact page, footer | owned by `SDE.ORG_IDENTITY_CONFLICT` |
| Founding year | organization founding date, about-page year | not implemented this milestone |
| Product name and model identifier | product name, sku or mpn, page h1 | not implemented this milestone |

## Normalisation, applied before every comparison

- **Text**: unicode normalise, collapse whitespace, strip zero-width characters,
  case-fold, strip surrounding punctuation and quotation marks.
- **Names**: additionally strip common legal suffixes and trailing separators. Two names
  that differ only by a legal suffix are the same name.
- **Currency**: separate the amount from the symbol or code, strip digit-group separators,
  normalise the decimal mark, compare amount and currency independently. Different
  currencies are not a contradiction; the same currency with different amounts is.
- **Phone**: strip all non-digits, compare the longest common suffix of at least 8 digits
  so that country-code prefixes do not create false contradictions.
- **Address**: compare the postal code and the street-number token, not the whole string.
- **Dates**: parse to a date; on ambiguity between day-first and month-first orders,
  **skip the comparison** rather than guessing.

## Comparison rules

1. A fact appearing once is not a conflict. A conflict needs two pages with two values.
2. Skip any pair where either side failed to normalise.
3. A price differing between a product page and a category listing is a genuine conflict
   worth reporting; a price differing between a product page and a blog post from three
   years ago is not, so gate price comparisons on page types that are supposed to be
   authoritative for that fact.
4. Record both URLs and both raw values in the evidence. The reader must be able to open
   the two pages and see it.
