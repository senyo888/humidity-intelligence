# Humidity Intelligence Advanced HACS - Edition

Version v1.1.1

**Smart humidity intelligence for Home Assistant — insights, not just numbers.**

Humidity Intelligence is an opinionated Home Assistant package that transforms raw humidity and temperature readings into **actionable building insight**.

It doesn’t just show percentages — it answers the real questions:

> **Am I heading toward condensation or mould?
> Where is the risk coming from?
> And what should I actually do right now?**

This Advanced Edition reflects the system I run at home and is designed to be:

* Vendor-agnostic
* Sensor-driven
* UI-friendly
* Automation-ready

---

## ✨ What it does

Humidity Intelligence builds a **decision-making layer** on top of your existing room sensors.

### House-level intelligence

* Dynamic **house average humidity**
* **Season-aware comfort band**
* 7-day humidity **drift** (current vs historical mean)
* Plain-language **ventilation suggestion**
* Binary danger flags for automations

### Per-room analysis

For every mapped room:

* Dew point calculation (Magnus formula)
* Condensation spread (°C above dew point)
* Condensation risk: **OK / Watch / Risk / Danger**
* Mould risk (humidity + spread scoring)
* 7-day room-level drift

### Smart summaries

* Worst room for condensation
* Worst room for mould
* Worst-case risk levels exposed as sensors

### Dashboard-ready outputs

* Stable `sensor.*` and `binary_sensor.*` entities
* ApexCharts-ready **Humidity Constellation** series
* Designed to power badge-based and dropdown-mod UIs

This is not a graph pack.
It’s an **analysis engine with a clean public API**.

---

## 📦 Requirements

### Home Assistant

* Home Assistant **2024.x+**
* YAML mode or package support enabled

### Core integrations (built-in)

* `template`
* `statistics`

### Frontend (optional, for the full UI)

- [HACS](https://hacs.xyz) (recommended) for easy frontend installation
- Frontend cards:
  - [`button-card`](https://github.com/custom-cards/button-card)
  - [`apexcharts-card`](https://github.com/RomRider/apexcharts-card)
  - [`card-mod`](https://github.com/thomasloven/lovelace-card-mod)
  * `config-template-card`

> The **backend works without these**.
> The provided UI and Constellation chart require them.

---

## 📁 Repository structure

This repository follows the HACS **custom template** layout:

| Path                          | Purpose                            |
| ----------------------------- | ---------------------------------- |
| `humidity_intelligence.jinja` | Core package (all sensors & logic) |
| `lovelace/`                   | Optional prebuilt dashboard card   |
| `assets/`                     | README assets                      |
| `hacs.json`                   | HACS metadata                      |
| `LICENSE`                     | MIT licence                        |

HACS uses the `.jinja` file as the install source. You control where and how it is included.

---

## 🚀 Installation

### 1️⃣ Add repository to HACS

* HACS → **Integrations**
* ⋮ → **Custom repositories**
* Add this repo as **Template** [`Humidity Intelligence`](https://github.com/senyo888/Humidity-Intelligence)
* Install
---

### 2️⃣ Enable packages (once)

In `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_merge_named packages
```

Restart Home Assistant.

---

### 3️⃣ Deploy the package

Choose **one** approach:

**Option A — Copy**

```text
/config/packages/humidity_intelligence.yaml
```

Copy the full contents of `humidity_intelligence.jinja` into it.

**Option B — Include**

```yaml
packages:
  humidity_intelligence: !include jinja/humidity_intelligence.jinja
```

Restart Home Assistant again.

---

## 🔧 Configuration (the only part you must edit)

All defaults are **placeholders**.

You only need to map your real sensors.

### 1️⃣ Room map (humidity)

Edit the `Humidity Intelligence Config` block:

```yaml
'Living Room': 'sensor.living_room_humidity'
'Kitchen':     'sensor.kitchen_humidity'
```

* Replace entity IDs with your real humidity sensors
* Add or remove rooms freely
* Invalid or unavailable sensors are ignored automatically

This map drives:

* House averages
* Constellation chart
* Worst-room logic

---

### 2️⃣ 7-day statistics (drift)

Each room has a statistics sensor:

```yaml
entity_id: sensor.living_room_humidity
```

Change **only** the `entity_id`.

Do not rename the statistics sensors unless you also update downstream templates.

---

### 3️⃣ Dew point inputs (temp + humidity)

For each room:

```jinja2
sensor.living_room_temperature
sensor.living_room_humidity
```

Once mapped, **everything else is automatic**.

---

## 🚫 Public entity API (do not rename)

These entity IDs are intentionally stable and used by the UI:

```
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

Think of these as the **public interface**.

---

## 🎛️ Lovelace UI (optional)

Humidity Intelligence is **backend-first**.

The package exposes a stable set of sensors and binary sensors designed to be consumed by **any dashboard, automation, or card style you prefer**.

This repository includes a **reference Lovelace UI** to demonstrate what the data *can* do — not what it *must* look like.

---

### What the reference UI shows

The included UI demonstrates:

* A **badge-first overview** (Humidity / Condensation / Mould / Drift)
* A contextual **Comfort Band** summary
* A chevron-controlled **dropdown-mod**
* A dynamic **24-hour Humidity Constellation** chart

The chart and dropdown are fully driven by backend sensors — no room entities are hard-coded.

---

### Applying the UI

The example Lovelace card is located in:

```text
lovelace/humidity_intelligence_card.yaml
```

To use it:

1. Install the required frontend cards (see below)
2. Add a **Manual card** to your dashboard
3. Paste the YAML
4. Save

If you keep the public entity IDs unchanged, **you maybe required to edit entity ID for the humidity constelltion**.

---

### Frontend requirements (UI only)

The reference UI uses the following custom cards:

* `button-card`
* `apexcharts-card`
* `card-mod`
* `config-template-card`

> The backend works without any of these.
> They are only required if you want the example UI.

---

### Dropdown-mod behaviour

The Constellation chart is controlled by:

```
input_boolean.humidity_constellation_expanded
```

The Comfort Band card toggles this helper via a chevron.

This pattern is deliberate and reusable — you can attach the same helper to any UI element you like.

---

### Customising the UI (encouraged)

You are encouraged to:

* Re-style the badges
* Replace ApexCharts
* Build mobile-first or wall-panel layouts
* Skip dashboards entirely and use automations instead

As long as you use the **public entity API**, the backend will support you.

There is no canonical UI.

---

## 🖼️ UI Gallery (scaffold)

Humidity Intelligence is designed to support **many visual interpretations**.

This section is reserved for **community-built dashboards**, including:

* Mobile layouts
* Wall panels
* Minimal or graph-heavy designs
* Automation-centric views

If you build something interesting, share it.

See `CONTRIBUTING.md` for how to add your UI to the gallery.

---


## 🧠 How the intelligence works (brief)

* Dew point calculated per room
* Condensation risk derived from **spread**
* Mould risk combines **humidity + spread**
* Seasonal comfort band adjusts thresholds
* Ventilation guidance is intentionally conservative

This biases toward **early warning**, not late alarm.

---

## 🧭 Roadmap

**1.2.x**

* More logic driven from the dynamic room map
* Optional outdoor reference inputs
* Easier onboarding
* Compact more UI variant

**Future**

* Predictive condensation warnings
* Energy-aware ventilation hints
* Automation hooks
* Seasonal humidity health reports

---

## 🛠️ Troubleshooting

**Values show `unknown`**

* Check entity IDs exist and are numeric
* Drift sensors need history (up to 7 days)

**Constellation chart blank**

* Inspect `sensor.humidity_constellation_series`
* One or more room entities are invalid

**Ventilation feels aggressive**

* This is intentional
* Tune thresholds if your building behaves differently
* Remember to rename humidity_intelligence.jinja to .yaml

---

## ❤️ Intent

Humidity Intelligence exists because:

> “65% isn’t helpful.
> Tell me if it’s bad **here**, **now**, and **what to do**.”

If it helps you understand your building better, a ⭐ or a screenshot in Discussions is always appreciated.

---

# Humidity Intelligence Lovelace UI

## Constellation Closed
  
![IMG_5368](https://github.com/user-attachments/assets/8cc1a546-2318-4f31-9d91-0cd2bf1c3437)


## Constellation Open

<img width="603" height="921" alt="IMG_5369" src="https://github.com/user-attachments/assets/07aad31a-01ad-4d19-a540-e52937901594" />





