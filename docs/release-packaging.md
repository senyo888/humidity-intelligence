# Release ZIP packaging

The `2.1.2` stable source retains the release delivery introduced in beta.1: the named
`humidity_intelligence.zip` asset. Published Stable remains `v2.1.1` until a new
Stable release is approved and published. Select the beta explicitly for testing;
source preparation and CI artifacts do not make an installable release available.

## Why the delivery changes

[Issue #145](https://github.com/senyo888/humidity-intelligence/issues/145) reports a
Marketplace install failure on Home Assistant 2026.11. The `v2.1.1` source ZIP
measured 107,908,863 transferred bytes and 113,472,636 expanded bytes, above
Marketplace's 104,857,600-byte limit. Its integration manifest is present. A
suppressed tag-download failure can lead to a misleading branch 404 and the
[upstream fallback-path defect](https://github.com/home-assistant/core/issues/190922).
The HI packaging change avoids the oversized download; it does not repair Core.

The repository keeps its conventional `custom_components/humidity_intelligence/`
layout and complete source archives. The install asset contains only that
directory's committed files, with `manifest.json` directly at the ZIP root. HACS
and Marketplace extract those files into `custom_components/humidity_intelligence/`.
Repository artwork, docs, tests, legacy material and local files are excluded from
the install asset. Component branding, translations, helpers and UI files remain.

`hacs.json` declares `zip_release: true`, `filename: humidity_intelligence.zip`,
and `hide_default_branch: true`. The default-branch choice is deliberately hidden:
branches have no matching release asset. Tagged releases and published prereleases
remain the managed installation route; a branch or unpublished candidate can still
be installed manually from its complete component directory. Do not treat a branch
as equivalent to a published Stable release.

## Build and check

`scripts/build_release_zip.py` resolves one Git commit before reading its tracked
component blobs. Dirty working files and untracked copies cannot enter the ZIP.
It rejects missing required files, links, unsafe or ambiguous names, wrong metadata
and oversized packages. Both ZIP and expanded content must fit a 16 MiB budget,
leaving headroom below Marketplace's 100 MiB limit. Fixed timestamps, sorted names,
regular-file permissions and uncompressed ZIP entries make output reproducible
without depending on a compression-library version. The current component is about
2.3 MiB. This is an install ZIP, not an enclosing directory or the GitHub source ZIP.

For a reviewed, committed candidate:

```sh
source_commit=$(git rev-parse HEAD)
artifact_dir=$(mktemp -d)
python3 scripts/build_release_zip.py --commit "$source_commit" --output "$artifact_dir"
python3 scripts/build_release_zip.py --commit "$source_commit" \
  --verify "$artifact_dir/humidity_intelligence.zip"
```

The summary records commit, version, file count, transferred/expanded sizes and
SHA-256. Verification compares every file and byte with that commit and rejects
missing, changed, extra, duplicate, nested or unreadable entries. Outputs are never
overwritten. CI runs failure tests, builds twice, compares results, verifies the
archive, and retains a short-lived review artifact. The outer Actions download ZIP
is a transport wrapper; only its inner `humidity_intelligence.zip` is the install
asset. CI has read-only repository permissions and does not publish releases.

## Publication and rollback

Follow the existing [release gates](release-governance.md#hard-release-gates).
After the final source/version and tag are approved, build from that exact commit
using `--tag vVERSION` as well as `--commit COMMIT`; the tag, commit and manifest
version must agree. An earlier beta or PR-merge artifact cannot establish parity
with a different release commit.

Prepare the GitHub Release as a draft. Attach the verified file under its exact
`humidity_intelligence.zip` name, then download that asset into a fresh directory
and run the verifier against the same commit and tag. Record its digest and the
verification result before publishing the draft. A missing or mismatched asset
means the release is not ready. Do not publish first and add the asset later.
Do not overwrite a published asset or move an existing tag; corrections use a new
version. The controller-package workflow remains a separate validation lane.

Validate a fresh Marketplace install, an upgrade, selected-version behavior and
the supported legacy HACS route with the actual artifact. Check that the final
manifest is directly inside the HI component directory. A source-derived harness
or ZIP extraction check is not evidence of a completed Home Assistant install.
Download/corrupt-asset failures must remain visible and preserve an existing
installation; retain the previous complete package for rollback.

ZIP delivery alone needs no configuration migration. The broader candidate also
changes unit handling and advances V2 cards to revision 16; follow the
[compatibility and saved-card instructions](home-assistant-2026.11.md). A package update requires a full Home Assistant restart
when installed; restart resets in-memory Stability history. Preserve rollback
copies outside `custom_components`, retain compatible saved cards, and verify the
loaded integration version after startup. Do not delete configured entities or
setups to recover from a download failure.

## Earlier versions and current evidence limits

The existing `v2.1.1` tag and release are unchanged. Marketplace reads the selected
version's metadata; older versions retain their source-archive delivery. Their
oversized archive and the upstream fallback defect remain independent problems.

Legacy HACS 2.0.5 has an additional first-install edge: with cached latest metadata
and an unchanged GitHub ETag, selecting an older release can retain the new ZIP
settings and request an asset that the older release never supplied. Source-derived
checks reproduced that case. Installed-version selection refreshes the metadata
in the checked path. Do not promise seamless older-version first installs across
all HACS versions. Use the complete component directory from the exact older tag
for a manual install if affected; preserve existing configuration and backups.
Backfilling old release assets or changing upstream installers is separate work.

The initial investigation checked archive bytes, download-size rejection and the
fallback destination using isolated upstream methods. It did not install HI on a
reporter's system.

The published `v2.1.2-beta.1` asset subsequently passed native Marketplace fresh
installation and upgrade from a manually installed v2.1.1 baseline on HA 2026.11.0.
Both installed packages matched all 78 released files; loaded-code identity and
configuration restoration were verified. This does not establish a legacy HACS
install or automatic update notification from a Marketplace-managed baseline.
See the [dated validation record](releases/v2.1.2-beta.1.md#validation-and-limits).

An earlier stable candidate (`2e2792ad`, revision 14) passed a manual Stable-instance upgrade on
Home Assistant 2026.11.0, with package parity, loaded identity and preserved
configuration verified after one restart. The subsequent revision-16 generator
correction changes the package. The `0d99f598` bytes passed fresh minimal-instance
validation and Stable acceptance on HA 2026.11.0, with 13 passes, 3 explained
warnings and no failures. All 78 files matched; five exports and live revision 16
were verified, with configuration, registry and saved-dashboard preservation.
The subsequent CO-unit Repairs and calculated-slope follow-up changes component
bytes without changing UI revision 16. The earlier `cc709769` package, including
Marketplace setup guidance, passed its own Stable acceptance: all 79 files matched,
13 checks passed with 3 explained warnings and no failures, and both saved V2 cards
were verified at revision 16 in browser checks. These results do not establish
public Marketplace selection of a final stable release.
The four PR #147 corrections change that package again. The corrected `d6174038`
package has its own immutable ZIP identity and completed Lab and Stable-instance
acceptance on 8 November 2026. All 79 files matched; Stable recorded 13 passes,
3 explained warnings and no failures. The Lab route was isolated native setup,
not Marketplace delivery. `cc709769` results retain their earlier package scope.
The subsequent PR #148 flash-restoration correction changes component bytes again;
its package needs its own identity and appropriate acceptance. The `d6174038` live
results do not cover the newer package or interrupted-flash restoration.
The [route-by-route validation record](releases/v2.1.2.md#validation-and-publication-status)
keeps final-tag/draft-asset verification, post-publication Marketplace acceptance
and legacy HACS results distinct. HACS 2.0.5 on HA 2026.10.1 subsequently installed
the published beta from a fresh package state and replaced a manually loaded
v2.1.1 package through a real HACS re-download. Both matched the beta asset;
configuration and entity identities were preserved. A subsequent manual bridge
loaded the earlier revision-14 candidate ZIP. This does not prove published stable HACS delivery,
managed-baseline update notification or the older-version cached-metadata edge.
The minimal fixture exposed an optional-reference generated-card defect, corrected
in the revision-16 source. Its new package validation remains distinct from these
earlier installer passes.
Retain the actual-installer requirement above; metadata checks and source
harnesses cannot fill an untested route.
