"""Website catalogue: parsing, speech, SSRF guard, crawl + sync, search."""

from __future__ import annotations

import asyncio
import gzip
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import httpcore
import httpx
import pytest
import respx
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from fallcha_tools.core.container import AppServices
from fallcha_tools.core.db import Database
from fallcha_tools.core.netguard import (
    BlockedUrlError,
    GuardedFetcher,
    GuardedNetworkBackend,
    check_url,
    guarded_client,
    ip_is_public,
    system_resolver,
)
from fallcha_tools.core.provider import ProviderRegistry, SyncFailed
from fallcha_tools.core.sync import sync_lock_id
from fallcha_tools.providers.website_catalogue import WebsiteCatalogueProvider
from fallcha_tools.providers.website_catalogue.crawler import (
    USER_AGENT_TOKEN,
    sitemap_locs,
)
from fallcha_tools.providers.website_catalogue.parse import parse_product
from fallcha_tools.providers.website_catalogue.service import CatalogueService
from fallcha_tools.providers.website_catalogue.settings import CatalogueConfig
from fallcha_tools.providers.website_catalogue.speech import (
    number_words,
    spoken_price,
)
from fallcha_tools.providers.website_catalogue.store import (
    CatalogueStore,
    near_query,
    query_terms,
)
from tests.catalogue_fakes import (
    PRODUCTS,
    SITE,
    FakeShop,
    catalogue_config,
    fake_resolver,
    product_page,
)
from tests.conftest import TEST_DATABASE_URL, internal_headers, issue_key
from tests.echo_provider import EchoProvider
from tests.test_mcp import mcp_client

PROVIDER = "website-catalogue"


# --- parsing and speech ---------------------------------------------------------


def test_parse_product_reads_json_ld() -> None:
    html = PRODUCTS["/products/child-lifejacket"]
    product = parse_product(html, f"{SITE}/p", "EUR")
    assert product is not None
    assert (product.sku, product.name, product.brand) == (
        "CS-100",
        "Crewsaver Child Lifejacket 150N",
        "Crewsaver",
    )
    assert product.category == "Safety > Lifejackets"
    assert product.price == Decimal("49.95") and product.currency == "EUR"
    assert product.availability == "InStock"
    graph = parse_product(PRODUCTS["/products/kobra-anchor"], f"{SITE}/a", "EUR")
    assert graph is not None and graph.category == "Deck > Anchoring"
    assert graph.price == Decimal("89.00")


def test_parse_product_edge_cases() -> None:
    assert parse_product("<html>no data</html>", "u", "EUR") is None
    assert parse_product(product_page(sku="", name="X"), "u", "EUR") is None
    no_price = parse_product(
        product_page(sku="A", name="X", price="", currency=None), "u", "GBP"
    )
    assert no_price is not None and no_price.price is None
    assert no_price.currency == "GBP"  # the connection's default currency
    broken = '<script type="application/ld+json">{not json</script>'
    assert parse_product(broken, "u", "EUR") is None


def test_spoken_prices() -> None:
    assert spoken_price(Decimal("29.95"), "EUR") == "twenty-nine euro ninety-five"
    assert spoken_price(Decimal("89"), "EUR") == "eighty-nine euro"
    assert spoken_price(Decimal("1"), "GBP") == "one pound"
    assert spoken_price(Decimal("2.50"), "USD") == "two dollars fifty"
    assert spoken_price(None, "EUR") == "price on request"
    assert number_words(1050) == "one thousand and fifty"
    assert number_words(2345) == "two thousand three hundred and forty-five"


def test_query_terms_and_near_query() -> None:
    assert query_terms("Do you have any rope for a BOAT?") == ["rope"]
    assert query_terms("something to clean the hull") == ["clean", "hull"]
    query = near_query(["clean", "hull"])
    assert query is not None and "(clean <1> hull)" in query
    assert "(hull <3> clean)" in query
    assert near_query(["one"]) is None


def test_sitemap_locs_handles_gzip_and_entities() -> None:
    xml = "<urlset><url><loc>https://s.com/p?a=1&amp;b=2</loc></url></urlset>"
    assert sitemap_locs(xml.encode()) == (False, ["https://s.com/p?a=1&b=2"])
    assert sitemap_locs(gzip.compress(xml.encode()))[1] == ["https://s.com/p?a=1&b=2"]
    index = "<sitemapindex><sitemap><loc>https://s.com/a.xml</loc></sitemap>"
    assert sitemap_locs(index.encode())[0] is True


def test_config_validation() -> None:
    config = CatalogueConfig.model_validate({"site_url": SITE, "currency": "gbp"})
    assert config.currency == "GBP" and config.max_products == 2000
    for bad in ("ftp://shop.example.com", "http://10.0.0.1", "http://localhost"):
        with pytest.raises(ValidationError):
            CatalogueConfig.model_validate({"site_url": bad})
    with pytest.raises(ValidationError, match="start with /"):
        CatalogueConfig.model_validate({"site_url": SITE, "include_paths": ["x"]})


# --- SSRF guard -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("10.1.2.3", False),
        ("172.16.0.1", False),
        ("192.168.0.1", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),  # cloud metadata
        ("100.64.0.1", False),  # CGNAT
        ("0.0.0.0", False),
        ("224.0.0.1", False),
        ("::1", False),
        ("fe80::1", False),
        ("fc00::1", False),
        ("::ffff:127.0.0.1", False),
        ("2002:c0a8:0101::", False),  # 6to4 of 192.168.1.1
        ("64:ff9b::a00:1", False),  # NAT64 of 10.0.0.1
        ("64:ff9b::5db8:d822", True),  # NAT64 of a public address
        ("::10.0.0.1", False),  # IPv4-compatible
        ("::", False),
        ("not-an-ip", False),
    ],
)
def test_ip_is_public(ip: str, public: bool) -> None:
    assert ip_is_public(ip) is public


@pytest.mark.parametrize(
    "url",
    [
        "ftp://shop.example.com/x",
        "file:///etc/passwd",
        "https://user:pw@shop.example.com/",
        "https://shop.example.com:22/",
        "gopher://shop.example.com/",
    ],
)
def test_check_url_rejects(url: str) -> None:
    with pytest.raises(BlockedUrlError):
        check_url(url)


@pytest.mark.parametrize(
    ("host", "fragment"),
    [
        ("evil.example.com", "not a public"),
        ("mixed.example.com", "not a public"),  # one bad address is enough
        ("mapped.example.com", "not a public"),
        ("nowhere.example.com", "could not be resolved"),
    ],
)
async def test_fetcher_blocks_private_hosts(host: str, fragment: str) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__regex=r".*").mock(return_value=httpx.Response(200))
        async with httpx.AsyncClient() as http:
            fetcher = GuardedFetcher(http=http, user_agent="t", resolver=fake_resolver)
            with pytest.raises(BlockedUrlError, match=fragment):
                await fetcher.get(f"https://{host}/x", max_bytes=1000)
        assert not route.called


async def test_fetcher_checks_every_redirect() -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{SITE}/go").mock(
            return_value=httpx.Response(
                302, headers={"location": "http://evil.example.com/admin"}
            )
        )
        internal = router.get("http://evil.example.com/admin").mock(
            return_value=httpx.Response(200)
        )
        router.get(f"{SITE}/loop").mock(
            return_value=httpx.Response(302, headers={"location": "/loop"})
        )
        router.get(f"{SITE}/ok").mock(
            return_value=httpx.Response(301, headers={"location": "/final"})
        )
        router.get(f"{SITE}/final").mock(return_value=httpx.Response(200, text="hi"))
        async with httpx.AsyncClient() as http:
            fetcher = GuardedFetcher(http=http, user_agent="t", resolver=fake_resolver)
            with pytest.raises(BlockedUrlError, match="not a public"):
                await fetcher.get(f"{SITE}/go", max_bytes=1000)
            assert not internal.called
            with pytest.raises(BlockedUrlError, match="too many redirects"):
                await fetcher.get(f"{SITE}/loop", max_bytes=1000)
            final = await fetcher.get(f"{SITE}/ok", max_bytes=1000)
    assert final.url == httpx.URL(f"{SITE}/final") and final.content == b"hi"


async def test_fetcher_caps_response_size() -> None:
    from fallcha_tools.core.netguard import ResponseTooLargeError

    with respx.mock() as router:
        router.get(f"{SITE}/big").mock(
            return_value=httpx.Response(200, content=b"x" * 5000)
        )
        async with httpx.AsyncClient() as http:
            fetcher = GuardedFetcher(http=http, user_agent="t", resolver=fake_resolver)
            with pytest.raises(ResponseTooLargeError):
                await fetcher.get(f"{SITE}/big", max_bytes=1000)


async def test_connect_time_guard_blocks_loopback() -> None:
    """Defence in depth against DNS rebinding: the transport itself refuses
    to connect to a non-public address, whatever the earlier check saw."""
    backend = GuardedNetworkBackend(system_resolver)
    with pytest.raises(httpcore.ConnectError, match="not a public"):
        await backend.connect_tcp("localhost", 80)
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_unix_socket("/var/run/docker.sock")
    async with guarded_client(system_resolver) as http:
        with pytest.raises(httpx.ConnectError):
            await http.get("http://127.0.0.1:8080/")


# --- through the app: connect, sync, search -------------------------------------


@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry(
        [WebsiteCatalogueProvider(resolver=fake_resolver), EchoProvider()]
    )


@pytest.fixture
def shop() -> Iterator[FakeShop]:
    with respx.mock(assert_all_called=False) as router:
        yield FakeShop(router)


def services(app: FastAPI) -> AppServices:
    return cast(AppServices, app.state.services)


async def connect(client: httpx.AsyncClient, *, org_id: int = 1, **config: Any) -> str:
    response = await client.post(
        "/internal/connections",
        headers=internal_headers(org_id),
        json={
            "provider": PROVIDER,
            "auth_mode": "none",
            "config": catalogue_config(**config),
        },
    )
    assert response.status_code == 201, response.text
    connection_id: str = response.json()["id"]
    return connection_id


async def sync(
    app: FastAPI, client: httpx.AsyncClient, connection_id: str, *, org_id: int = 1
) -> dict[str, Any]:
    started = await client.post(
        f"/internal/connections/{connection_id}/sync", headers=internal_headers(org_id)
    )
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "running"
    await services(app).sync.wait(uuid.UUID(connection_id))
    got = await client.get(
        f"/internal/connections/{connection_id}", headers=internal_headers(org_id)
    )
    status: dict[str, Any] = got.json()["sync"]
    return status


async def test_catalog_and_none_auth(client: httpx.AsyncClient) -> None:
    catalog = await client.get("/internal/catalog", headers=internal_headers())
    entry = {p["id"]: p for p in catalog.json()["providers"]}[PROVIDER]
    assert entry["auth_modes"] == ["none"]
    assert entry["capabilities"] == ["sync"]
    assert entry["sync_item_label"] == "products"
    assert {t["name"] for t in entry["tools"]} == {"search_products", "product_detail"}
    assert {p["id"]: p for p in catalog.json()["providers"]}["echo"][
        "capabilities"
    ] == []

    with_secret = await client.post(
        "/internal/connections",
        headers=internal_headers(),
        json={
            "provider": PROVIDER,
            "auth_mode": "none",
            "secret": {"x": "y"},
            "config": catalogue_config(),
        },
    )
    assert with_secret.status_code == 422
    echo_without_secret = await client.post(
        "/internal/connections",
        headers=internal_headers(),
        json={"provider": "echo", "auth_mode": "api_key"},
    )
    assert echo_without_secret.status_code == 422
    echo_none = await client.post(
        "/internal/connections",
        headers=internal_headers(),
        json={"provider": "echo", "auth_mode": "none"},
    )
    assert echo_none.status_code == 422  # echo does not support none


async def test_sync_imports_products_politely(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop
) -> None:
    connection_id = await connect(client)
    listed = await client.get("/internal/connections", headers=internal_headers())
    assert listed.json()["connections"][0]["sync"] is None  # never synced

    status = await sync(app, client, connection_id)
    assert status["status"] == "succeeded", status
    assert status["item_count"] == 3 and status["last_error"] is None
    assert status["last_synced_at"] is not None
    # robots.txt Disallow and off-site URLs are never fetched.
    fetched = {call.request.url.path for call in shop.page.calls}
    assert "/products/secret" not in fetched
    assert all(call.request.url.host == "shop.example.com" for call in shop.page.calls)
    assert shop.robots.call_count == 1
    assert all(ua.startswith(USER_AGENT_TOKEN) for ua in shop.user_agents)
    assert set(shop.encodings) == {"gzip"}

    listed = await client.get("/internal/connections", headers=internal_headers())
    assert listed.json()["connections"][0]["sync"]["item_count"] == 3


async def test_include_paths_and_max_products(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop, engine: AsyncEngine
) -> None:
    connection_id = await connect(client, include_paths=["/products/k*"])
    status = await sync(app, client, connection_id)
    assert status["item_count"] == 1
    assert {c.request.url.path for c in shop.page.calls} == {"/products/kobra-anchor"}

    # A capped sync keeps only what it reached, and says it was capped.
    await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": {"include_paths": None, "max_products": 1}},
    )
    status = await sync(app, client, connection_id)
    assert status["status"] == "succeeded"
    assert status["item_count"] == 1
    assert status["note"].startswith("stopped at 1 pages")


async def test_full_sync_prunes_products_gone_from_the_sitemap(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop
) -> None:
    connection_id = await connect(client)
    assert (await sync(app, client, connection_id))["item_count"] == 3
    shop.products_sitemap.mock(
        return_value=httpx.Response(
            200,
            content=gzip.compress(
                b"<urlset><url><loc>https://shop.example.com/products/kobra-anchor"
                b"</loc></url></urlset>"
            ),
        )
    )
    assert (await sync(app, client, connection_id))["item_count"] == 1


async def test_robots_rules(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop
) -> None:
    # robots.txt behind a login: nothing may be crawled.
    connection_id = await connect(client, sitemap_url=f"{SITE}/sitemap_index.xml")
    shop.robots.mock(return_value=httpx.Response(403))
    status = await sync(app, client, connection_id)
    assert status["status"] == "failed"
    assert "no product data" in status["last_error"]
    assert not shop.page.called

    shop.robots.mock(return_value=httpx.Response(503))
    status = await sync(app, client, connection_id)
    assert "robots.txt answered HTTP 503" in status["last_error"]

    # No robots.txt at all: everything may be fetched, from /sitemap.xml.
    await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": {"sitemap_url": None}},
    )
    shop.robots.mock(return_value=httpx.Response(404))
    shop.default_sitemap.mock(
        return_value=httpx.Response(
            200,
            text="<urlset><url><loc>https://shop.example.com/products/secret"
            "</loc></url></urlset>",
        )
    )
    status = await sync(app, client, connection_id)
    assert status["status"] == "succeeded" and status["item_count"] == 1


async def test_sync_refuses_private_sites(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop
) -> None:
    connection_id = await connect(client, site_url="https://evil.example.com")
    status = await sync(app, client, connection_id)
    assert status["status"] == "failed"
    assert "not a public internet address" in status["last_error"]
    # The sitemap must be on the site itself.
    refused = await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={
            "config": {
                "site_url": SITE,
                "sitemap_url": "https://evil.example.com/sitemap.xml",
            }
        },
    )
    assert refused.status_code == 422
    assert "same site" in refused.json()["detail"]
    nat64 = await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": {"site_url": "https://nat64.example.com"}},
    )
    assert nat64.status_code == 200
    status = await sync(app, client, connection_id)
    assert "not a public internet address" in status["last_error"]


async def test_off_site_sitemaps_are_ignored(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop
) -> None:
    shop.robots.mock(
        return_value=httpx.Response(
            200, text="Sitemap: https://cdn.example.net/sitemap.xml\n"
        )
    )
    shop.index.mock(
        return_value=httpx.Response(
            200,
            text="<sitemapindex><sitemap><loc>https://cdn.example.net/x.xml"
            "</loc></sitemap></sitemapindex>",
        )
    )
    offsite = shop.router.get(url__startswith="https://cdn.example.net").mock(
        return_value=httpx.Response(200, text="<urlset></urlset>")
    )
    connection_id = await connect(client)
    status = await sync(app, client, connection_id)
    assert status["status"] == "failed"
    assert not offsite.called
    # robots.txt pointed off-site, so the default /sitemap.xml was used.
    assert shop.default_sitemap.called


async def test_one_sync_per_connection(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop
) -> None:
    connection_id = await connect(client)
    release = asyncio.Event()

    async def slow_robots(request: httpx.Request) -> httpx.Response:
        await release.wait()
        return httpx.Response(404)

    shop.robots.mock(side_effect=slow_robots)
    url = f"/internal/connections/{connection_id}/sync"
    first = await client.post(url, headers=internal_headers())
    assert first.status_code == 202
    second = await client.post(url, headers=internal_headers())
    assert second.status_code == 409
    assert "already running" in second.json()["detail"]
    release.set()
    await services(app).sync.wait(uuid.UUID(connection_id))

    # Another replica holding the lock blocks this one too.
    db = Database(TEST_DATABASE_URL)
    try:
        async with db.engine.connect() as conn:
            await conn.execute(
                text("SELECT pg_advisory_lock(:id)"),
                {"id": sync_lock_id(uuid.UUID(connection_id))},
            )
            await conn.commit()
            blocked = await client.post(url, headers=internal_headers())
            assert blocked.status_code == 409
            await conn.execute(
                text("SELECT pg_advisory_unlock(:id)"),
                {"id": sync_lock_id(uuid.UUID(connection_id))},
            )
    finally:
        await db.dispose()
    assert services(app).sync.running == 0


async def test_sync_is_org_scoped_and_needs_the_capability(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop
) -> None:
    connection_id = await connect(client, org_id=1)
    other_org = await client.post(
        f"/internal/connections/{connection_id}/sync", headers=internal_headers(2)
    )
    assert other_org.status_code == 404
    echo = await client.post(
        "/internal/connections",
        headers=internal_headers(),
        json={"provider": "echo", "auth_mode": "api_key", "secret": {"api_key": "k"}},
    )
    not_syncable = await client.post(
        f"/internal/connections/{echo.json()['id']}/sync", headers=internal_headers()
    )
    assert not_syncable.status_code == 422
    await client.delete(
        f"/internal/connections/{connection_id}", headers=internal_headers()
    )
    revoked = await client.post(
        f"/internal/connections/{connection_id}/sync", headers=internal_headers()
    )
    assert revoked.status_code == 409


async def test_stale_running_sync_reads_as_interrupted(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop, engine: AsyncEngine
) -> None:
    connection_id = await connect(client)
    await sync(app, client, connection_id)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE fallcha_tools.connection_syncs SET status = 'running',"
                " heartbeat_at = :old"
            ),
            {"old": datetime.now(UTC) - timedelta(minutes=10)},
        )
    got = await client.get(
        f"/internal/connections/{connection_id}", headers=internal_headers()
    )
    assert got.json()["sync"]["status"] == "failed"
    assert "interrupted" in got.json()["sync"]["last_error"]


async def test_connection_test(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop
) -> None:
    connection_id = await connect(client)
    result = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert result.json()["ok"], result.text
    assert "sitemap_index.xml" in result.json()["message"]
    shop.index.mock(return_value=httpx.Response(404))
    failed = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert not failed.json()["ok"] and "HTTP 404" in failed.json()["message"]


# --- search semantics (Postgres) ---------------------------------------------------


EXTRA = [
    product_page(
        sku="TT-1",
        name="Tuff Tape",
        brand="Tuff",
        price="9.99",
        description="Repair tape. Waterproof, works on wellies, tents and covers.",
        crumbs=("Home", "Repair"),
    ),
    product_page(
        sku="DB-1",
        name="Deck Brush",
        brand="Shurhold",
        price="19",
        description=(
            "A sturdy brush. Suitable for any small vessel. Great value. Fits "
            "standard handles. Also handy around anchors stowage lockers."
        ),
        crumbs=("Home", "Cleaning"),
    ),
    product_page(
        sku="GC-J",
        name="Guy Cotten Offshore Jacket",
        brand="Guy Cotten",
        price="149",
        description="Waterproof offshore jacket.",
        crumbs=("Home", "Clothing"),
    ),
]


async def seeded_service(
    app: FastAPI, client: httpx.AsyncClient, *, org_id: int = 1, **config: Any
) -> CatalogueService:
    connection_id = uuid.UUID(await connect(client, org_id=org_id, **config))
    store = CatalogueStore(services(app).db)
    pages = [*PRODUCTS.values(), *EXTRA]
    parsed = [parse_product(html, f"{SITE}/{i}", "EUR") for i, html in enumerate(pages)]
    await store.upsert(
        org_id, connection_id, [p for p in parsed if p is not None], datetime.now(UTC)
    )
    return CatalogueService(
        store=store,
        config=CatalogueConfig.model_validate(catalogue_config(**config)),
        org_id=org_id,
        connection_id=connection_id,
    )


async def test_search_semantics(app: FastAPI, client: httpx.AsyncClient) -> None:
    svc = await seeded_service(app, client)

    stemmed = await svc.search("have you lifejackets for kids", None)
    assert stemmed.found and stemmed.products[0].sku == "CS-100"
    assert stemmed.unmatched_terms == ["kids"]
    assert stemmed.say.startswith("I could not find that exact one, but I do have")
    assert "forty-nine euro ninety-five, in stock" in stemmed.say

    exact = await svc.search("crewsaver lifejacket", None)
    assert exact.unmatched_terms == []
    assert exact.say == (
        "I have the Crewsaver Child Lifejacket 150N, forty-nine euro "
        "ninety-five, in stock."
    )

    # One word in a description is noise, not an answer.
    wellies = await svc.search("do you sell wellies", None)
    assert not wellies.found and wellies.products == []
    assert wellies.say == (
        "I could not find that one. Could you describe it a different way, or "
        "tell me the brand? I can also put you through to one of the team."
    )

    # A brand we do not stock is named as missing, the alternative offered.
    musto = await svc.search("musto jacket", None)
    assert musto.unmatched_terms == ["musto"]
    assert [p.sku for p in musto.products] == ["GC-J"]

    # A strong description-only hit: the caller's words next to each other.
    hull = await svc.search("something to clean the hull", None)
    assert [p.sku for p in hull.products] == ["SB-9"]
    assert "not in stock at the moment" in hull.say

    # AND matches only scattered description words; OR finds the anchor.
    anchors = await svc.search("anchors for a small boat", None)
    assert [p.sku for p in anchors.products] == ["PL-6"]

    nothing = await svc.search("the and for", None)
    assert not nothing.found and nothing.unmatched_terms is None


async def test_search_limits_and_surface_first(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    svc = await seeded_service(app, client, max_results=1)
    waterproof = await svc.search("waterproof jacket tape", None)
    assert waterproof.count == 1
    many = await svc.search("waterproof jacket tape", 5)
    skus = [p.sku for p in many.products]
    assert set(skus) == {"GC-J", "TT-1"}
    assert len(skus) == 2


async def test_detail(app: FastAPI, client: httpx.AsyncClient) -> None:
    long_text = "word " * 200
    svc = await seeded_service(app, client, no_match_transfer_offer="")
    await svc.store.upsert(
        svc.org_id,
        svc.connection_id,
        [
            p
            for p in [
                parse_product(
                    product_page(sku="LONG", name="Long One", description=long_text),
                    f"{SITE}/long",
                    "EUR",
                )
            ]
            if p is not None
        ],
        datetime.now(UTC),
    )
    detail = await svc.detail("LONG")
    assert detail.found and detail.description is not None
    assert len(detail.description) <= 403 and detail.description.endswith("...")
    assert detail.say.startswith(
        "The Long One is twenty-nine euro ninety-five and it is in stock."
    )
    missing = await svc.detail("NOPE")
    assert missing.found is False
    assert missing.say == "I do not have the details for that one to hand."
    no_offer = await svc.search("zzzqqq", None)
    assert no_offer.say.endswith("or tell me the brand?")


async def test_catalogues_are_isolated_between_orgs(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    org_one = await seeded_service(app, client, org_id=1)
    org_two = await seeded_service(app, client, org_id=2)
    other = CatalogueService(
        store=org_one.store,
        config=org_one.config,
        org_id=2,  # right org id, wrong connection: nothing
        connection_id=org_one.connection_id,
    )
    assert (await other.detail("CS-100")).found is False
    assert not (await other.search("lifejacket", None)).found
    assert (await org_two.detail("CS-100")).found
    assert await org_one.store.count(1, org_one.connection_id) == 6


# --- MCP and REST compatibility ----------------------------------------------


async def test_mcp_and_rest_compat(app: FastAPI, client: httpx.AsyncClient) -> None:
    svc = await seeded_service(app, client)
    key = await issue_key(client, str(svc.connection_id))
    async with mcp_client(app, f"http://tools/mcp/{PROVIDER}", key) as mcp:
        found = await mcp.call_tool("search_products", {"query": "kobra anchor"})
        assert found.structured_content is not None
        assert found.structured_content["products"][0]["sku"] == "PL-6"
        detail = await mcp.call_tool("product_detail", {"sku": "PL-6"})
        assert detail.structured_content is not None
        assert detail.structured_content["price_spoken"] == "eighty-nine euro"

    shim_style = {"X-API-Key": key}
    miss = await client.post(
        f"/v1/{PROVIDER}/product_search", headers=shim_style, json={"query": "wellies"}
    )
    assert miss.status_code == 200
    assert set(miss.json()) == {"found", "count", "products", "say"}
    hit = await client.post(
        f"/v1/{PROVIDER}/product_search",
        headers={"Authorization": f"Bearer {key}"},
        json={"query": "lifejacket", "max_results": 9},
    )
    assert hit.status_code == 200  # max_results is capped at 5, as before
    assert hit.json()["count"] <= 5
    hit = await client.post(
        f"/v1/{PROVIDER}/product_search",
        headers=shim_style,
        json={"query": "lifejacket"},
    )
    assert set(hit.json()) == {"found", "count", "products", "unmatched_terms", "say"}
    product = hit.json()["products"][0]
    assert set(product) == {
        "sku",
        "name",
        "brand",
        "category",
        "price",
        "currency",
        "price_spoken",
        "in_stock",
        "url",
    }
    detail_miss = await client.post(
        f"/v1/{PROVIDER}/product_detail", headers=shim_style, json={"sku": "NOPE"}
    )
    assert detail_miss.json() == {
        "found": False,
        "say": "I do not have the details for that one to hand.",
    }
    unauthorized = await client.post(
        f"/v1/{PROVIDER}/product_search", json={"query": "x"}
    )
    assert unauthorized.status_code == 401


# --- review follow-ups: robustness -----------------------------------------------


class RecordingProgress:
    def __init__(self) -> None:
        self.calls = 0

    async def heartbeat(self, items: int) -> None:
        self.calls += 1


def sync_context(app: FastAPI, connection_id: str, **config: Any) -> Any:
    from fallcha_tools.core.models import AuthMode
    from fallcha_tools.core.provider import ConnectionContext

    return ConnectionContext(
        org_id=1,
        connection_id=uuid.UUID(connection_id),
        provider=PROVIDER,
        auth_mode=AuthMode.NONE,
        secret={},
        access_token=None,
        http=services(app).http,
        config=catalogue_config(**config),
        db=services(app).db,
    )


async def test_a_bad_page_is_counted_not_fatal(
    app: FastAPI,
    client: httpx.AsyncClient,
    shop: FakeShop,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fallcha_tools.providers.website_catalogue import crawler

    real = parse_product

    def parse(html: str, url: str, currency: str) -> Any:
        if url.endswith("kobra-anchor"):
            raise RecursionError("deeply nested JSON-LD")
        return real(html, url, currency)

    monkeypatch.setattr(crawler, "parse_product", parse)
    connection_id = await connect(client)
    status = await sync(app, client, connection_id)
    assert status["status"] == "succeeded", status
    assert status["item_count"] == 2
    assert "2 page(s) could not be loaded" in status["note"]  # + the 500 page


async def test_a_storage_error_stops_the_sync(
    app: FastAPI,
    client: httpx.AsyncClient,
    shop: FakeShop,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fallcha_tools.providers.website_catalogue import provider as module

    async def broken(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("database went away")

    monkeypatch.setattr(CatalogueStore, "upsert", broken)
    monkeypatch.setattr(module, "UPSERT_BATCH", 1)
    connection_id = await connect(client)
    status = await sync(app, client, connection_id)
    assert status["status"] == "failed"
    assert status["last_error"] == "the sync failed unexpectedly"
    assert services(app).sync.running == 0


async def test_slow_pages_time_out_and_the_run_has_a_deadline(
    app: FastAPI,
    client: httpx.AsyncClient,
    shop: FakeShop,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def drip(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)  # a server that never finishes the body
        return httpx.Response(200)

    shop.page.mock(side_effect=drip)
    connection_id = await connect(client)
    fast = WebsiteCatalogueProvider(
        resolver=fake_resolver, page_timeout=0.1, sitemap_timeout=0.5
    )
    started = asyncio.get_running_loop().time()
    with pytest.raises(SyncFailed, match="no product data"):
        await fast.run_sync(sync_context(app, connection_id), RecordingProgress())
    assert asyncio.get_running_loop().time() - started < 3

    from fallcha_tools.providers.website_catalogue import provider as module

    monkeypatch.setattr(module, "SECONDS_PER_MINUTE", 0.3)
    slow = WebsiteCatalogueProvider(resolver=fake_resolver, page_timeout=10)
    with pytest.raises(SyncFailed, match="took longer than 1 minutes"):
        await slow.run_sync(
            sync_context(app, connection_id, max_sync_minutes=1), RecordingProgress()
        )


async def test_heartbeat_on_every_page_even_without_products(
    app: FastAPI, client: httpx.AsyncClient, shop: FakeShop
) -> None:
    shop.pages = {path: "<html>no product here</html>" for path in shop.pages}
    connection_id = await connect(client)
    progress = RecordingProgress()
    with pytest.raises(SyncFailed):
        await WebsiteCatalogueProvider(resolver=fake_resolver).run_sync(
            sync_context(app, connection_id), progress
        )
    # 3 sitemaps + 6 product-sitemap pages (the 500 one included).
    assert progress.calls >= 9


async def test_progress_writes_are_throttled_and_stop_when_closed(
    app: FastAPI, client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    from fallcha_tools.core.sync import SyncRepository, _Progress

    connection_id = uuid.UUID(await connect(client))
    runner = services(app).sync
    now = datetime.now(UTC)
    ticks = iter([now + timedelta(seconds=s) for s in (1, 30, 31, 90)])
    runner.clock = lambda: next(ticks)
    async with services(app).db.session() as session:
        await SyncRepository(session, lambda: now).mark_running(1, connection_id, 1)
    progress = _Progress(runner, 1, connection_id, now)

    async def beat() -> datetime:
        async with engine.connect() as conn:
            row = await conn.execute(
                text("SELECT heartbeat_at FROM fallcha_tools.connection_syncs")
            )
            value: datetime = row.scalar_one()
            return value

    await progress.heartbeat(1)  # +1 s: throttled
    assert await beat() == now
    await progress.heartbeat(2)  # +30 s: written
    assert await beat() == now + timedelta(seconds=30)
    await progress.heartbeat(3)  # +31 s: throttled
    progress.closed = True
    await progress.heartbeat(4)  # closed: never written
    assert await beat() == now + timedelta(seconds=30)


async def test_guarded_backend_tries_every_vetted_address() -> None:
    attempts: list[str] = []

    stream = cast(httpcore.AsyncNetworkStream, object())

    class Inner(httpcore.AsyncNetworkBackend):
        async def connect_tcp(  # type: ignore[override]
            self, host: str, port: int, **kwargs: Any
        ) -> httpcore.AsyncNetworkStream:
            attempts.append(host)
            if host == "93.184.216.34":
                raise httpcore.ConnectError("refused")
            return stream

    async def two(host: str, port: int) -> list[str]:
        return ["93.184.216.34", "151.101.1.1"]

    backend = GuardedNetworkBackend(two, inner=Inner())
    assert await backend.connect_tcp("shop.example.com", 443) is stream
    assert attempts == ["93.184.216.34", "151.101.1.1"]
