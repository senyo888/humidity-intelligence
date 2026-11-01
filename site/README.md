# Humidity Intelligence website

The landing page mirrors tracked product and release claims; the repository and
Wiki own setup, compatibility and operational detail. V2.1.1 Stable is the featured
release, with its approved artwork, single-level/dashboard fixes, update-status
explanation and upgrade guidance. The existing animated V2.1 Stability Score hero
remains the product overview; its illustration does not represent live telemetry.

The website presents v2.1.1, published on 24 October 2026. Its release-note
links point to the canonical notes on main and the published GitHub Release. Users must check the version offered in HACS
and the loaded Home Assistant identity separately. The main-only Pages workflow
copies both V2.1 and v2.1.1 artwork into the static artifact.

The page uses static HTML and CSS, system fonts, locally packaged images and
native disclosures. It requires no JavaScript, third-party widget, analytics or
new plugin. The separate Inspector is built through its existing validated script.

The selected V2.1 header uses a CSS/SVG decorative light sequence: top, right,
left; one step every three seconds. It reads no Home Assistant data. The pause
checkbox shows the still artwork, and `prefers-reduced-motion: reduce` disables
the sequence and hides the unnecessary pause control. All essential content and
navigation remain available without motion.

Assets and third-party logo attribution are documented in
[assets/site/README.md](../assets/site/README.md). The real Stability screenshot
retains its incomplete-monitoring warning. Earlier gallery screenshots retain
adjacent target/layout qualifications.

Before publishing a website update, run the Pages, workflow, banner and version checks; build
Inspector and every referenced asset with `.github/workflows/pages.yml`; check
390/820/1440px layouts, keyboard disclosures/pause, reduced motion, local links
and the three animation phases. The maintainer selected the V2.1 artwork on
10 October 2026. Earlier HI Stable acceptance, including the seven-day drift history
advisory, belongs to each previously tested package. Current v2.1.1 source and
publication records do not establish an individual Home Assistant installation or
a completed soak; earlier beta/RC evidence keeps its original package identity.


## Discovery guides

The homepage uses the positioning “Humidity and Air Quality Control for Home
Assistant”. Page titles, descriptions and social previews describe the same scope;
the approved visual headline and release presentation remain intact.

Three static guides under `site/guides/` explain coordinated control, condensation
and mould-risk context, and Stability Score. They are introductory explanations
of tracked product behaviour, with descriptive links to the detailed Wiki and
repository contracts. Keep those sources authoritative when updating a guide.
Each guide has its own canonical URL and metadata, shares the site's navigation,
styles and footer, and appears in `sitemap.xml`. The existing Pages workflow copies
that directory without a new build dependency. Inspector remains excluded from
indexing and the sitemap.

Validate the built artifact, including nested guide links, fragments, shared assets,
unique metadata and sitemap coverage. Check all guide routes at phone, tablet and
desktop widths and follow their navigation with a keyboard. No analytics, search
ranking promise, external widget or version bump accompanies these pages.
