# Humidity Intelligence website

The landing page mirrors tracked product and release claims; the repository and
Wiki own setup, compatibility and operational detail. V2.1 remains a candidate
preview while the Stable installation path points to v2.0.12.

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

Before publication, run the Pages, workflow, banner and version checks; build
Inspector and every referenced asset with `.github/workflows/pages.yml`; check
390/820/1440px layouts, keyboard disclosures/pause, reduced motion, local links
and the three animation phases. The maintainer selected the V2.1 artwork on
10 October 2026. RC.1 source preparation is approved; final release checks and
the develop PR await explicit HA Stable acceptance. Website publication remains
a separate action.
