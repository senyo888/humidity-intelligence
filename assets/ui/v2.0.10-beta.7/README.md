# Humidity Intelligence 2.0.10-beta.7 UI captures

These public assets document the refreshed V2 Mobile and V2 Tablet cards from an
exact live `2.0.10-beta.7` installation. Before capture, Home Assistant was
restarted, the cards were freshly exported with `dump_cards` or `view_cards`, the
complete Manual-card YAML was replaced, and the dashboard/browser cache was
refreshed.

The full dashboard images are live UI evidence for this package and card set. They
do not, by themselves, prove soak completion, Stable approval, release approval, or
HACS publication.

The two before/after images are editorial comparison graphics assembled to explain
the presentation change. Their refreshed panels use beta.7 UI evidence, but the
compositions are not continuous playback records.

These assets are retained as historical evidence. Current state-example references
use the separately prepared v2.1 captures; those also predate the final v2.1 score
polish. The intended uses below describe the original publication placements and do
not identify current-interface evidence.

## Historical asset index

| File | Label | Historical intended use |
| --- | --- | --- |
| `mobile-manual-override-active.jpg` | Manual override — HI steps back and says so | Supporting state example |
| `mobile-automatic-control-disabled.jpg` | Disabled — automatic control is intentionally off | Supporting state example |
| `mobile-aq-humidifier-retrying.png` | Air-quality response — lane selection and retry truth stay together | README, site, gallery |
| `tablet-aq-humidifier-fault.jpg` | Output fault — uncertainty remains visible | Supporting state example |
| `tablet-zone1-cooking-output-on.jpg` | Cooking response — what changed, why it mattered, and what HI selected | README, site, gallery |
| `mobile-zone2-bathroom-output-on.jpg` | Bathroom response — room, zone, and observed output in one view | Supporting state example |
| `mobile-high-humidity-alert.jpg` | High-humidity alert — danger, source, zone, and response stay explicit | Supporting state example |
| `comparison-alert-reason-before-after.png` | The same deterministic alert decision, now explained in natural language | Editorial comparison |
| `comparison-reason-field-before-after.png` | What happened, why it happened, and what HI is doing | Editorial comparison |
| `mobile-monitoring-output-unknown.jpg` | Monitoring honestly when an output is unknown | Supporting Wiki example; low-resolution source |

## Public-safety note

The numeric telemetry in these captures is approved for public use. Generic room,
level, zone, and output labels are retained. The alert comparison's original private
entity ID was replaced with `sensor.example_bathroom_humidity`. Public derivatives
were re-encoded without source metadata.
