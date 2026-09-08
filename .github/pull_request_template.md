## Summary

<!-- What changed and why? -->

## Scope

<!-- Files/areas affected. Keep the scope small and explicit. -->

## Reason

<!-- Why this change is needed now. -->

## Files affected

<!-- List the main files or folders touched. -->

## Runtime impact

<!-- State whether lane ordering, entity semantics, services, outputs, diagnostics, or migrations changed. -->

## UI impact

<!-- State whether generated dashboards, cards, gallery examples, or frontend dependency assumptions changed. -->

## Migration impact

<!-- State whether users need to take action. If none, say "None". -->

## Rollback safety

<!-- State how this can be reverted safely if it regresses. -->

## Validation performed

<!-- Commands, Home Assistant checks, generated-card checks, or docs checks run. -->

## HA Lab advisory evidence

<!-- Optional and non-blocking. If useful, state HA Lab status as pass / fail / blocked / incomplete / not run / not applicable and include only sanitized evidence. No HA Lab status is a PR, promotion, tag, HACS, or release gate. -->

## Maintainer notes

<!-- Reserved for the maintainer's manual notes. -->

## Checks

- [ ] PR targets `develop`.
- [ ] Tested in Home Assistant, or testing notes explain why not.
- [ ] Restart/config flow checked where relevant.
- [ ] Ran `humidity_intelligence.refresh_ui` or refreshed dashboards where UI output changed.
- [ ] Docs/changelog updated where needed.
- [ ] Support docs, diagnostics guidance, and issue templates updated where support flow changed.
- [ ] Native diagnostics schema/redaction and aggregate mapped-entity privacy are unchanged or the approved contract change is explicit and tested.
- [ ] `v205_release_check` compatibility, result wording, packaged service description, README, Wiki, and range tests agree where release support changed.
- [ ] Wiki update status recorded as `updated`, `no-op`, or `blocked` where public support/manual guidance is affected.
- [ ] No private entity IDs, secrets, addresses, or personal data included.
- [ ] HACS default-list status, My Home Assistant link, package layout, and custom-integration metadata still look correct.
- [ ] Deterministic lane ordering is preserved, or the PR explicitly explains an approved semantic change.
- [ ] UI truth consistency is preserved; generated UI stays anchored to backend state.
- [ ] Migration impact is documented, using "none" where appropriate.
- [ ] Release/readiness impact is stated, including whether Bella/Aetherwing/AetherCore review is needed.

## UI Gallery submissions

- [ ] Uses `/ui-gallery/<card-id>/`.
- [ ] Includes `README.md`, `preview.png`, and `card.yaml` or `dashboard.yaml`.
- [ ] Top-level `ui-gallery/README.md` is updated.
- [ ] Example follows `ui-gallery/reference.txt` format.
- [ ] Required custom cards are documented.
- [ ] Preserves canonical Humidity Intelligence backend entities/helpers.
- [ ] Screenshots and YAML contain no private entity IDs, secrets, addresses, device IDs, tokens, internal URLs, or personal data.

## Maintainer summary

<!-- Final maintainer-facing decision, residual risks, and release/deploy gates. -->
