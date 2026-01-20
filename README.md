# Humidity Intelligence Advanced HACS - Edition

Version v1.1.2


<img width="1536" height="1024" alt="Banner-4" src="https://github.com/user-attachments/assets/71a0714c-b20f-46da-868c-d52f28193416" />


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

![IMG_5368](https://github.com/user-attachments/assets/8cc1a546-2318-4f31-9d91-0cd2bf1c3437)

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

HACS uses the `.jinja` file as the install source.

---


## 🚀 Installation

Humidity Intelligence is distributed via **HACS as a managed template package**.

This means:

* HACS **does not write directly** to your `configuration.yaml` or `/packages/`
* You explicitly decide **how** the package is deployed into your config
* This keeps your setup predictable and update-safe

Follow the steps below carefully.

---

### 1️⃣ Add repository to HACS

1. Open **HACS**
2. Go to **Integrations**
3. Click **⋮ → Custom repositories**
4. Add this repository as:

   * **Category:** Template
   * **Name:** Humidity Intelligence
     [https://github.com/senyo888/Humidity-Intelligence](https://github.com/senyo888/Humidity-Intelligence)
5. Install
6. Restart Home Assistant

After this step, HACS installs the managed source file here:

```text
/config/custom_templates/humidity_intelligence.jinja
```

⚠️ **Important:**
This file is **owned by HACS** and **will be overwritten on every update**.

Do **not** edit it directly.

---

### 2️⃣ Enable packages (one-time setup)

If you are not already using packages, add the following to `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_merge_named packages
```
or

```
homeassistant:
  packages: !include_dir_named packages
```

Restart Home Assistant.

This only needs to be done once.

---

### 3️⃣ Deploy the package (choose one approach)

At this point, nothing is active yet.
You must now choose **how Humidity Intelligence is wired into your config**.

---

#### 🅰️ Option A — Copy (static, user-owned)

Create the file:

```text
/config/packages/humidity_intelligence.yaml
```

Then copy the **entire contents** of:

```text
custom_templates/humidity_intelligence.jinja
```

into that file.

**Use this option if you want:**

* Full control over the YAML
* To freely modify logic
* To avoid possible changes on HACS update

**Trade-off:**

* You must manually update your copy when new versions are released

---

#### 🅱️ Option B — Include (recommended)

Reference the HACS-managed file directly:

```yaml
packages:
  humidity_intelligence: !include jinja/humidity_intelligence.jinja
```

Restart Home Assistant again.

**This is the recommended approach.**

**What this means:**

* You receive fixes and improvements automatically via HACS
* The backend remains canonical and consistent
* You do **not** duplicate logic

⚠️ **Important behaviour (read this):**

> If you choose **Option B**, **any changes you make to entity IDs, names, or logic inside the package could be reset to the canonical defaults on some HACS update**.

This is intentional.

Option B treats Humidity Intelligence as a **library**, not user-owned config.

---

### 🔑 Which option should I choose?

| If you want…                           | Choose   |
| -------------------------------------- | -------- |
| Automatic updates                      | Option B |
| Canonical entity IDs                   | Option B |
| Minimal maintenance                    | Option B |
| To freely customise backend logic      | Option A |
| No risk of updates overwriting changes | Option A |

Most users should choose **Option B**.

---

### ✅ After deployment

Once deployed:

* Restart Home Assistant
* Proceed to **Configuration** below to map your room sensors
  (this is the *only* part you are expected to edit)

---



## 🔧 Configuration (the only part you should need to edit)

All defaults are **placeholders**.

Humidity Intelligence is built around a **stable public entity API** (see below).
To connect your sensors, you have two supported approaches:

### ✅ Recommended approach: Map your sensors (normal)

You keep your existing entity IDs and just point Humidity Intelligence at them.

### Optional approach: Align your entity IDs (zero-edit experience)

If you want the **reference UI + gallery UIs** to work with minimal/no edits, you can choose to **align your entity naming** to the examples used here (e.g. `sensor.living_room_humidity`, `sensor.living_room_temperature`).
This is optional — the backend works either way.

> Practical tip: *alias/rename in your integrations where possible*, rather than creating lots of extra template sensors. Keep it tidy.

---

### 1️⃣ Room map (humidity)

Edit the `Humidity Intelligence Config` room map:

```yaml
'Living Room': 'sensor.living_room_humidity'
'Kitchen':     'sensor.kitchen_humidity'
```

* Replace the entity IDs with your real humidity sensors
* Add/remove rooms freely
* Invalid/unavailable sensors are ignored automatically

This map drives:

* House averages
* Constellation chart
* Worst-room logic

---

### 2️⃣ 7-day statistics (drift)

Each room has a statistics sensor like:

```yaml
entity_id: sensor.living_room_humidity
```

Change **only** the `entity_id`.

> Don’t rename the statistics sensors unless you also update downstream templates.

---

### 3️⃣ Dew point inputs (temp + humidity)

For each room, the dew point logic expects:

```jinja2
sensor.living_room_temperature
sensor.living_room_humidity
```

Once mapped, **everything else is automatic**.

---

## ⚠️ Important note if you chose Option B (Include)

If you installed using **Option B (Include)**, the source file is **managed by HACS** and could be overwritten on update.

That means:

* ✅ Changes you make to *your* sensor mapping (in your own config) persist
* ❌ Changes you make inside the HACS-managed `.jinja` file do not persist

If you need a fully editable copy you can change freely, use **Option A (Copy)** instead.

---

## 🚫 Public entity API (do not rename)

These entity IDs are intentionally stable and used by the UI and gallery submissions:

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
If you keep them unchanged, most UIs “just work”.

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

## 🖼️ UI Gallery

Humidity Intelligence is designed to support **many visual interpretations**.

The UI Gallery showcases ** defult & community-built dashboards, badges and cards** built on top of the
Humidity Intelligence backend, including:

- Mobile-first layouts
- Tablet and wall-panel dashboards
- Minimal or graph-heavy designs
- Automation-centric or insight-driven views

All gallery submissions must follow the project’s **canonical UI rules**
to ensure portability, clarity, and compatibility.

> Gallery entries are reviewed and validated before inclusion.

👉 See `CONTRIBUTING.md` for:
- required folder structure
- preview image rules
- canonical entity and helper usage
- PR and review expectations


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

## ⚠️ Notes on Editor Warnings & Known Issues

### VS Code / YAML `patternWarning`

Some users may see a warning similar to:

```
patternWarning yaml-schema: http://schemas.home-assistant.io/configuration
```

This typically appears in **VS Code** when using:

```yaml
homeassistant:
  packages: !include_dir_merge_named packages
```

**Important:**
This is **not a Home Assistant runtime error**.

* `!include_dir_merge_named` is a **valid and supported** Home Assistant feature.
* Home Assistant will start normally and the sensors will function as expected.
* The warning comes from the **VS Code Home Assistant schema validator**, which does not fully understand all advanced YAML directives.

✅ If Home Assistant starts and the Humidity Intelligence sensors appear, this warning can be safely ignored.

---

### House Average Humidity showing `unknown` (v1.0.2)

In **v1.0.2**, there was a known issue in the *House Average Humidity* template caused by yaml variable scoping inside a loop.
This could result in the sensor returning `unknown` even when valid humidity data existed.

* This issue **only affects v1.0.2**
* It has been fixed in later versions using a  `namespace()` approach
* Upgrading resolves the problem

If you encounter this behaviour, please confirm which version you are running before opening an issue.

---

### When reporting issues

To help diagnose problems quickly, please include:

* Humidity Intelligence version
* Home Assistant version
* Whether the issue is:

  * a runtime error in Home Assistant **or**
  * an editor/schema warning (e.g. VS Code)

This helps distinguish real bugs from tooling limitations.

---

## ❤️ Intent

Humidity Intelligence exists because:

> “65% isn’t helpful.
> Tell me if it’s bad **here**, **now**, and **what to do**.”

If it helps you understand your building better, a ⭐ or a screenshot in Discussions is always appreciated.

---

# Humidity Intelligence Lovelace UI

## Constellation Open

<img width="603" height="921" alt="IMG_5369" src="https://github.com/user-attachments/assets/07aad31a-01ad-4d19-a540-e52937901594" />





