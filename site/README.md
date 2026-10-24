# Humidity Intelligence website

The landing page mirrors tracked product and release claims; the repository and
Wiki own setup, compatibility and operational detail. [V2.1.0 is published Stable](https://github.com/senyo888/humidity-intelligence/releases/tag/v2.1.0),
released on 12 October 2026. The installation path points to HACS; users should check
the offered version and refresh repository information if an older version is shown.

The preparation note identifies **v2.1.1 Stable source as not yet published** and
links to release notes for single-level exports, update-status and report changes.
The final metadata retains the reviewed RC runtime and revision-13 cards.
V2.1.0 remains the Stable installation target and published release artwork.
Updating this source on the preparation branch does not deploy the website;
the existing Pages workflow publishes it when an approved change reaches `main`.

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
advisory, belongs to the previously tested package. Installed v2.1.0-rc.1 validation remains
bound to that exact package. Published v2.1.0 preserves its runtime and generated-card
bytes, with a distinct final package identity. Release publication does not establish
an individual Home Assistant installation or a completed soak.
