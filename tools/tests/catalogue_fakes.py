"""A fake shop for the website catalogue tests: robots, sitemaps, product pages."""

from __future__ import annotations

import gzip
import json
from typing import Any

import httpx
import respx

SITE = "https://shop.example.com"
SHOP_IP = "93.184.216.34"
PRIVATE_IP = "10.0.0.5"

ADDRESSES = {
    "shop.example.com": [SHOP_IP],
    "www.shop.example.com": [SHOP_IP],
    "cdn.example.net": ["151.101.1.1"],
    "evil.example.com": [PRIVATE_IP],
    "mixed.example.com": [SHOP_IP, "127.0.0.1"],
    "mapped.example.com": ["::ffff:192.168.1.10"],
}


async def fake_resolver(host: str, port: int) -> list[str]:
    del port
    if host not in ADDRESSES:
        raise OSError("unknown host")
    return ADDRESSES[host]


def product_page(
    *,
    sku: str,
    name: str,
    price: Any = "29.95",
    brand: Any = "Crewsaver",
    description: str = "",
    availability: str = "https://schema.org/InStock",
    currency: str | None = "EUR",
    crumbs: tuple[str, ...] = ("Home", "Safety", "Lifejackets"),
    graph: bool = False,
) -> str:
    offers: dict[str, Any] = {"@type": "Offer", "price": price}
    if availability:
        offers["availability"] = availability
    if currency:
        offers["priceCurrency"] = currency
    product: dict[str, Any] = {
        "@type": "Product",
        "sku": sku,
        "name": name,
        "brand": {"@type": "Brand", "name": brand} if brand else None,
        "description": description,
        "offers": [offers],
    }
    breadcrumb = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "item": {"name": c}}
            for i, c in enumerate([*crumbs, name], start=1)
        ],
    }
    scripts = (
        [{"@context": "https://schema.org", "@graph": [breadcrumb, product]}]
        if graph
        else [breadcrumb, product]
    )
    body = "".join(
        f'<script type="application/ld+json">{json.dumps(s)}</script>' for s in scripts
    )
    return f"<html><head><title>{name}</title>{body}</head><body>x</body></html>"


PRODUCTS: dict[str, str] = {
    "/products/child-lifejacket": product_page(
        sku="CS-100",
        name="Crewsaver Child Lifejacket 150N",
        price="49.95",
        description="Foam lifejacket for children 15-30kg.",
    ),
    "/products/kobra-anchor": product_page(
        sku="PL-6",
        name="Plastimo Kobra Anchor 6kg",
        brand="Plastimo",
        price="89",
        description="Galvanised anchor for small boats.",
        crumbs=("Home", "Deck", "Anchoring"),
        graph=True,
    ),
    "/products/gelcoat-restorer": product_page(
        sku="SB-9",
        name="Gel Coat Restorer",
        brand="Starbrite",
        price="24.50",
        availability="https://schema.org/OutOfStock",
        description="Cleans the hull and restores shine to gelcoat in minutes.",
        crumbs=("Home", "Maintenance"),
    ),
}
NOT_A_PRODUCT = "<html><body>About us</body></html>"

ROBOTS = (
    "User-agent: *\n"
    "Disallow: /products/secret\n"
    "Disallow: /checkout\n"
    f"Sitemap: {SITE}/sitemap_index.xml\n"
)


def urlset(paths: list[str], *, host: str = SITE) -> str:
    locs = "".join(f"<url><loc>{host}{p}</loc></url>" for p in paths)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'
    )


def sitemap_index(urls: list[str]) -> str:
    locs = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in urls)
    return f"<sitemapindex>{locs}</sitemapindex>"


class FakeShop:
    def __init__(self, router: respx.MockRouter) -> None:
        self.router = router
        self.pages = dict(PRODUCTS)
        self.pages["/about"] = NOT_A_PRODUCT
        self.pages["/products/secret"] = PRODUCTS["/products/child-lifejacket"]
        self.robots = router.get(f"{SITE}/robots.txt").mock(
            return_value=httpx.Response(200, text=ROBOTS)
        )
        product_paths = [
            *PRODUCTS,
            "/about",
            "/products/secret",
            "/products/broken",
        ]
        self.index = router.get(f"{SITE}/sitemap_index.xml").mock(
            return_value=httpx.Response(
                200,
                text=sitemap_index(
                    [f"{SITE}/sitemap-pages.xml", f"{SITE}/sitemap-products.xml.gz"]
                ),
            )
        )
        products_xml = urlset(product_paths) + ""
        offsite = "<url><loc>https://other.example.org/products/x</loc></url>"
        products_xml = products_xml.replace("</urlset>", offsite + "</urlset>")
        self.products_sitemap = router.get(f"{SITE}/sitemap-products.xml.gz").mock(
            return_value=httpx.Response(
                200, content=gzip.compress(products_xml.encode())
            )
        )
        self.pages_sitemap = router.get(f"{SITE}/sitemap-pages.xml").mock(
            return_value=httpx.Response(200, text=urlset(["/about"]))
        )
        self.broken = router.get(f"{SITE}/products/broken").mock(
            return_value=httpx.Response(500)
        )
        self.page = router.get(url__regex=rf"^{SITE}/(products|about)").mock(
            side_effect=self._page
        )
        self.user_agents: list[str] = []
        self.default_sitemap = router.get(f"{SITE}/sitemap.xml").mock(
            return_value=httpx.Response(404)
        )
        # Anything else on the shop is missing, as on a real site.
        router.get(url__startswith=SITE).mock(return_value=httpx.Response(404))

    def _page(self, request: httpx.Request) -> httpx.Response:
        self.user_agents.append(request.headers.get("user-agent", ""))
        html = self.pages.get(request.url.path)
        if html is None:
            return httpx.Response(404)
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})


def catalogue_config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"site_url": SITE, "request_delay_seconds": 0.2}
    config.update(overrides)
    return config
