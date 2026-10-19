#!/usr/bin/env python3
"""Generate the local fixture sites used to measure detection precision and recall.

Design principle: **one clean base site, then single-variable mutations.**

Every fixture is the same site with exactly one thing changed. That makes attribution
clean — if a detector fires on F04 it is because of the price contradiction, not because
F04 happens to differ from F00 in five ways. It also means the negative controls (F00,
F03, F08, F09, F10, F11) are structurally identical to the positives, so a detector
cannot "pass" them by accident.

The brand and content here are invented placeholders. Nothing in the detectors may
reference them: fixtures test generalisable properties of HTML and HTTP, not this site.

Usage: python3 tests/make_fixtures.py [--out tests/fixtures]
"""
import argparse
import json
import os
import re
import shutil

BRAND = "Larkspur Instruments"
ORIGIN = "http://localhost:8099"

# --------------------------------------------------------------------------------------
# Base site (F00, the clean control)
# --------------------------------------------------------------------------------------

HEAD = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{origin}{path}">
{extra_head}
</head>
<body>
<header>
<a href="/">{brand}</a>
<nav aria-label="Main">
<a href="/products/">{nav_products}</a>
<a href="/about.html">{nav_about}</a>
<a href="/faq.html">{nav_faq}</a>
<a href="/contact.html">{nav_contact}</a>
</nav>
<form action="/search.html" role="search"><label for="q">{search_label}</label>
<input id="q" name="q" type="search"></form>
</header>
<main>
"""

FOOT = """</main>
<footer>
<p>{copyright}</p>
<p>{brand}, 42 Kiln Road, Fairhaven FH2 9QT. Telephone +44 20 7946 0810.</p>
</footer>
</body>
</html>
"""

ORG_JSONLD = {
    "@context": "https://schema.org",
    "@graph": [
        {
            "@type": "Organization",
            "@id": ORIGIN + "/#organization",
            "name": BRAND,
            "url": ORIGIN + "/",
            "description": "Precision measuring instruments made in Fairhaven since 1994.",
            "slogan": "Measure once.",
            "foundingDate": "1994",
            "telephone": "+44 20 7946 0810",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "42 Kiln Road",
                "addressLocality": "Fairhaven",
                "postalCode": "FH2 9QT",
            },
            "sameAs": [
                "https://example.org/profiles/larkspur",
                "https://example.net/companies/larkspur-instruments",
            ],
        },
        {
            "@type": "WebSite",
            "@id": ORIGIN + "/#website",
            "url": ORIGIN + "/",
            "name": BRAND,
            "publisher": {"@id": ORIGIN + "/#organization"},
        },
    ],
}


def jsonld(payload):
    return ('<script type="application/ld+json">%s</script>'
            % json.dumps(payload, indent=None, sort_keys=True))


def breadcrumb(items):
    return jsonld({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": name, "item": ORIGIN + url}
            for i, (name, url) in enumerate(items)
        ],
    })


def product_jsonld(name, sku, price, availability="https://schema.org/InStock"):
    return jsonld({
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "sku": sku,
        "brand": {"@type": "Brand", "name": BRAND},
        "description": "%s precision instrument from %s." % (name, BRAND),
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": "GBP",
            "availability": availability,
            "url": ORIGIN + "/products/%s.html" % sku.lower(),
        },
    })


def page(path, title, description, body, lang="en", extra_head="", labels=None):
    labels = labels or {}
    head = HEAD.format(
        lang=lang, title=title, description=description, origin=ORIGIN, path=path,
        brand=labels.get("brand", BRAND), extra_head=extra_head,
        nav_products=labels.get("products", "Products"),
        nav_about=labels.get("about", "About"),
        nav_faq=labels.get("faq", "FAQ"),
        nav_contact=labels.get("contact", "Contact"),
        search_label=labels.get("search", "Search this site"),
    )
    foot = FOOT.format(brand=labels.get("brand", BRAND),
                       copyright=labels.get("copyright", "Copyright 2026 " + BRAND))
    return head + body + foot


PRODUCT_BODY = """{breadcrumb}
{jsonld}
<article>
<h1 id="top">{name}</h1>
<p>The {name} is a handheld precision caliper from {brand}. It costs
{price_text} and is in stock, shipping within two working days.</p>
<h2 id="specifications">Specifications</h2>
<table>
<tr><th>Measuring range</th><td>0 to 150 millimetres</td></tr>
<tr><th>Resolution</th><td>0.01 millimetres</td></tr>
<tr><th>Mass</th><td>240 grams</td></tr>
<tr><th>Price</th><td>{price_text}</td></tr>
</table>
<h2 id="in-the-box">In the box</h2>
<p>The {name}, a fitted case, and a calibration certificate.</p>
<p>See also the <a href="/products/">full range</a> and our
<a href="/faq.html">frequently asked questions</a>.</p>
<img src="/hairline.png" alt="">
</article>
"""


def build_base():
    """Return {relative_path: file_contents} for the clean control site."""
    files = {}

    files["index.html"] = page(
        "/", "%s: precision measuring instruments" % BRAND,
        "Precision measuring instruments made in Fairhaven since 1994.",
        jsonld(ORG_JSONLD) + """
<h1>%s</h1>
<p>%s makes precision measuring instruments in Fairhaven. Founded in 1994, our
tagline is Measure once. Browse the <a href="/products/">product range</a>, read
<a href="/about.html">about the company</a>, or see the
<a href="/faq.html">frequently asked questions</a>.</p>
""" % (BRAND, BRAND))

    files["about.html"] = page(
        "/about.html", "About %s" % BRAND,
        "How %s has made precision instruments since 1994." % BRAND,
        breadcrumb([("Home", "/"), ("About", "/about.html")]) + """
<h1 id="top">About %s</h1>
<p>%s was founded in 1994 in Fairhaven and makes precision measuring instruments.
Our tagline is Measure once. Our address is 42 Kiln Road, Fairhaven FH2 9QT and our
telephone number is +44 20 7946 0810.</p>
<h2 id="facts">Key facts</h2>
<dl>
<dt>Founded</dt><dd>1994</dd>
<dt>Tagline</dt><dd>Measure once.</dd>
<dt>Head office</dt><dd>42 Kiln Road, Fairhaven FH2 9QT</dd>
<dt>Telephone</dt><dd>+44 20 7946 0810</dd>
</dl>
<p>Updated 12 August 2026. See the <a href="/products/">product range</a>.</p>
""" % (BRAND, BRAND))

    files["contact.html"] = page(
        "/contact.html", "Contact %s" % BRAND, "How to reach %s." % BRAND,
        breadcrumb([("Home", "/"), ("Contact", "/contact.html")]) +
        jsonld({"@context": "https://schema.org", "@type": "ContactPage",
                "mainEntity": {"@type": "Organization", "@id": ORIGIN + "/#organization",
                               "telephone": "+44 20 7946 0810",
                               "address": {"@type": "PostalAddress",
                                           "streetAddress": "42 Kiln Road",
                                           "addressLocality": "Fairhaven",
                                           "postalCode": "FH2 9QT"}}}) + """
<h1 id="top">Contact %s</h1>
<p>Telephone +44 20 7946 0810. Our address is 42 Kiln Road, Fairhaven FH2 9QT.
We answer enquiries within one working day.</p>
""" % BRAND)

    files["faq.html"] = page(
        "/faq.html", "Frequently asked questions", "Common questions about %s." % BRAND,
        breadcrumb([("Home", "/"), ("FAQ", "/faq.html")]) +
        jsonld({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": "How long is the warranty?",
             "acceptedAnswer": {"@type": "Answer",
                                "text": "Every %s instrument carries a three year "
                                        "warranty from the date of purchase." % BRAND}},
            {"@type": "Question", "name": "Do you ship internationally?",
             "acceptedAnswer": {"@type": "Answer",
                                "text": "Yes. %s ships to 40 countries, with delivery "
                                        "in five to ten working days." % BRAND}}]}) + """
<h1 id="top">Frequently asked questions</h1>
<h2 id="warranty">How long is the warranty?</h2>
<p>Every %s instrument carries a three year warranty from the date of purchase.</p>
<h2 id="shipping">Do you ship internationally?</h2>
<p>Yes. %s ships to 40 countries, with delivery in five to ten working days.</p>
""" % (BRAND, BRAND))

    # Evergreen legal page with a deliberately old date. Legitimate, not a defect.
    files["legal.html"] = page(
        "/legal.html", "Terms of sale", "Terms of sale.",
        breadcrumb([("Home", "/"), ("Terms", "/legal.html")]) + """
<h1 id="top">Terms of sale</h1>
<p>These terms govern purchases from %s. Last reviewed 3 February 2019 and unchanged
since; they are reviewed annually and no change has been required.</p>
""" % BRAND)

    # Utility page, correctly noindexed. A naive auditor flags this; it must not.
    files["search.html"] = page(
        "/search.html", "Search", "Search this site.", """
<h1>Search</h1>
<p>Enter a term to search the site.</p>
""", extra_head='<meta name="robots" content="noindex, follow">')

    files["products/index.html"] = page(
        "/products/index.html", "Products", "The full %s range." % BRAND,
        breadcrumb([("Home", "/"), ("Products", "/products/")]) +
        jsonld({"@context": "https://schema.org", "@type": "ItemList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1,
                     "url": ORIGIN + "/products/alpha.html", "name": "Alpha Caliper"},
                    {"@type": "ListItem", "position": 2,
                     "url": ORIGIN + "/products/beta.html", "name": "Beta Caliper"},
                    {"@type": "ListItem", "position": 3,
                     "url": ORIGIN + "/products/gamma.html", "name": "Gamma Caliper"}]}) + """
<h1 id="top">Products</h1>
<ul>
<li><a href="/products/alpha.html">Alpha Caliper</a>, 59.00 GBP</li>
<li><a href="/products/beta.html">Beta Caliper</a>, 74.00 GBP</li>
<li><a href="/products/gamma.html">Gamma Caliper</a>, 88.00 GBP</li>
</ul>
""")

    for name, sku, price in (("Alpha Caliper", "ALPHA", "59.00"),
                             ("Beta Caliper", "BETA", "74.00"),
                             ("Gamma Caliper", "GAMMA", "88.00")):
        files["products/%s.html" % sku.lower()] = page(
            "/products/%s.html" % sku.lower(), "%s: %s" % (name, BRAND),
            "The %s from %s." % (name, BRAND),
            PRODUCT_BODY.format(
                breadcrumb=breadcrumb([("Home", "/"), ("Products", "/products/"),
                                       (name, "/products/%s.html" % sku.lower())]),
                jsonld=product_jsonld(name, sku, price),
                name=name, brand=BRAND, price_text="%s GBP" % price))

    files["robots.txt"] = (
        "User-agent: *\n"
        "Disallow: /search.html\n"
        "Allow: /\n"
        "\n"
        "Sitemap: %s/sitemap.xml\n" % ORIGIN)

    urls = ["/", "/about.html", "/contact.html", "/faq.html", "/legal.html",
            "/products/", "/products/alpha.html", "/products/beta.html",
            "/products/gamma.html"]
    lastmods = ["2026-08-12", "2026-08-12", "2026-07-30", "2026-08-01", "2019-02-03",
                "2026-08-14", "2026-08-14", "2026-08-09", "2026-08-11"]
    files["sitemap.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join("<url><loc>%s%s</loc><lastmod>%s</lastmod></url>\n" % (ORIGIN, u, m)
                  for u, m in zip(urls, lastmods))
        + "</urlset>\n")

    files["_rules.json"] = json.dumps({"description": "no server-side behaviour"}, indent=2)
    return files


# --------------------------------------------------------------------------------------
# Mutations. Each takes the base file map and changes exactly one thing.
# --------------------------------------------------------------------------------------

def m_csr_shell(files):
    """Product pages become an empty client-rendered shell."""
    for sku in ("alpha", "beta", "gamma"):
        path = "products/%s.html" % sku
        files[path] = page(
            "/products/%s.html" % sku, "%s Caliper" % sku.title(), "Loading.",
            '<div id="app"></div>\n'
            '<noscript>You need to enable JavaScript to view this site.</noscript>\n'
            '<script src="/bundle.js"></script>\n')
    files["bundle.js"] = "/* %s */\n" % ("x" * 40000)
    return files


def m_robots_blocks_retrieval(files):
    files["robots.txt"] = (
        "User-agent: *\nAllow: /\n\n"
        "User-agent: OAI-SearchBot\nDisallow: /\n\n"
        "User-agent: Claude-SearchBot\nDisallow: /\n\n"
        "User-agent: PerplexityBot\nDisallow: /\n\n"
        "User-agent: Googlebot\nDisallow: /\n\n"
        "Sitemap: %s/sitemap.xml\n" % ORIGIN)
    return files


def m_robots_blocks_training_only(files):
    """A deliberate, coherent policy. Must produce info only, never a defect."""
    files["robots.txt"] = (
        "User-agent: *\nDisallow: /search.html\nAllow: /\n\n"
        "User-agent: GPTBot\nDisallow: /\n\n"
        "User-agent: ClaudeBot\nDisallow: /\n\n"
        "User-agent: Google-Extended\nDisallow: /\n\n"
        "User-agent: CCBot\nDisallow: /\n\n"
        "User-agent: OAI-SearchBot\nAllow: /\n\n"
        "User-agent: Claude-SearchBot\nAllow: /\n\n"
        "User-agent: PerplexityBot\nAllow: /\n\n"
        "Sitemap: %s/sitemap.xml\n" % ORIGIN)
    return files


def m_schema_visible_mismatch(files):
    """Structured price contradicts the visible price on the same page."""
    files["products/alpha.html"] = files["products/alpha.html"].replace(
        '"price": "59.00"', '"price": "49.00"')
    return files


def m_deeplink_redirect(files):
    files["_rules.json"] = json.dumps({
        "description": "published product deep links bounce to the homepage, discarding the query",
        "redirects": {
            "/products/alpha.html": {"to": "/", "code": 302},
            "/products/beta.html": {"to": "/", "code": 302},
            "/products/gamma.html": {"to": "/", "code": 302},
        },
        "drop_query": True,
    }, indent=2)
    return files


def m_facts_in_images(files):
    """The specification table becomes an image, and the detail moves into a PDF."""
    for sku in ("alpha", "beta", "gamma"):
        path = "products/%s.html" % sku
        files[path] = files[path].replace(
            files[path][files[path].index("<table>"):files[path].index("</table>") + 8],
            '<img src="/specs-%s.png" alt="">\n'
            '<p><a href="/specs-%s.pdf">Full specification (PDF)</a></p>' % (sku, sku))
        files[path] = files[path].replace(
            "It costs\n59.00 GBP and is in stock, shipping within two working days.", "")
    for sku in ("alpha", "beta", "gamma"):
        files["specs-%s.pdf" % sku] = "%PDF-1.4 stub\n"
    return files


def m_stale_conflict(files):
    """Same facts, different values across the site's own pages."""
    files["about.html"] = files["about.html"].replace(
        "Our tagline is Measure once.", "Our tagline is Measure twice.")
    files["about.html"] = files["about.html"].replace(
        "<dt>Tagline</dt><dd>Measure once.</dd>", "<dt>Tagline</dt><dd>Measure twice.</dd>")
    files["about.html"] = files["about.html"].replace(
        "founded in 1994", "founded in 1991")
    files["products/index.html"] = files["products/index.html"].replace(
        "59.00 GBP", "52.00 GBP")
    files["contact.html"] = files["contact.html"].replace(
        "+44 20 7946 0810", "+44 20 7946 0999")
    files["sitemap.xml"] = files["sitemap.xml"].replace(
        files["sitemap.xml"], files["sitemap.xml"])
    import re as _re
    files["sitemap.xml"] = _re.sub(r"<lastmod>[^<]+</lastmod>",
                                   "<lastmod>2026-01-01</lastmod>", files["sitemap.xml"])
    files["index.html"] = files["index.html"].replace(
        "Copyright 2026", "Copyright 2019")
    return files


def m_non_english(files):
    """A valid, well-built site that simply is not in English."""
    labels = {"brand": "Instruments Larkspur", "products": "Produits", "about": "A propos",
              "faq": "Questions", "contact": "Contact", "search": "Rechercher sur le site",
              "copyright": "Copyright 2026 Instruments Larkspur"}
    out = {k: v for k, v in files.items() if k in ("robots.txt", "sitemap.xml", "_rules.json")}
    out["index.html"] = page(
        "/", "Instruments Larkspur: instruments de mesure de precision",
        "Instruments de mesure de precision fabriques a Fairhaven depuis 1994.",
        jsonld(ORG_JSONLD) + """
<h1>Instruments Larkspur</h1>
<p>Instruments Larkspur fabrique des instruments de mesure de precision a Fairhaven.
Fondee en 1994, notre devise est Mesurer une fois. Consultez la
<a href="/products/">gamme de produits</a>, lisez la page
<a href="/about.html">a propos</a>, ou les <a href="/faq.html">questions frequentes</a>.</p>
""", lang="fr", labels=labels)
    out["about.html"] = page(
        "/about.html", "A propos d'Instruments Larkspur",
        "L'histoire d'Instruments Larkspur depuis 1994.",
        breadcrumb([("Accueil", "/"), ("A propos", "/about.html")]) + """
<h1 id="top">A propos d'Instruments Larkspur</h1>
<p>Instruments Larkspur a ete fondee en 1994 a Fairhaven. Notre devise est Mesurer une
fois. Notre adresse est 42 Kiln Road, Fairhaven FH2 9QT et notre numero de telephone
est +44 20 7946 0810.</p>
<h2 id="faits">Faits essentiels</h2>
<dl><dt>Fondation</dt><dd>1994</dd><dt>Devise</dt><dd>Mesurer une fois.</dd></dl>
""", lang="fr", labels=labels)
    out["contact.html"] = page(
        "/contact.html", "Contacter Instruments Larkspur", "Nous joindre.",
        breadcrumb([("Accueil", "/"), ("Contact", "/contact.html")]) + """
<h1 id="top">Contacter Instruments Larkspur</h1>
<p>Telephone +44 20 7946 0810. Adresse 42 Kiln Road, Fairhaven FH2 9QT.</p>
""", lang="fr", labels=labels)
    out["faq.html"] = page(
        "/faq.html", "Questions frequentes", "Questions courantes.",
        breadcrumb([("Accueil", "/"), ("Questions", "/faq.html")]) + """
<h1 id="top">Questions frequentes</h1>
<h2 id="garantie">Quelle est la duree de la garantie?</h2>
<p>Chaque instrument Larkspur est garanti trois ans a compter de la date d'achat.</p>
""", lang="fr", labels=labels)
    out["products/index.html"] = page(
        "/products/index.html", "Produits", "La gamme complete.",
        breadcrumb([("Accueil", "/"), ("Produits", "/products/")]) + """
<h1 id="top">Produits</h1>
<ul><li><a href="/products/alpha.html">Pied a coulisse Alpha</a>, 59,00 GBP</li></ul>
""", lang="fr", labels=labels)
    out["products/alpha.html"] = page(
        "/products/alpha.html", "Pied a coulisse Alpha: Instruments Larkspur",
        "Le pied a coulisse Alpha.",
        breadcrumb([("Accueil", "/"), ("Produits", "/products/"),
                    ("Alpha", "/products/alpha.html")]) +
        product_jsonld("Pied a coulisse Alpha", "ALPHA", "59.00") + """
<h1 id="top">Pied a coulisse Alpha</h1>
<p>Le pied a coulisse Alpha d'Instruments Larkspur coute 59,00 GBP et est en stock.</p>
<h2 id="specifications">Caracteristiques</h2>
<table><tr><th>Plage de mesure</th><td>0 a 150 millimetres</td></tr>
<tr><th>Resolution</th><td>0,01 millimetre</td></tr>
<tr><th>Masse</th><td>240 grammes</td></tr></table>
<p>Voir aussi la <a href="/products/">gamme complete</a>.</p>
""", lang="fr", labels=labels)
    out["sitemap.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join('<url><loc>%s%s</loc><lastmod>2026-08-1%d</lastmod></url>\n'
                  % (ORIGIN, u, i)
                  for i, u in enumerate(["/", "/about.html", "/contact.html", "/faq.html",
                                         "/products/", "/products/alpha.html"]))
        + "</urlset>\n")
    return out


def m_small_site(files):
    """Two pages, correctly built. Template-level checks must disable themselves."""
    out = {k: v for k, v in files.items() if k in ("robots.txt", "_rules.json")}
    labels = {"products": "Home", "about": "Home", "faq": "Contact", "contact": "Contact"}
    out["index.html"] = page(
        "/", "%s: precision measuring instruments" % BRAND,
        "Precision measuring instruments made in Fairhaven since 1994.",
        jsonld(ORG_JSONLD) + """
<h1>%s</h1>
<p>%s makes precision measuring instruments in Fairhaven. Founded in 1994, our tagline
is Measure once. Our address is 42 Kiln Road, Fairhaven FH2 9QT. To reach us, see the
<a href="/contact.html">contact page</a>.</p>
""" % (BRAND, BRAND))
    out["contact.html"] = page(
        "/contact.html", "Contact %s" % BRAND, "How to reach %s." % BRAND,
        breadcrumb([("Home", "/"), ("Contact", "/contact.html")]) + """
<h1 id="top">Contact %s</h1>
<p>Telephone +44 20 7946 0810. Our address is 42 Kiln Road, Fairhaven FH2 9QT.
Return to the <a href="/">home page</a>.</p>
""" % BRAND)
    for name in ("index.html", "contact.html"):
        out[name] = out[name].replace(
            '<a href="/products/">Products</a>', '<a href="/">Home</a>').replace(
            '<a href="/about.html">About</a>', "").replace(
            '<a href="/faq.html">FAQ</a>', "")
    del labels
    out["robots.txt"] = ("User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n"
                         % ORIGIN)
    out["sitemap.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '<url><loc>%s/</loc><lastmod>2026-08-12</lastmod></url>\n'
        '<url><loc>%s/contact.html</loc><lastmod>2026-07-30</lastmod></url>\n'
        '</urlset>\n' % (ORIGIN, ORIGIN))
    return out


def m_microdata_only(files):
    """Valid Microdata, no JSON-LD. Not a defect."""
    import re as _re
    for path in list(files):
        if path.endswith(".html"):
            files[path] = _re.sub(
                r'<script type="application/ld\+json">.*?</script>', "", files[path],
                flags=_re.S)
    files["index.html"] = files["index.html"].replace(
        "<h1>%s</h1>" % BRAND,
        '<div itemscope itemtype="https://schema.org/Organization">'
        '<h1 itemprop="name">%s</h1>'
        '<link itemprop="url" href="%s/">'
        '<meta itemprop="foundingDate" content="1994">' % (BRAND, ORIGIN))
    files["index.html"] = files["index.html"].replace("</main>", "</div></main>")
    files["products/alpha.html"] = files["products/alpha.html"].replace(
        '<h1 id="top">Alpha Caliper</h1>',
        '<div itemscope itemtype="https://schema.org/Product">'
        '<h1 id="top" itemprop="name">Alpha Caliper</h1>'
        '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
        '<meta itemprop="price" content="59.00">'
        '<meta itemprop="priceCurrency" content="GBP">'
        '<link itemprop="availability" href="https://schema.org/InStock"></div>')
    files["products/alpha.html"] = files["products/alpha.html"].replace(
        "</article>", "</div></article>")
    return files


def m_noindex_utility(files):
    """More correctly-noindexed utility pages. Must still produce nothing."""
    for name, title in (("cart", "Basket"), ("account", "Your account"),
                        ("checkout", "Checkout")):
        files["%s.html" % name] = page(
            "/%s.html" % name, title, title, "<h1>%s</h1><p>Utility page.</p>" % title,
            extra_head='<meta name="robots" content="noindex, nofollow">')
    files["sitemap.xml"] = files["sitemap.xml"].replace(
        "</urlset>",
        "".join("<url><loc>%s/%s.html</loc><lastmod>2026-08-12</lastmod></url>\n"
                % (ORIGIN, name) for name in ("cart", "account", "checkout"))
        + "</urlset>")
    return files


def m_ua_blocked(files):
    """A CDN serving 403 to non-browser agents while browsers get 200."""
    files["_rules.json"] = json.dumps({
        "description": "edge blocks any user agent that is not a mainstream browser",
        "ua_block": {
            "allow_substrings": ["Mozilla/5.0 (Windows", "Mozilla/5.0 (Macintosh"],
            "status": 403,
            "body": "Forbidden",
        },
    }, indent=2)
    return files



def m_no_h1(files):
    """Product templates lose their h1 (replaced by an equivalent div), nothing else changes."""
    for sku in ("alpha", "beta", "gamma"):
        path = "products/%s.html" % sku
        files[path] = re.sub(
            r'<h1 id="top">([^<]*)</h1>', r'<div id="top" class="title">\1</div>',
            files[path])
    return files


def m_duplicate_titles(files):
    """Product templates all render one shared static title instead of their own name."""
    for sku in ("alpha", "beta", "gamma"):
        path = "products/%s.html" % sku
        files[path] = re.sub(r"<title>[^<]*</title>", "<title>Shop</title>", files[path])
    files["about.html"] = re.sub(r"<title>[^<]*</title>", "<title>Shop</title>",
                                 files["about.html"])
    files["contact.html"] = re.sub(r"<title>[^<]*</title>", "<title>Shop</title>",
                                   files["contact.html"])
    return files


def m_interstitial_shell(files):
    """A consent dialog replaces the product pages' real content in the raw response."""
    dialog = (
        '<div role="dialog" aria-modal="true">'
        '<p>We use cookies to improve your experience. Please accept to continue.</p>'
        '<button>Accept</button></div>'
    )
    for sku in ("alpha", "beta", "gamma"):
        path = "products/%s.html" % sku
        files[path] = page(
            "/products/%s.html" % sku, "%s Caliper" % sku.title(), "Loading.", dialog)
    return files


def m_org_identity_conflict(files):
    """The contact page's own Organization node shares the homepage's @id but
    disagrees with it on telephone. Homepage is untouched; single variable."""
    files["contact.html"] = files["contact.html"].replace(
        "+44 20 7946 0810", "+44 20 7946 0555")
    conflicting = jsonld({
        "@context": "https://schema.org", "@type": "ContactPage",
        "mainEntity": {"@id": ORIGIN + "/#organization", "@type": "Organization",
                       "telephone": "+44 20 7946 0555"},
    })
    files["contact.html"] = files["contact.html"].replace(
        '<h1 id="top">Contact %s</h1>' % BRAND,
        conflicting + '\n<h1 id="top">Contact %s</h1>' % BRAND)
    return files


def m_no_structured_data_clean(files):
    """A well-built, valid site with every JSON-LD block removed. Headings, titles,
    canonicals and text all stay correct; only structured data is absent."""
    for path in list(files):
        if path.endswith(".html"):
            files[path] = re.sub(
                r'<script type="application/ld\+json">.*?</script>', "", files[path],
                flags=re.S)
    return files


def m_article_pages(files):
    """Adds two article pages: one fully compliant, one missing a required property.
    Neither touches any existing page, so all prior expectations still hold."""
    compliant_jsonld = jsonld({
        "@context": "https://schema.org", "@type": "Article",
        "headline": "Choosing the right caliper for your workshop",
        "datePublished": "2026-03-01", "author": {"@type": "Person", "name": "J. Reyes"},
        "publisher": {"@id": ORIGIN + "/#organization"},
    })
    files["articles/choosing-a-caliper.html"] = page(
        "/articles/choosing-a-caliper.html",
        "Choosing the right caliper for your workshop",
        "A guide to selecting a precision caliper.",
        breadcrumb([("Home", "/"), ("Articles", "/articles/"),
                   ("Choosing a caliper", "/articles/choosing-a-caliper.html")])
        + compliant_jsonld + """
<article>
<h1 id="top">Choosing the right caliper for your workshop</h1>
<p>By J. Reyes, published 1 March 2026.</p>
<p>A precision caliper is one of the most useful tools in any workshop. This guide
covers what to look for: measuring range, resolution, and build quality, so you can
pick the right one for the job at hand.</p>
<h2 id="range">Measuring range</h2>
<p>Most hobbyist work is comfortably covered by a 150 millimetre range, while larger
components call for a longer jaw.</p>
</article>
""")
    incomplete_jsonld = jsonld({
        "@context": "https://schema.org", "@type": "Article",
        "headline": "Caring for your precision instruments",
        "author": {"@type": "Person", "name": "J. Reyes"},
    })
    files["articles/caring-for-instruments.html"] = page(
        "/articles/caring-for-instruments.html",
        "Caring for your precision instruments",
        "How to keep a precision caliper accurate for years.",
        breadcrumb([("Home", "/"), ("Articles", "/articles/"),
                   ("Caring for instruments", "/articles/caring-for-instruments.html")])
        + incomplete_jsonld + """
<article>
<h1 id="top">Caring for your precision instruments</h1>
<p>By J. Reyes.</p>
<p>A precision caliper stays accurate for years with a little care: keep it clean, store
it in its case, and have it recalibrated periodically against a reference standard.</p>
<h2 id="storage">Storage</h2>
<p>Always return the caliper to its fitted case after use to protect the jaws from
knocks.</p>
</article>
""")
    files["sitemap.xml"] = files["sitemap.xml"].replace(
        "</urlset>",
        "<url><loc>%s/articles/choosing-a-caliper.html</loc></url>\n"
        "<url><loc>%s/articles/caring-for-instruments.html</loc></url>\n</urlset>"
        % (ORIGIN, ORIGIN))
    return files


def m_buried_answer(files):
    """The price is stated only after several paragraphs of unrelated narrative,
    instead of near the top of the page."""
    filler = (" ".join(["Our workshop has been perfecting precision tools for "
                        "measuring small components with great care and attention."]
                       * 6))
    prices = {"alpha": "59.00", "beta": "74.00", "gamma": "88.00"}
    for sku, price in prices.items():
        path = "products/%s.html" % sku
        files[path] = files[path].replace(
            "It costs\n%s GBP and is in stock, shipping within two working days."
            % price,
            filler + " It costs\n%s GBP and is in stock, shipping within two "
            "working days." % price)
    return files


def m_specs_in_prose(files):
    """Specification values stay in prose; the table is removed, no image or PDF
    replaces it (unlike F06, which moves the values into an image and a PDF)."""
    for sku in ("alpha", "beta", "gamma"):
        path = "products/%s.html" % sku
        files[path] = files[path].replace(
            files[path][files[path].index("<h2 id=\"specifications\">"):
                       files[path].index("</table>") + 8],
            "<h2 id=\"specifications\">Specifications</h2>\n"
            "<p>It measures 0 to 150.5 millimetres with a resolution of 0.01 "
            "millimetres, and weighs 240.0 grams in total.</p>")
    return files


def m_unitless_values(files):
    """A decimal rating value stated in prose with no unit or currency nearby."""
    for sku in ("alpha", "beta", "gamma"):
        path = "products/%s.html" % sku
        files[path] = files[path].replace(
            "<h2 id=\"in-the-box\">In the box</h2>",
            "<p>Owners rate this instrument 4.8 in independent workshop surveys.</p>\n"
            "<h2 id=\"in-the-box\">In the box</h2>")
    return files


def m_entity_never_named(files):
    """The product page's body only ever refers to the product as 'it' or 'this
    caliper', never restating the product's own name anywhere after the h1."""
    prices = {"alpha": "59.00", "beta": "74.00", "gamma": "88.00"}
    for sku, price in prices.items():
        path = "products/%s.html" % sku
        name = "%s Caliper" % sku.title()
        files[path] = files[path].replace(
            "The %s is a handheld precision caliper from Larkspur "
            "Instruments. It costs\n%s GBP and is in stock, shipping within two "
            "working days." % (name, price),
            "This handheld precision caliper comes from Larkspur Instruments. It "
            "costs\n%s GBP and is in stock, shipping within two working days." % price)
        files[path] = files[path].replace(
            "The %s, a fitted case, and a calibration certificate." % name,
            "This instrument, a fitted case, and a calibration certificate.")
    return files


def m_long_docs_no_structure(files):
    """A long documentation page with 5 headings and no id attributes, and almost no
    lead-in text before the first section -- single variable: docs page structure."""
    sections = "".join(
        '<h2>Section %d</h2>\n<p>%s</p>\n' % (i, ("Detail about this section. " * 30))
        for i in range(1, 6))
    files["docs/reference.html"] = page(
        "/docs/reference.html", "Reference guide", "Full reference documentation.",
        breadcrumb([("Home", "/"), ("Docs", "/docs/"), ("Reference", "/docs/reference.html")])
        + "<article>\n<h1 id=\"top\">Reference guide</h1>\n" + sections + "</article>\n")
    files["sitemap.xml"] = files["sitemap.xml"].replace(
        "</urlset>", "<url><loc>%s/docs/reference.html</loc></url>\n</urlset>" % ORIGIN)
    return files


def m_faq_not_questions(files):
    """The FAQ page is classified as FAQ content but its headings are statements,
    not questions."""
    files["faq.html"] = files["faq.html"].replace(
        "How long is the warranty?", "Warranty information")
    files["faq.html"] = files["faq.html"].replace(
        "Do you ship internationally?", "International shipping")
    return files


def m_no_canonical_fact_surface(files):
    """No single page combines the brand name with two or more key facts: the
    founding year moves off the about page entirely, leaving facts scattered thinly."""
    files["about.html"] = files["about.html"].replace(
        "Larkspur Instruments was founded in 1994 in Fairhaven and makes precision "
        "measuring instruments.",
        "Larkspur Instruments makes precision measuring instruments.")
    files["about.html"] = files["about.html"].replace(
        "<dt>Founded</dt><dd>1994</dd>", "")
    files["about.html"] = files["about.html"].replace(
        "Updated 12 August 2026.", "")
    files["contact.html"] = files["contact.html"].replace(
        "+44 20 7946 0810", "our contact form")
    files["index.html"] = files["index.html"].replace(
        "Founded in 1994, our", "Our")
    return files


def m_key_fact_outside_main(files):
    """The product price appears in the page footer (outside <main>, matching this
    fixture generator's own FOOT template) but not within the main content region.
    The specification table's own price row is also removed, so the price genuinely
    does not appear anywhere inside <main> -- otherwise it would just be a page where
    the price is stated twice within main content, not outside it."""
    prices = {"alpha": "59.00", "beta": "74.00", "gamma": "88.00"}
    for sku, price in prices.items():
        path = "products/%s.html" % sku
        files[path] = files[path].replace(
            "It costs\n%s GBP and is in stock, shipping within two working days."
            % price,
            "It is a precision instrument built for daily workshop use.")
        files[path] = files[path].replace(
            "<tr><th>Price</th><td>%s GBP</td></tr>" % price, "")
        files[path] = files[path].replace(
            "</footer>",
            "<p>Price: %s GBP. Call for trade pricing.</p>\n</footer>" % price)
    return files


def m_sku_price_conflict(files):
    """The homepage features the Alpha Caliper at a different price than its own
    product page states, matched by the same sku -- a genuine cross-page price
    conflict for the same product, not different products."""
    files["index.html"] = files["index.html"].replace(
        "<li><a href=\"/products/alpha.html\">Alpha Caliper</a>, 59.00 GBP</li>",
        "<li><a href=\"/products/alpha.html\">Alpha Caliper</a>, 49.00 GBP</li>")
    featured = jsonld({
        "@context": "https://schema.org", "@type": "Product", "name": "Alpha Caliper",
        "sku": "ALPHA", "offers": {"@type": "Offer", "price": "49.00",
                                   "priceCurrency": "GBP"},
    })
    files["index.html"] = files["index.html"].replace(
        "</head>", featured + "\n</head>")
    return files


def m_date_signal_conflict(files):
    """A product page's own JSON-LD dateModified disagrees by months with its
    sitemap lastmod entry -- both signals genuinely present, genuinely disagreeing."""
    files["products/alpha.html"] = files["products/alpha.html"].replace(
        '"sku": "ALPHA"}', '"sku": "ALPHA", "dateModified": "2026-01-15"}')
    files["sitemap.xml"] = re.sub(
        r"(<loc>%s/products/alpha\.html</loc>)<lastmod>[^<]*</lastmod>"
        % re.escape(ORIGIN),
        r"\1<lastmod>2026-08-01</lastmod>", files["sitemap.xml"])
    return files


def m_availability_missing(files):
    """Product pages state a price but no availability property at all."""
    for sku in ("alpha", "beta", "gamma"):
        path = "products/%s.html" % sku
        files[path] = re.sub(
            r',\s*"availability":\s*"https://schema\.org/InStock"', "", files[path])
    return files


def m_current_and_dated_clean(files):
    """A negative control: a genuinely current page claiming to be the 'latest'
    model, with a date signal that is NOT older than the rest of the site -- must
    never be flagged, unlike the stale-claim positive case."""
    files["products/alpha.html"] = files["products/alpha.html"].replace(
        "The Alpha Caliper is a handheld precision caliper from Larkspur "
        "Instruments.",
        "The Alpha Caliper is our latest precision caliper from Larkspur "
        "Instruments.")
    # Dates match each page's own real sitemap lastmod (2026-08-14 / -08-09 / -08-11
    # respectively) so this fixture tests ONLY the stale-claim dimension -- a
    # genuinely current, non-conflicting date signal -- without also introducing an
    # unrelated date-signal disagreement within the same page.
    files["products/alpha.html"] = files["products/alpha.html"].replace(
        '"sku": "ALPHA"}', '"sku": "ALPHA", "dateModified": "2026-08-14"}')
    files["products/beta.html"] = files["products/beta.html"].replace(
        '"sku": "BETA"}', '"sku": "BETA", "dateModified": "2026-08-09"}')
    files["products/gamma.html"] = files["products/gamma.html"].replace(
        '"sku": "GAMMA"}', '"sku": "GAMMA", "dateModified": "2026-08-11"}')
    return files


def m_eng_dead_end_product(files):
    """Single variable: the Alpha Caliper product page loses its two in-content
    links ("full range", "frequently asked questions"), leaving zero in-content
    links -- an unambiguous dead end. Other products are untouched, so this is a
    page-level, not template-level, condition."""
    files["products/alpha.html"] = re.sub(
        r'<p>See also the.*?questions</a>\.</p>\n?', '',
        files["products/alpha.html"], flags=re.S)
    return files


def m_eng_healthy_action_and_related(files):
    """Negative control: a product page with a clear purchase/contact action link
    and a genuine related-content link, to confirm neither
    ENG.WEAK_ACTION_PATHWAY nor ENG.NO_RELATED_CONTENT_PATHWAY fires on a healthy
    page. Also adds a second inbound link to legal.html so it is not orphan-like,
    isolating each fixture to test one condition at a time."""
    files["products/alpha.html"] = files["products/alpha.html"].replace(
        "</article>",
        '<p><a href="/contact.html">Contact us to buy</a> or see the '
        '<a href="/products/beta.html">Beta Caliper</a> for a larger range.</p>\n'
        '</article>')
    return files


def m_eng_orphan_page(files):
    """Single variable: about.html is removed from the homepage's navigation and
    from every other page's links, but remains in the sitemap and fully fetchable
    -- orphan-like within the sampled graph."""
    for path in ("index.html", "products/alpha.html", "products/beta.html",
                "products/gamma.html", "contact.html", "faq.html", "legal.html",
                "products/index.html"):
        if path in files:
            files[path] = files[path].replace(
                '<a href="/about.html">', '<a href="/about.html" data-removed-nav="1" '
                'style="display:none">')
    # The style/attribute trick above keeps the anchor technically present but the
    # collector's link extraction is text-based, not CSS-aware, so instead remove
    # the nav link outright to genuinely eliminate the inbound reference.
    for path in ("index.html", "products/alpha.html", "products/beta.html",
                "products/gamma.html", "contact.html", "faq.html", "legal.html",
                "products/index.html"):
        if path in files:
            files[path] = re.sub(
                r'<a href="/about\.html"[^>]*>[^<]*</a>\n?', "", files[path])
    return files


def m_eng_ambiguous_action_surface(files):
    """Single variable: the Alpha Caliper product page gains two in-content links
    that both say 'Learn more' but point to different destinations."""
    files["products/alpha.html"] = files["products/alpha.html"].replace(
        "</article>",
        '<p><a href="/products/beta.html">Learn more</a> or '
        '<a href="/products/gamma.html">Learn more</a>.</p>\n</article>')
    return files

FIXTURES = [
    ("F00-clean-control", None,
     "Correctly built site. The precision test: nothing above info may fire."),
    ("F01-csr-shell", m_csr_shell,
     "Product content only exists after JavaScript runs."),
    ("F02-robots-blocks-retrieval", m_robots_blocks_retrieval,
     "Retrieval and user-triggered agents disallowed sitewide."),
    ("F03-robots-blocks-training-only", m_robots_blocks_training_only,
     "Negative control: a deliberate training opt-out with retrieval allowed."),
    ("F04-schema-visible-mismatch", m_schema_visible_mismatch,
     "Structured price contradicts the visible price."),
    ("F05-deeplink-redirect", m_deeplink_redirect,
     "Published deep links bounce to the homepage and drop the fragment."),
    ("F06-facts-in-images", m_facts_in_images,
     "Specifications exist only as an image and a PDF."),
    ("F07-stale-conflict", m_stale_conflict,
     "The site contradicts itself on tagline, founding year, price and telephone."),
    ("F08-non-english-clean", m_non_english,
     "Negative control: a valid site that is not in English."),
    ("F09-small-site-clean", m_small_site,
     "Negative control: a correct two-page site below the template threshold."),
    ("F10-microdata-only", m_microdata_only,
     "Negative control: valid Microdata and no JSON-LD is not a defect."),
    ("F11-noindex-utility-ok", m_noindex_utility,
     "Negative control: correctly noindexed utility pages."),
    ("F12-ua-blocked", m_ua_blocked,
     "The edge serves 403 to non-browser agents while browsers get 200."),
    ("F13-no-h1", m_no_h1,
     "Product templates lose their h1 heading, nothing else changes."),
    ("F14-duplicate-titles", m_duplicate_titles,
     "Five distinct pages share one static title."),
    ("F15-interstitial-shell", m_interstitial_shell,
     "A consent dialog replaces the product pages' real content in the raw response."),
    ("F16-org-identity-conflict", m_org_identity_conflict,
     "The contact page's own Organization node shares the homepage's @id but "
     "disagrees on telephone."),
    ("F17-no-structured-data-clean", m_no_structured_data_clean,
     "A well-built, valid site with all structured data removed."),
    ("F18-article-pages", m_article_pages,
     "Two article pages: one fully compliant, one missing a required property."),
    ("F19-buried-answer", m_buried_answer,
     "The price appears only after several paragraphs of unrelated narrative."),
    ("F20-specs-in-prose", m_specs_in_prose,
     "Specification values stay in prose; no table exists to hold them."),
    ("F21-unitless-values", m_unitless_values,
     "A decimal rating value with no unit anywhere nearby."),
    ("F22-entity-never-named", m_entity_never_named,
     "The body only ever refers to the product as 'it', never restating its name."),
    ("F23-long-docs-no-structure", m_long_docs_no_structure,
     "A long documentation page with no heading ids and no lead summary."),
    ("F24-faq-not-questions", m_faq_not_questions,
     "The FAQ page's headings are statements, not questions."),
    ("F25-no-canonical-fact-surface", m_no_canonical_fact_surface,
     "No single page combines the brand name with two or more key facts."),
    ("F26-key-fact-outside-main", m_key_fact_outside_main,
     "The price appears only in the page footer, outside the main content region."),
    ("F27-sku-price-conflict", m_sku_price_conflict,
     "The homepage features the Alpha Caliper at a different price than its own "
     "product page, matched by sku."),
    ("F28-date-signal-conflict", m_date_signal_conflict,
     "A product page's structured dateModified disagrees by months with its own "
     "sitemap lastmod entry."),
    ("F29-availability-missing", m_availability_missing,
     "Product pages state a price but no availability property at all."),
    ("F30-current-and-dated-clean", m_current_and_dated_clean,
     "A genuinely current page claiming to be the latest model, with a date signal "
     "that is not older than the rest of the site -- negative control."),
    ("F31-eng-dead-end-product", m_eng_dead_end_product,
     "A product page loses all in-content links, leaving an unambiguous dead end."),
    ("F32-eng-healthy-action-and-related", m_eng_healthy_action_and_related,
     "A product page with a clear action link and a genuine related-product link "
     "-- negative control."),
    ("F33-eng-orphan-page", m_eng_orphan_page,
     "The about page is removed from every page's navigation and content links, "
     "remaining reachable only via the sitemap -- orphan-like within the sampled "
     "graph."),
    ("F34-eng-ambiguous-action-surface", m_eng_ambiguous_action_surface,
     "Two in-content links on one page both say 'Learn more' but lead to "
     "different products."),
]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the local fixture sites.")
    parser.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "fixtures"))
    args = parser.parse_args(argv)

    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out)

    index = []
    for fixture_id, mutation, description in FIXTURES:
        files = build_base()
        if mutation is not None:
            files = mutation(files)
        target = os.path.join(args.out, fixture_id)
        for rel, content in sorted(files.items()):
            path = os.path.join(target, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
        meta = {"id": fixture_id, "description": description,
                "files": sorted(files.keys()),
                "negative_control": "clean" in fixture_id or "ok" in fixture_id
                                    or "only" in fixture_id}
        with open(os.path.join(target, "_fixture.json"), "w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2)
        index.append(meta)
        print("built %-32s %2d files  %s" % (fixture_id, len(files), description))

    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as handle:
        json.dump({"fixtures": index}, handle, indent=2)
    print("\n%d fixtures written to %s" % (len(index), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
