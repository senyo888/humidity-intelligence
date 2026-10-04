# Default V2 Tablet Zone 1 Cooking

- Style: tablet-friendly V2 control surface with the Zone 1 cooking lane selected
- Optimised for: tablets, wall panels, and wider dashboard views
- Author: @senyo888
- Source template: `custom_components/humidity_intelligence/ui/cards/v2_tablet.yaml`
- Required custom cards: `card-mod`, `button-card`, `mod-card`, `apexcharts-card`

## Notes

The V2 Tablet example follows the backend reason, Stability and history contracts.
Ventilation and humidifier chips share one horizontally scrollable Current Air
Control row. See the [UI guide](../../custom_components/humidity_intelligence/ui/README.md)
for compatibility and refresh instructions.

In your installation, use `humidity_intelligence.dump_cards` to generate cards with
your entity mappings. The gallery YAML provides the reusable layout.

## Files

- [Historical layout preview](preview.png)
- [Card YAML](card.yaml)
