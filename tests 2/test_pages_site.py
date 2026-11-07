"""Regression checks for the GitHub Pages SEO landing site."""

from __future__ import annotations

from html.parser import HTMLParser
import json
import pathlib
import re
import shlex
import subprocess
import tempfile
import unittest
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PAGES_URL = "https://senyo888.github.io/humidity-intelligence/"
INSPECTOR_URL = f"{PAGES_URL}inspector/"
INSPECTOR_SOURCE = SITE / "inspector"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.images: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.structured_data: list[str] = []
        self.title_parts: list[str] = []
        self.resources: list[str] = []
        self.ids: list[str] = []
        self._in_json_ld = False
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "link" and values.get("rel") in {"stylesheet", "icon"}:
            self.resources.append(values["href"])
        if tag == "a" and values.get("href"):
            self.links.append(values["href"] or "")
        if tag == "img" and values.get("src"):
            self.images.append(values["src"] or "")
        if tag == "meta":
            key = (
                values.get("name")
                or values.get("property")
                or values.get("http-equiv")
            )
            content = values.get("content")
            if key and content:
                self.meta[key] = content
        if tag == "link" and values.get("rel") == "canonical":
            self.canonical = values.get("href")
        if tag == "title":
            self._in_title = True
        if tag == "script" and values.get("type") == "application/ld+json":
            self._in_json_ld = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_json_ld:
            self.structured_data.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "script":
            self._in_json_ld = False

    @property
    def title(self) -> str:
        return "".join(self.title_parts).strip()


def parse_index() -> tuple[str, PageParser]:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    parser = PageParser()
    parser.feed(html)
    return html, parser


def parse_inspector() -> tuple[str, PageParser]:
    html = (INSPECTOR_SOURCE / "index.html").read_text(encoding="utf-8")
    parser = PageParser()
    parser.feed(html)
    return html, parser


def referenced_site_assets(parser: PageParser) -> set[str]:
    styles = (SITE / "styles.css").read_text(encoding="utf-8")
    css_assets = set(re.findall(r"url\([\"']?([^\"')]+)", styles))
    return set(parser.images) | {asset for asset in css_assets if asset.startswith("assets/")}


class PagesSiteTests(unittest.TestCase):
    def test_pages_site_has_required_seo_metadata(self) -> None:
        _html, parser = parse_index()

        self.assertEqual(
            parser.title,
            "Humidity Intelligence | Humidity and Air Quality Control for Home Assistant",
        )
        self.assertEqual(parser.canonical, PAGES_URL)
        self.assertEqual(parser.meta.get("robots"), "index,follow")
        self.assertNotIn("noindex", " ".join(parser.meta.values()).lower())
        self.assertIn("Humidity Intelligence", parser.meta.get("description", ""))
        self.assertIn("Home Assistant", parser.meta.get("description", ""))

    def test_release_copy_preserves_established_product_hero(self) -> None:
        html, _parser = parse_index()
        hero = html.split('<section class="hero"', 1)[1].split("</section>", 1)[0]
        stability = html.split('id="stability"', 1)[1].split("</section>", 1)[0]
        self.assertIn('<h1 id="hero-title">Humidity Intelligence</h1>', hero)
        self.assertIn('class="hero-logo" src="assets/logo.png"', hero)
        self.assertNotIn('release_banner/', hero)
        self.assertIn('02 / The bigger picture', stability)
        self.assertIn('src="assets/release_banner/v2.1_release.png"', stability)
        self.assertIn('class="led-layer"', stability)
        self.assertIn('class="pause-motion"', stability)
        self.assertEqual(html.count('class="led-layer"'), 1)
        self.assertLess(html.index('<section class="hero"'), html.index('id="harmonization"'))
        self.assertLess(html.index('id="harmonization"'), html.index('id="stability"'))

    def test_pages_site_has_search_discovery_structured_data(self) -> None:
        _html, parser = parse_index()
        self.assertTrue(parser.structured_data)

        payload = json.loads("".join(parser.structured_data))
        graph = payload.get("@graph", [])
        graph_types = {entry.get("@type") for entry in graph}

        self.assertEqual(payload.get("@context"), "https://schema.org")
        self.assertIn("WebSite", graph_types)
        self.assertIn("SoftwareSourceCode", graph_types)
        self.assertIn(
            "https://github.com/senyo888/Humidity-Intelligence",
            json.dumps(payload),
        )
        self.assertIn(PAGES_URL, json.dumps(payload))

    def test_pages_site_routes_to_canonical_public_sources(self) -> None:
        html, parser = parse_index()
        required_targets = {
            "https://my.home-assistant.io/redirect/hacs_repository/?owner=senyo888&repository=humidity-intelligence&category=integration",
            "https://github.com/senyo888/Humidity-Intelligence#installation",
            "https://github.com/senyo888/Humidity-Intelligence/releases",
            "https://github.com/senyo888/Humidity-Intelligence/wiki",
            "https://github.com/senyo888/Humidity-Intelligence/wiki/UI-Gallery",
            "https://github.com/senyo888/Humidity-Intelligence/tree/main/ui-gallery",
            "https://github.com/sponsors/senyo888",
        }

        self.assertIn('id="support"', html)
        self.assertIn("Support Humidity Intelligence", html)
        self.assertTrue(required_targets.issubset(set(parser.links)))
        inspector_links = [link for link in parser.links if link == "inspector/"]
        self.assertEqual(len(inspector_links), 1)
        self.assertEqual(urljoin(PAGES_URL, inspector_links[0]), INSPECTOR_URL)

    def test_referenced_site_assets_are_public_and_copied_by_workflow(self) -> None:
        html, parser = parse_index()
        normalized_html = " ".join(html.split())
        workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        assets = referenced_site_assets(parser)

        self.assertIn("assets/logo.png", parser.images)
        self.assertIn("assets/site/github-pages-hero.png", assets)
        self.assertIn("assets/first-interaction-welcome.png", assets)
        self.assertIn("assets/release_banner/v2.1_release.png", parser.images)
        self.assertIn("Home Assistant 2026.11 Harmonization", html)
        self.assertIn("v2.1.2 · In preparation", html)
        # Preparation must not relabel the still-published stable release.
        self.assertIn("V2.1.1 · Stable", normalized_html)
        self.assertIn("V2.1.1 · 24 October 2026", normalized_html)
        self.assertIn("Stable version</span><span class=\"badge-value\">v2.1.1", html)
        self.assertIn("blob/senyo888-patch-1/docs/releases/v2.1.2.md", html)
        self.assertIn("releases/tag/v2.1.1", html)
        self.assertIn("release-packaging.md#earlier-versions-and-current-evidence-limits", html)
        self.assertNotIn("Install from GitHub", html)
        self.assertIn("Open legacy HACS", html)

        for asset in assets:
            with self.subTest(asset=asset):
                source_asset = ROOT / asset
                self.assertTrue(source_asset.exists(), f"{source_asset} is missing")
                self.assertIn(f"cp {asset}", workflow)

    def test_pages_workflow_builds_validated_inspector_at_public_route(self) -> None:
        workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        expected_files = {
            "app.mjs",
            "handoff.mjs",
            "index.html",
            "inspection-session.mjs",
            "parser.mjs",
            "styles.css",
        }

        self.assertIn(
            "python3 scripts/build_hi_inspector.py _site/inspector",
            workflow,
        )
        self.assertIn("branches: [main]", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        for job in ("build", "deploy"):
            with self.subTest(job=job):
                self.assertRegex(
                    workflow,
                    rf"(?m)^  {job}:\n"
                    r"    if: github\.ref == 'refs/heads/main'$",
                )
        self.assertIn('"scripts/build_hi_inspector.py"', workflow)
        self.assertEqual(
            {path.name for path in INSPECTOR_SOURCE.iterdir() if path.is_file()},
            expected_files,
        )

    def test_public_inspector_is_noindex_canonical_and_zero_network_egress(self) -> None:
        html, parser = parse_inspector()
        normalized = " ".join(html.split())
        robots = set(parser.meta.get("robots", "").split(","))
        csp = parser.meta.get("Content-Security-Policy", "")

        self.assertEqual(parser.canonical, INSPECTOR_URL)
        self.assertEqual(parser.images, ["../assets/logo.png"])
        self.assertEqual(
            urljoin(INSPECTOR_URL, parser.images[0]),
            f"{PAGES_URL}assets/logo.png",
        )
        self.assertEqual(
            robots,
            {"noindex", "nofollow", "noarchive", "nosnippet"},
        )
        for directive in (
            "default-src 'none'",
            "img-src 'self'",
            "connect-src 'none'",
            "worker-src 'none'",
            "form-action 'none'",
            "base-uri 'none'",
        ):
            self.assertIn(directive, csp)
        self.assertNotIn("img-src 'none'", csp)
        workflow = (ROOT / ".github/workflows/pages.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "cp assets/logo.png _site/assets/logo.png",
            workflow,
        )
        self.assertIn(
            "Diagnostic contents remain in this browser tab.",
            normalized,
        )
        self.assertIn(
            "selected file contents remain in this tab",
            normalized,
        )
        self.assertIn(
            "Native Home Assistant diagnostics remain the preferred support",
            normalized,
        )

    def test_public_inspector_and_triage_share_one_version_contract(self) -> None:
        html = (INSPECTOR_SOURCE / "index.html").read_text(encoding="utf-8")
        handoff = (INSPECTOR_SOURCE / "handoff.mjs").read_text(encoding="utf-8")
        triage = (ROOT / "scripts" / "issue_triage.py").read_text(encoding="utf-8")

        html_version = re.search(
            r"Inspector version\s*<strong>([^<]+)</strong>",
            html,
        )
        handoff_version = re.search(
            r'export const INSPECTOR_VERSION = "([^"]+)";',
            handoff,
        )
        triage_version = re.search(
            r'HANDOFF_INSPECTOR_VERSION = "([^"]+)"',
            triage,
        )
        self.assertIsNotNone(html_version)
        self.assertIsNotNone(handoff_version)
        self.assertIsNotNone(triage_version)
        self.assertEqual(
            {
                html_version.group(1),
                handoff_version.group(1),
                triage_version.group(1),
            },
            {"0.3.0-beta.1"},
        )

    def test_sitemap_and_robots_allow_indexing_the_project_site(self) -> None:
        robots = (SITE / "robots.txt").read_text(encoding="utf-8")
        sitemap = SITE / "sitemap.xml"
        root = ET.parse(sitemap).getroot()
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [node.text for node in root.findall("sm:url/sm:loc", namespace)]

        self.assertIn("Allow: /", robots)
        self.assertIn(f"Sitemap: {PAGES_URL}sitemap.xml", robots)
        guide_urls = {
            urljoin(PAGES_URL, path.parent.relative_to(SITE).as_posix() + "/")
            for path in (SITE / "guides").glob("*/index.html")
        }
        self.assertEqual(len(guide_urls), 3)
        self.assertEqual(set(locs), {PAGES_URL} | guide_urls)
        self.assertEqual(len(locs), len(set(locs)))
        self.assertNotIn(INSPECTOR_URL, locs)

    def test_guides_have_unique_metadata_and_crawlable_home_links(self) -> None:
        _html, home = parse_index()
        titles = {home.title}
        descriptions = {home.meta["description"]}
        for path in sorted((SITE / "guides").glob("*/index.html")):
            with self.subTest(page=path.parent.name):
                html = path.read_text(encoding="utf-8")
                parser = PageParser()
                parser.feed(html)
                route = path.parent.relative_to(SITE).as_posix() + "/"
                canonical = urljoin(PAGES_URL, route)
                self.assertIn(route, home.links)
                self.assertEqual(parser.canonical, canonical)
                self.assertEqual(parser.meta["og:url"], canonical)
                self.assertEqual(parser.meta["robots"], "index,follow")
                self.assertEqual(parser.meta["og:title"], parser.title)
                self.assertEqual(parser.meta["twitter:title"], parser.title)
                self.assertEqual(parser.meta["og:description"], parser.meta["description"])
                self.assertEqual(parser.meta["twitter:description"], parser.meta["description"])
                self.assertNotIn(parser.title, titles)
                self.assertNotIn(parser.meta["description"], descriptions)
                titles.add(parser.title)
                descriptions.add(parser.meta["description"])
                data = json.loads("".join(parser.structured_data))
                self.assertEqual(data["@type"], "WebPage")
                self.assertEqual(data["url"], canonical)
                self.assertEqual(data["isPartOf"]["url"], PAGES_URL)
                self.assertEqual(len(re.findall(r"<h1(?:\s|>)", html)), 1)
                self.assertEqual(len(parser.ids), len(set(parser.ids)))
                self.assertIn("../../#start", parser.links)
                self.assertTrue(any("/wiki/" in link for link in parser.links))
                # Discovery pages have no executable script or remote widget.
                self.assertEqual(html.count("<script"), 1)

    def test_built_guides_resolve_links_fragments_and_shared_assets(self) -> None:
        workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temp:
            artifact = (pathlib.Path(temp) / "_site").resolve()
            artifact.mkdir()
            # Exercise the workflow's real static-copy commands, including recursive
            # guide copying, with a temporary destination outside the checkout.
            for line in workflow.splitlines():
                command = line.strip()
                if not command.startswith("cp "):
                    continue
                args = shlex.split(command)
                destination = pathlib.Path(temp) / args[-1]
                destination.parent.mkdir(parents=True, exist_ok=True)
                args[-1] = str(destination) + ("/" if command.endswith("/") else "")
                subprocess.run(args, cwd=ROOT, check=True, capture_output=True)
            pages = sorted((artifact / "guides").glob("*/index.html"))
            self.assertEqual(len(pages), 3)
            for path in pages:
                parser = PageParser()
                parser.feed(path.read_text(encoding="utf-8"))
                for target in parser.links + parser.images + parser.resources:
                    url = urlsplit(target)
                    if url.scheme or url.netloc:
                        continue
                    with self.subTest(page=path.parent.name, target=target):
                        resolved = (path.parent / unquote(url.path)).resolve()
                        self.assertTrue(resolved.is_relative_to(artifact))
                        if resolved.is_dir():
                            resolved /= "index.html"
                        self.assertTrue(resolved.is_file(), f"Broken built link: {target}")
                        if url.fragment:
                            linked = PageParser()
                            linked.feed(resolved.read_text(encoding="utf-8"))
                            self.assertIn(unquote(url.fragment), linked.ids)

    def test_public_support_docs_record_gate3_status_and_route(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        support = (ROOT / "docs/support.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        normalized_changelog = " ".join(changelog.split())

        for source in (readme, support):
            self.assertIn(INSPECTOR_URL, source)
            self.assertIn("native", source.lower())
            self.assertIn("preferred", source.lower())
        self.assertIn("Wiki update status: `updated`", normalized_changelog)
        self.assertIn(
            "Services Reference now documents the final external service permission boundaries.",
            normalized_changelog,
        )
        self.assertIn("Release-documentation status:", normalized_changelog)
        self.assertIn("`updated` by this entry", normalized_changelog)

    def test_pages_public_copy_has_no_private_or_overclaiming_terms(self) -> None:
        site_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(SITE.rglob("*"))
            if path.is_file() and path.suffix in {".html", ".css", ".txt", ".xml"}
        )
        private_patterns = (
            "/Users" + "/",
            "." + "codex",
            "HA" + " Lab",
            "ha-" + "lab",
        )
        risky_claims = {
            "latest",
            "guaranteed",
            "medical",
            "healthy",
            "healthier",
            "certified",
            "alarm",
            "official Home Assistant",
            "prevent",
            "prevention",
        }

        for pattern in private_patterns:
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, site_text)

        # Permit publication-record navigation, not a claim that the source is latest.
        lower_site_text = site_text.lower().replace(
            "github releases records the latest published stable", "publication record"
        ).replace("humidity intelligence latest published release", "publication link").replace(
            '<span class="badge-value">latest</span>', '<span class="badge-value">release</span>'
        )
        for claim in risky_claims:
            with self.subTest(claim=claim):
                self.assertIsNone(re.search(rf"\b{re.escape(claim.lower())}\b", lower_site_text))


if __name__ == "__main__":
    unittest.main()
