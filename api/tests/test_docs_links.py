"""Every docs link the app shows must reach a page the website actually publishes.

The links used to point at docs.lightmove.ai, which was never set up, so every
"<provider> docs" link in the app was dead. Docs now live on the website
(lightmove-website, Starlight under /docs). PUBLISHED_PAGES mirrors the pages in
lightmove-website/src/content/docs/docs/integrations/; that repo's
tests/docs-links.test.ts checks the same list, so a page renamed on either side
fails a test instead of a customer's click.
"""

from types import SimpleNamespace

import pytest

from api.constants import BRAND_DOCS_URL
from api.services.telephony import registry
from api.services.telephony.providers.cloudonix.setup import (
    MANAGED_DOCS_URL,
    SELF_SERVE_DOCS_URL,
)
from api.services.workflow.node_specs import all_specs

PUBLISHED_PAGES = {
    "integrations/telephony/asterisk-ari",
    "integrations/telephony/twilio",
    "integrations/telephony/telnyx",
    "integrations/telephony/vonage",
    "integrations/telephony/plivo",
    "integrations/telephony/exotel",
    "integrations/telephony/vobiz",
    "integrations/telephony/cloudonix",
    "integrations/telephony/dograh-sip",
    "integrations/paygent",
    "integrations/tuner",
}


def _first_party_links() -> list[tuple[str, str]]:
    links = [
        (f"telephony:{spec.name}", spec.ui_metadata.docs_url)
        for spec in registry.all_specs()
        if spec.ui_metadata and spec.ui_metadata.docs_url
    ]
    links += [("cloudonix:managed", MANAGED_DOCS_URL)]
    links += [("cloudonix:self-serve", SELF_SERVE_DOCS_URL)]
    links += [
        (f"node:{spec.name}", spec.docs_url)
        for spec in all_specs()
        if spec.docs_url and "lightmove" in spec.docs_url
    ]
    return links


def test_docs_live_on_their_own_subdomain():
    assert BRAND_DOCS_URL == "https://docs.lightmove.ai"


def test_every_provider_has_a_docs_link():
    without = [
        spec.name
        for spec in registry.all_specs()
        if not (spec.ui_metadata and spec.ui_metadata.docs_url)
    ]
    assert without == []


@pytest.mark.parametrize(
    ("where", "url"), _first_party_links(), ids=lambda v: str(v)[:60]
)
def test_link_reaches_a_published_page(where: str, url: str):
    assert url.startswith(f"{BRAND_DOCS_URL}/"), (where, url)
    page = url.removeprefix(f"{BRAND_DOCS_URL}/").split("#")[0]
    assert page in PUBLISHED_PAGES, (where, url)


def test_the_link_list_covers_all_published_pages():
    linked = {
        url.removeprefix(f"{BRAND_DOCS_URL}/").split("#")[0]
        for _, url in _first_party_links()
    }
    # Every page we publish is reachable from the app, so the two lists stay one list.
    assert linked == PUBLISHED_PAGES, SimpleNamespace(unlinked=PUBLISHED_PAGES - linked)
