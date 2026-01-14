# Humidity Intelligence Advanced HACS - Edition

**Smart humidity intelligence for Home Assistant — insights, not just numbers.**

<img width="1536" height="1024" alt="banner" src="https://github.com/user-attachments/assets/72d0ce73-e8a4-412d-a3c1-570b1048d740" />


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
* Add this repo as **Template**
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

## 🎛️ UI & dropdown-mod support

The package is designed to pair with a **badge-first dashboard**:

* Four circular badges (Humidity / Condensation / Mould / Drift)
* Comfort Band card
* Dropdown-mod **24-hour Humidity Constellation**

The Constellation chart is auto-generated — no manual series editing required.

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

---

## ❤️ Intent

Humidity Intelligence exists because:

> “65% isn’t helpful.
> Tell me if it’s bad **here**, **now**, and **what to do**.”

If it helps you understand your building better, a ⭐ or a screenshot in Discussions is always appreciated.

---


Just say the word.




