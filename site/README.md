# Humidity Intelligence website

The landing page mirrors tracked product and release claims; the repository and
Wiki own setup, compatibility and operational detail. V2.1.2 has a text section directly below the established hero, **Home Assistant 2026.11 Harmonization**, with Marketplace delivery,
air-quality units, update status and revision-15 card upgrade guidance. Published
Stable remains v2.1.1 during preparation; update that status only after publication.

The established V2.1 hero title, artwork, LED overlay and pause control are
preserved. Release emphasis does not authorize replacing the hero. Its illustration
is not live telemetry; the Stability Score explanation remains in its own section. A compact linked history connects 2.1.0, 2.1.1 and
2.1.2 without repeating their detailed notes. Credits in the release block thank
the #145 reporters without implying they tested the fix.

The main-only Pages workflow includes the V2.1, v2.1.1 and v2.1.2 artwork.
The release block distinguishes the earlier Stable-instance test from refreshed
validation of the revision-15 package, retaining v2.1.1 as Published Stable.
Installer coverage stays in the release notes.
Prepared-release links point to the canonical `senyo888-patch-1` records so review
links resolve before promotion. At publication, switch preparation status and links
to the verified immutable release. Users check the offered Marketplace/HACS version
and loaded Home Assistant identity separately.

The page uses static HTML and CSS, system fonts, locally packaged images and
native disclosures. It requires no JavaScript, third-party widget, analytics or
new plugin. The separate Inspector is built through its existing validated script.

The retained V2.1 illustration uses a CSS/SVG decorative light sequence: top, right,
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
advisory, belongs to each previously tested package. Current release source and
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
