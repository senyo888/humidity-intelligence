# Humidity-Intelligence

Smart humidity intelligence for Home Assistant – badges, comfort band and 24-hour multi-room chart.

# Version: **v1.1.0**

![IMG_5368](https://github.com/user-attachments/assets/8ce3f56c-f232-4be6-a941-5b31a2983387) 


---

# 🌧️ Humidity-Intelligence — v1.1.0

### Smart humidity analysis for Home Assistant — insights, not just numbers.

Humidity-Intelligence turns your room sensors into a **decision-making dashboard**:

✔️ House average + **season-aware comfort band**
✔️ Dew-point per room
✔️ Condensation spread (°C from trouble)
✔️ Mould risk scoring
✔️ 7-day drift (house + rooms)
✔️ “Worst room” summary
✔️ Plain-language **ventilation suggestion**
✔️ Multi-room **Humidity Constellation** chart (dropdown-mod style UI)

This isn’t “just humidity graphs”.
It answers the real question:

> **“Am I heading toward condensation or mould — and what should I do?”**

---

## 📦 Requirements & Dependencies

### Home Assistant

* Home Assistant (recent version, 2024.x+ recommended)
* YAML mode enabled, or at least support for **packages** via `configuration.yaml`.

Core integrations used (no extra install needed):

* `statistics` platform (for 7-day means)
* `template` platform (for sensors & binary_sensors)

### Frontend (for the optional UI + Constellation chart)

If you want the **full badge + Comfort Band + dropdown Constellation UI**, you’ll need these custom cards:

* [`button-card`](https://github.com/custom-cards/button-card)
* [`apexcharts-card`](https://github.com/RomRider/apexcharts-card)
* [`config-template-card`](https://github.com/iantrich/config-template-card)
* [`card-mod`](https://github.com/thomasloven/lovelace-card-mod)

Best installed via **HACS → Frontend**.

> The **backend package works without these**, but the prebuilt Humidity-Intelligence UI and Constellation chart depend on them.

---

## 🔧 Installation (5–10 minutes)

### 1️⃣ Enable packages (if not already)

Create:

```text
/config/packages/
```

In `configuration.yaml`, make sure you have:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Restart Home Assistant once.

---

### 2️⃣ Add the Humidity-Intelligence package

Copy the file:

```text
/config/packages/humidity_intelligence.yaml
```

Restart Home Assistant again.

> Don’t panic if you see warnings/errors about entities at this stage — that just means you haven’t mapped your sensors yet. Next step fixes that.

---

## 🔁 How the system is structured

This package builds around three pillars:

1️⃣ **Dynamic room map**

* One place to define which rooms you care about.
* Backend uses this map for averages & Constellation.

2️⃣ **Advanced analysis engine**

* Dew-point, condensation spread, mould risk, drift, ventilation suggestion.

3️⃣ **Public entity API for UI**

* Well-defined `sensor.*` and `binary_sensor.*` outputs that your Lovelace UI, dropdown-mod pattern, and automations can rely on.

You only change **your input entities** (your room sensors).
The public outputs stay stable.

---

## 📍 STEP 1 — Map your entities (the *only* bit you must edit)

All default names in the package are **generic placeholders**.
You need to replace them with your actual **temperature and humidity sensors**.

The two main places:

1. Dynamic `room_map`
2. Per-room dew-point / spread / risk logic

---

### 🗺️ 1.1 — Dynamic room map (humidity only)

Find this block near the top:

```yaml
- name: "Humidity Intelligence Config"
  unique_id: humidity_intelligence_config
  state: "Active"
  attributes:
    room_map: >
      {{ {
        'Living Room': 'sensor.living_room_humidity',   # ← CHANGE
        'Kitchen':     'sensor.kitchen_humidity',       # ← CHANGE
        'Hallway':     'sensor.hallway_humidity',       # ← CHANGE
        'Bedroom':     'sensor.bedroom_humidity',       # ← CHANGE
        'Kids Room':   'sensor.kids_room_humidity',     # ← CHANGE
        'Bathroom':    'sensor.bathroom_humidity',      # ← CHANGE
        'Toilet':      'sensor.toilet_humidity'         # ← CHANGE
      } }}
```

For each room:

* Replace the **entity id** with your real **humidity sensor** for that room.
* You can **remove rooms** you don’t have, or **add extra rooms** using the same pattern.

Example for a user with Zigbee sensors:

```yaml
'Living Room': 'sensor.zigbee_lounge_humidity',
'Kids Room':   'sensor.kids_bedroom_relative_humidity',
```

This `room_map` drives:

* `sensor.house_average_humidity`
* `sensor.humidity_constellation_series`
* Worst-room condensation/mould summaries

Anything missing/unavailable is automatically ignored.

---

### 📊 1.2 — 7-day statistics (drift engine)

Each room has a statistics sensor:

```yaml
- platform: statistics
  name: "Living Room Humidity Mean 7d"
  entity_id: sensor.living_room_humidity   # ← CHANGE
  state_characteristic: mean
  max_age:
    days: 7
```

For each block:

* Change **only** the `entity_id` to match your room humidity sensor.
* Keep the **`name`** and the generated sensor id pattern as-is, unless you know what you’re doing and also update the later templates.

These feed the “Drift 7d” sensors.

---

### 🌡️ 1.3 — Dew point inputs (temp + humidity per room)

Example for the living room:

```jinja2
{% set T  = states('sensor.living_room_temperature') | float(none) %}  # ← CHANGE
{% set RH = states('sensor.living_room_humidity')    | float(none) %}  # ← CHANGE
```

Do this for each room:

* `*_temperature` → your room temperature sensor
* `*_humidity`    → your room humidity sensor

Once correct:

* Dew point (`*_dew_point`)
* Condensation spread (`*_condensation_spread`)
* Condensation risk (`*_condensation_risk`)
* Mould risk (`*_mould_risk`)

will all compute automatically.

---

## 🚫 Do **not** rename these public outputs

The UI, dropdown-mod pattern, and future releases depend on these **public entity ids**:

```text
sensor.house_average_humidity
sensor.house_humidity_mean_7d
sensor.house_humidity_drift_7d

sensor.worst_room_condensation
sensor.worst_room_condensation_risk
sensor.worst_room_mould
sensor.worst_room_mould_risk

sensor.humidity_constellation_series

binary_sensor.humidity_danger
binary_sensor.condensation_danger
binary_sensor.mould_danger

input_boolean.humidity_constellation_expanded
```

Treat these as the **API layer**.

* You customize **inputs** (room sensors)
* These **outputs** stay stable for UI and automations.

---

## 🎛️ Dropdown-mod + Constellation UI (frontend)

This package is built to work beautifully with a **dropdown-mod style card**:

* **Row 1**: four circular badges (Humidity / Condensation / Mould / Drift)
* **Row 2**: “Comfort Band” card – tap to toggle
* **Dropdown**: 24h **Humidity Constellation** chart

### Entities the UI expects

From this package:

* `sensor.house_average_humidity`
* `sensor.house_humidity_target_low`
* `sensor.house_humidity_target_high`
* `sensor.house_humidity_drift_7d`
* `sensor.worst_room_condensation`
* `sensor.worst_room_condensation_risk`
* `sensor.worst_room_mould`
* `sensor.worst_room_mould_risk`
* `binary_sensor.humidity_danger`
* `binary_sensor.condensation_danger`
* `binary_sensor.mould_danger`
* `sensor.humidity_constellation_series`
* `input_boolean.humidity_constellation_expanded`

From frontend dependencies:

* `custom:button-card`
* `custom:apexcharts-card`
* `custom:config-template-card`
* `card-mod`

> If you’re using the provided UI YAML, install the frontend dependencies via HACS first, then paste the card into a view. The dropdown behaviour is controlled by `input_boolean.humidity_constellation_expanded`.

---

## 🤖 What the backend actually calculates

### House-level analytics

* `sensor.house_average_humidity`
* `sensor.house_average_temperature`
* `sensor.house_humidity_mean_7d` (statistics platform)
* `sensor.house_humidity_drift_7d` (current vs 7-day mean)
* Seasonal **target band**:

  * Winter: tighter band to reduce condensation
  * Summer: slightly higher upper target
* `sensor.ventilation_suggestion` — plain-language advice
* `binary_sensor.humidity_danger` — extreme high/low humidity alert

### Per-room metrics

For each mapped room (Living Room, Kitchen, Hallway, Bedroom, Kids Room, Bathroom, Toilet):

* `*_dew_point`
* `*_condensation_spread` (°C above dew point)
* `*_condensation_risk` (`OK / Watch / Risk / Danger`)
* `*_mould_risk` (score-combined humidity + spread)
* `*_humidity_drift_7d` (current vs room’s 7-day mean)

### Smart summaries

* `sensor.worst_room_condensation`
* `sensor.worst_room_condensation_risk`
* `sensor.worst_room_mould`
* `sensor.worst_room_mould_risk`

### Constellation engine

* `sensor.humidity_constellation_series` — attribute `series` contains a JSON-like list of `{ entity, name, curve, group_by }` definitions for `apexcharts-card` via `config-template-card`.

This removes the need to manually maintain per-room series in the UI YAML.

---

## 🧭 Roadmap

### 1.2.x — Dynamic Intelligence Edition

Planned evolution:

* Put more of the advanced per-room logic behind the **dynamic `room_map`**
* Optional “outdoor reference” input (for better context)
* Easier onboarding (minimal edits, defaults for common setups)
* Enhanced UI variants (compact mobile view, wall tablet view)

### Longer-term ideas

* Predictive condensation warnings (“likely in 2–4 hours”)
* Energy-aware ventilation recommendations
* Integration hooks for climate/ventilation automations
* Exportable humidity “health report” per season
* HACS raedy structure & Auto release

---

## 🛠️ Troubleshooting

### 🔸 Card loads, but values show `unknown` or `-`

Check:

* Have you **mapped all entity ids** for humidity + temperature?
* Does each referenced sensor show a numeric value in **Developer Tools → States**?
* 7-day mean sensors need time to collect history before drift becomes meaningful.

---

### 🔸 Constellation chart is blank

1. Open **Developer Tools → States**.

2. Look at:

   ```text
   sensor.humidity_constellation_series
   ```

3. If `attributes.series` is empty or invalid:

   * One or more room entities in `room_map` are wrong (typo / don’t exist).
   * Fix the entity ids, reload templates (or restart), and check again.

---

### 🔸 Ventilation suggestion feels “too aggressive”

This logic is intentionally conservative (biased toward early action).

If it shouts “Risk / Danger” frequently:

* Check bathroom and kitchen extraction (run time + power).
* Keep doors closed during moisture events.
* Avoid drying large loads of washing indoors without a plan.

You can tweak thresholds by editing:

* Condensation risk cut-offs (spread)
* Mould scoring thresholds (humidity + spread)
* Target band ranges (seasonal section)

---

### 🔸 YAML error on restart

* Use **Developer Tools → YAML → Check configuration**.
* The error will point at a **line number** in the package.
* Most common issues:

  * Indentation off after manual edits
  * Missing or extra quotes in strings
  * Accidental tab characters

If stuck, strip back to the original file and re-apply your entity mappings carefully.

---

## 🙌 Contributing

Contributions are welcome:

* New UI patterns (compact / wall / mobile)
* Additional room templates or example configs
* Translations of the ventilation guidance
* Bugfixes and robustness improvements

When opening a PR:

* Keep **default entity ids generic** (`sensor.living_room_humidity`, etc.)
* Avoid baking in personal device names.
* Try to maintain the **public entity API** listed above.

---

## ❤️ Credits & intent

Humidity-Intelligence grew from a practical need:

> “Stop just showing me 65%.
> Tell me if that’s bad *for this room, this season, right now* — and what I should actually do.”

If this project helps you understand your building better, a ⭐ on the repo and a screenshot/thread in Issues/Discussions is always appreciated.

---



