![Humidity Intelligence agent header](assets/agent-banner.png)

# Humidity Intelligence Agent Guide

This is the public, repository-safe operating guide for AI agents working on Humidity Intelligence. It is intentionally concise and complements the tracked public architecture contract.

## Project Identity

Humidity Intelligence is a deterministic Home Assistant environmental control engine packaged as a HACS custom integration. It performs runtime-driven environmental orchestration, resolves one control decision per cycle, and exports truth-based Manual-card YAML from backend telemetry, mappings, and diagnostics.

## Source of Truth

- Public repo correctness must be reviewable from tracked files in this repository.
- `ARCHITECTURE.md`, `AGENTS.md`, `README.md`, `CHANGELOG.md`, tracked docs, runtime code, tests, generated UI templates, and `ui-gallery/` are the public review contract.
- Maintainers may keep `DESIGN_BRIEF.md`, `PROJECT_SUMMARY.md`, `ROADMAP.md`, and `PROPOSALS.md` as ignored local planning or release-preparation documents.
- If architecture, runtime behavior, security posture, release flow, contributor expectations, or documentation expectations materially change, update the relevant tracked public docs in the same work.
- Ignored local docs may be mirrored separately, but must not be required for public contributor correctness.
- Maintainers may keep local-only instructions in `AGENTS.local.md`. That file is intentionally ignored and must not be required for public contributors or public repo correctness.

## Repository Workspace Boundary

- Release truth must come from a git-managed Humidity Intelligence checkout or a worktree created from that checkout.
- Unmanaged mirror folders, scratch folders, and local planning surfaces are not release authority.
- Local-only planning, lab, credential, generated-export, and agent-private files must remain ignored unless publication is explicitly approved.
- Do not require machine-specific local paths for public repo correctness, validation instructions, release notes, issue templates, or PR descriptions.

## Codex Pet Memory Architecture

- Codex pet memory is a first-class subsystem under `.codex/memories/`.
- Canonical pet memory paths use the placeholder pattern `.codex/memories/pets/<PetName>/`.
- Shared project memory belongs under `.codex/memories/project/`; shared terminology belongs under `.codex/memories/shared/`.
- Pet identity pointers may exist under `.codex/pets_pointer/`. `.codex/pets/` is historical or possible app identity space only; pet memory, history, canon, and reporting rules must not be stored there.
- Repository memory must stay public-safe: no secrets, credentials, private entity IDs, private MCP configuration, or machine-specific local paths.

## Non-Negotiable Architecture Rules

- Preserve the integration name, domain, HACS identity, and public package positioning unless explicitly instructed otherwise.
- Keep deterministic control authoritative: one selected ventilation lane per evaluation cycle.
- Keep humidity targets season-aware and profile-relative.
- Keep generated dashboards and reason panels aligned with backend truth only.
- Do not add hidden automations, hidden service paths, or parallel output writers.
- Optional frontend cards and UI dependencies must never block backend functionality.
- Unknown, unavailable, incomplete, or unmapped inputs must degrade safely and explainably.

## Deterministic Runtime Rules

- Preserve lane priority: CO emergency, humidity danger, mould danger, mould risk, condensation danger, condensation risk, zone 1, zone 2, AQ, normal.
- CO emergency is always the highest-priority runtime lane.
- Humidity, mould, and condensation alerts must resolve source, room, and zone before applying zone-bound control.
- Humidity danger thresholds are derived from the active target profile, not legacy static alert values.
- Humidifier lanes remain independent from ventilation lane resolution.
- Global gates must be respected and surfaced truthfully in runtime telemetry and UI.
- Missing outputs or failed optional service calls must be logged, skipped, and exposed without crashing the control loop.

## UI/Card Generation Rules

- Do not invent placeholder entities.
- Do not use private entity IDs, device IDs, room names, telemetry values, or user-specific helpers in published cards, tests, docs, screenshots, or examples.
- Do not ship malformed Lovelace structures, empty card containers, invalid conditionals, or unresolved self-mapped placeholders.
- Dashboard chips must map to backend telemetry, entity mapping, diagnostics, or runtime truth.
- Current Air Control chips are display surfaces only. They must not create or alter lane decisions.
- Alert chipsets should stay concise: active lane/status plus resolved source context.
- Optional chip rows and optional frontend dependencies must hide or degrade cleanly when unavailable.
- After UI template, mapping, chip, or card-generation changes, validate exported/generated cards before completion.

## Home Assistant and HACS Compatibility Rules

- Keep config flow, options flow, entity registry behavior, services, translations, diagnostics, and generated files compatible with supported Home Assistant versions.
- Avoid blocking filesystem, network, or slow I/O work in async Home Assistant paths.
- Keep service schemas explicit and error messages actionable.
- Keep `hacs.json` limited to HACS-supported keys.
- Keep integration metadata in `manifest.json`.
- Keep branding assets, README expectations, HACS metadata, and release notes aligned with the actual package layout.
- Do not add hard dependencies on optional frontend cards.

## Validation Expectations

- Run validation appropriate to the changed scope.
- For runtime changes, include Python compile/import sanity and targeted regression tests where available.
- For card/UI changes, validate generated Lovelace output and check for stale mappings, private entities, malformed structures, and frontend dependency assumptions.
- For docs-only changes, perform a documentation sanity pass: check filenames, source-of-truth references, public-safety, and consistency with current repository structure.
- Review for stale imports, stale mappings, stale docs, outdated service names, and drift from `ARCHITECTURE.md` plus other tracked public docs.
- Do not claim validation was completed if it was not run.

## HA Lab Operational Validation Boundary

- HA Lab may be used as Operational Beta Validation Infrastructure for beta deploys, post-deploy read-only checks, diagnostics review, and generated-card/entity-map sanity evidence.
- HA Lab evidence is advisory process evidence only. It is not release authority, runtime authority, stable Home Assistant authority, or a substitute for Bella, Aetherwing, AetherCore, and maintainer gates.
- HA Lab evidence is optional and non-blocking. A pass, failure, blocked run, incomplete
  playback matrix, missing soak, or absence of HA Lab evidence may inform risk notes,
  but must never be treated as a promotion, merge, tag, GitHub Release, HACS
  publication, or Stable-release gate.
- HA Lab work must preserve source identity, exact version, target boundary, mutation classification, rollback evidence, and public/private documentation separation.
- HA Lab validation must not authorize autonomous Home Assistant mutation, restarts, reloads, helper changes, dashboard mutation, output writes, stable runtime access, tags, releases, or PR merges.
- Public docs and PRs may summarize HA Lab status in sanitized terms, but local reports, credentials, target URLs, private entity IDs, and machine-specific details must remain local-only.

## Documentation and Release Expectations

- Keep `README.md`, `manifest.json`, `hacs.json`, docs, release notes, UI examples, and runtime behavior aligned.
- Keep the current candidate, current Stable release, and immediately preceding Stable release summaries expanded in the README `Release Notes` section. When a newer release displaces one of those three positions, move the older summary into the collapsible `Previous Releases` container; retain that container as the canonical older-release structure. `CHANGELOG.md` remains the complete detailed release and legacy-migration history.
- Keep the Wiki UI Gallery as a browseable mirror/index only; repository `ui-gallery/` remains canonical for reviewed YAML, preview assets, and contribution rules.
- Update related docs when implementation behavior changes.
- Treat completed milestones as completed. Do not leave shipped v2.0.5 functionality in planned, pending, or proposal-only roadmap buckets.
- Keep branch/version state explicit: `senyo888-patch-1` may carry beta, rc, or stable labels; `develop` may carry rc or stable labels; `main` carries stable releases only.
- Run the version-governance check before release promotion so unstable builds cannot be promoted as stable by accident.
- Treat release tagging as blocked until Bella verification, AetherCore governance verification, release sanity validation, and maintainer README approval are complete.
- Preserve backwards compatibility where practical. If compatibility breaks, call it out explicitly and document the migration path.
- Keep release notes factual, version-aligned, and free of private local details.
- Report changed files and validation results at the end of the work.

## Safety and Privacy Rules

- Never expose secrets, tokens, credentials, addresses, private telemetry, private entity IDs, device IDs, usernames, machine names, or local absolute paths.
- Do not run destructive actions unless explicitly requested.
- Do not delete user files, generated outputs, dashboards, helpers, or repository metadata without clear authorization.
- Public examples must use canonical HI entities or sanitized placeholders only.
- Do not publish local-only planning notes unless explicitly approved.

## What Agents Must NOT Do

- Do not rename the integration.
- Do not bypass deterministic architecture.
- Do not invent entities, services, sensors, helpers, features, workflows, or commands.
- Do not weaken runtime truth principles.
- Do not silently remove backward compatibility.
- Do not introduce private entities into public docs, cards, screenshots, examples, release notes, or tests.
- Do not mark work complete without appropriate validation.
- Do not duplicate the design brief here or let this file become bloated documentation.
