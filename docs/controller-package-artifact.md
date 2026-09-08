# Deterministic controller package artifact

Humidity Intelligence publishes one short-lived, branch-bound package artifact for
external validation by the separately governed HI Lab Controller. This is an optional
distribution evidence lane. It is not a Home Assistant runtime dependency, HACS
release, GitHub Release asset, deployment instruction, rollback source, or release
approval.

## Fixed provider contract

- Workflow: `.github/workflows/controller-package.yml`
- Source branch: `senyo888-patch-1` only
- Artifact name: `humidity-intelligence-controller-package`
- Retention: seven days
- Source profile: `public_patch_1`
- Package contract: `hi-package-public-v20-conventional-1`
- Provenance subject: the strict `artifact-manifest.json` produced from the exact
  workflow commit

The workflow runs after relevant package, builder, test, or workflow changes on Patch
1. It cannot run as this provider on `develop`, `main`, a tag, a pull-request merge
ref, or another repository.

## Artifact contents

The GitHub Actions artifact contains exactly:

```text
artifact-manifest.json
humidity_intelligence/<tracked installable component files>
```

The builder reads Git blobs from the exact immutable commit rather than mutable
working-tree bytes. The manifest binds the commit, full repository tree, integration
version, package-contract identity, ordered file paths, Git blob identities, SHA-256
digests, sizes, executable flags, and the deterministic aggregate package hash.

Repository documentation, tests, scripts, workflows, site content, UI Gallery
material, ignored/local credentials, runtime data, caches, and private evidence are
outside the selected tracked component. Before upload, the workflow runs the
repository's redacted tracked-file Gitleaks scan as well as the package regression
contract. Any unclassified runtime-looking path, executable component file, unsafe
Git object, missing required path, invalid manifest, path collision, forbidden
filename, high-confidence private-key marker, or size overflow fails the build closed.
These controls are safeguards, not permission to store secrets in tracked component
files.

## Local reproduction

Run from a clean Git-managed checkout or worktree:

```bash
artifact_dir="$(mktemp -d)/controller-package"
python3 scripts/build_controller_package.py \
  --repository . \
  --commit HEAD \
  --output "$artifact_dir"
```

The command creates local files only and prints a public-safe JSON summary. Repeating
it for the same commit in a different empty output directory must produce byte-for-byte
identical files and the same manifest and package hashes.

## Lifecycle and rollback boundary

An uploaded artifact proves only that the workflow produced retained candidate bytes
for one exact commit. Artifact availability, successful provenance attestation,
download, controller quarantine, `VERIFIED_CANDIDATE`, Stage A preparation, Home
Assistant restart, deployment verification, observation, baseline acceptance, tag,
GitHub Release, HACS availability, and Stable promotion remain separate facts and
decisions.

The mutable Patch 1 branch is not a rollback store. If a separately authorized
controller deployment occurs later, rollback remains bound to the exact verified
predecessor retained by that deployment. Artifact expiry after seven days is expected
and does not remove or rewrite Git history or any published release.
