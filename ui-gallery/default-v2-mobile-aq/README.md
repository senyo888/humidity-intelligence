# Default V2 Mobile AQ

- Style: mobile-first V2 control surface with air-quality lane active state
- Optimised for: phones and narrow dashboard panels
- Author: @senyo888
- Source template: `custom_components/humidity_intelligence/ui/cards/v2_mobile.yaml`
- Required custom cards: `card-mod`, `button-card`, `mod-card`, `apexcharts-card`

[![Air-quality response](../../assets/ui/v2.1/air-quality-response.png)](../../assets/ui/v2.1/air-quality-response.png)

## Notes

The V2 Mobile example follows the backend reason, Stability and history contracts.
Ventilation and humidifier chips share one horizontally scrollable Current Air
Control row. See the [UI guide](../../custom_components/humidity_intelligence/ui/README.md)
for compatibility and refresh instructions.

In your installation, use `humidity_intelligence.dump_cards` to generate cards with
your entity mappings. The gallery YAML provides the reusable layout.

## Files

- [Air-quality response](../../assets/ui/v2.1/air-quality-response.png)
- [Historical layout preview](preview.png)
- [Card YAML](card.yaml)
