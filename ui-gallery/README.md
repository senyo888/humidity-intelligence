![Humidity Intelligence UI Gallery banner](../assets/header.png)

# Humidity Intelligence UI Gallery

Reusable Lovelace examples built on the Humidity Intelligence V2 generated card templates.

These examples are public documentation artifacts. They should demonstrate safe, canonical UI patterns without exposing private Home Assistant entity IDs, addresses, screenshots, or personal data.

The V2 example YAML follows the backend-owned `hi.reason.v1` reason contract and the
humidifier demand/output truth contract. The reason panel renders the escaped backend
headline and ordered line text without card-authored `Stage:` or `Engine:` prose.
Requested, On, Idle, Isolated, Retrying, Stopping, Unknown, Degraded, and Fault
remain separate presentation states. `On` is concise card wording for backend
`output_on`, and the examples do not infer physical moisture production from a
generic output `on` state. The canonical YAML uses the same plain-language backend
reason authority across AQ and Zone examples. See the
[UI guide](../custom_components/humidity_intelligence/ui/README.md) for current card
behavior, compatibility and refresh instructions.

The browseable UI Gallery lives in the GitHub Wiki:

- [UI Gallery](https://github.com/senyo888/humidity-intelligence/wiki/UI-Gallery)

This repository directory remains the canonical source for gallery YAML, preview assets, example notes, and contribution review. The Wiki is a visual navigation layer only; it must not define new entity semantics, backend behavior, lane priority, generated-card logic, or install guidance that differs from the repository.

## Available Layouts

### Default V2 Mobile AQ

- Style: mobile-first V2 control surface with air-quality lane active state
- Optimised for: phones and narrow dashboard panels
- Author: @senyo888
- Source template: `custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml`
- Required custom cards: `card-mod`, `button-card`, `mod-card`, `apexcharts-card`

[![Air-quality response](../assets/ui/v2.1/air-quality-response.png)](../assets/ui/v2.1/air-quality-response.png)

- [View air-quality response](../assets/ui/v2.1/air-quality-response.png)
- [Historical Mobile layout preview](default-v2-mobile-aq/preview.png)
- [Card YAML](default-v2-mobile-aq/card.yaml)
- [Example notes](default-v2-mobile-aq/README.md)

### Default V2 Tablet Zone 1 Cooking

- Style: tablet-friendly V2 control surface with the Zone 1 cooking lane selected
- Optimised for: tablets, wall panels, and wider dashboard views
- Author: @senyo888
- Source template: `custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml`
- Required custom cards: `card-mod`, `button-card`, `mod-card`, `apexcharts-card`

- [Historical Tablet layout preview](default-v2-tablet-zone-1-cooking/preview.png)
- [Card YAML](default-v2-tablet-zone-1-cooking/card.yaml)
- [Example notes](default-v2-tablet-zone-1-cooking/README.md)

### Default V1 Mobile (Deprecated)

- Status: deprecated for new dashboards; still exportable in the v2.1 candidate
- Replacement: Default V2 Mobile AQ /
  `custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml`
- Style: legacy-compatible mobile layout with comfort band and humidity constellation
- Optimised for: phones and users keeping a V1-style dashboard presentation
- Author: @senyo888
- Source template: `custom_components/humidity_intelligence/ui/cards/v1_mobile.yaml`
- Required custom cards: `card-mod`, `button-card`, `mod-card`, `apexcharts-card`

[![Default V1 Mobile preview](default-v1-mobile/preview.png)](default-v1-mobile/preview.png)

- [View preview](default-v1-mobile/preview.png)
- [Card YAML](default-v1-mobile/card.yaml)
- [Example notes](default-v1-mobile/README.md)

The V1 example remains available for existing users in this candidate, including the
dynamic-text HTML-escaping fix. Do not use it for new dashboard installations.
Removal requires a separately approved migration.

## Submitting Gallery Examples

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a UI Gallery pull request.

Every example must use:

```text
ui-gallery/<card-id>/
```

Required files:

- `README.md`
- `card.yaml` or `dashboard.yaml`
- `preview.png`

Use [reference.txt](reference.txt) as the entry template.
