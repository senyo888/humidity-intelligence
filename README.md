# Humidity-Intelligence

Smart humidity intelligence for Home Assistant – badges, comfort band and 24-hour multi-room chart.

> Version: **v1.0.0**

![IMG_5368](https://github.com/user-attachments/assets/8ce3f56c-f232-4be6-a941-5b31a2983387) 

> **TL;DR:**  
> Drop one package file into `/config/packages/`, paste one Lovelace card, change your room sensor IDs, and you get:
> - Live house-average humidity  
> - Condensation & mould risk badges  
> - 7-day humidity drift  
> - A Comfort Band panel with actionable guidance  
> - A dropdown 24-hour multi-room humidity chart

---

## Features

- **Four badges across the top**
  - **Humidity** – live house average with dynamic colour + glow
  - **Condensation** – worst-room risk (“Watch / Risk / Danger”)
  - **Mould** – worst-room risk (“Watch / Risk / Danger”)
  - **Drift** – 7-day difference vs historical mean (up/down trend)

- **Comfort Band panel**
  - Shows **target band** (default 45–55 %)
  - Plain-language comfort text: dry / sweet spot / high
  - Worst-room **condensation** + **mould** summary lines
  - Tapping anywhere on the card toggles an **expansion chevron**

- **Humidity Constellation (24 h)**
  - ApexCharts line chart of all your key rooms
  - Target band rendered as a shaded zone
  - 24-hour, group-by-15-minutes smoothing
  - Hidden by default; opened by the Comfort Band chevron

- **Backend intelligence (no automations required)**
  - House average humidity
  - 7-day mean and drift
  - Worst-room condensation and mould with simple thresholds
  - Binary “danger” flags to drive the badge styling

- **Responsive UI**
  - Circular badges scale between phone and tablet widths
  - Works as a single stack or dropped into a larger dashboard

---

## Requirements

- Home Assistant 20251203.3 (tested on recent installs)
- [HACS](https://hacs.xyz) (recommended) for easy frontend installation
- Frontend cards:
  - [`button-card`](https://github.com/custom-cards/button-card)
  - [`apexcharts-card`](https://github.com/RomRider/apexcharts-card)
  - [`card-mod`](https://github.com/thomasloven/lovelace-card-mod)

---

## Set-up Instructions

---


* `packages/humidity_intelligence.yaml`
  All backend logic: helpers, template sensors, statistics, risk flags.

* `lovelace/humidity_intelligence_card.yaml`
  The UI card: badges, Comfort Band + chevron, Humidity Constellation chart.

The README assumes this structure, but you can rename folders if you like.

---

## 1. Enable packages (once per HA instance)

If you already use packages, you can skip this step.

1. Create a folder called `packages` inside your Home Assistant config folder:

   ```text
   /config/packages/
   ```

2. Open `configuration.yaml` and add (or extend) the `homeassistant:` block:

   ```yaml
   homeassistant:
     packages: !include_dir_merge_named packages/
   ```

3. Go to **Settings → System → Developer tools → Check configuration**.

4. If valid, restart Home Assistant.

---

## 2. Install frontend dependencies

Install via **HACS → Frontend**:

1. Search for and install:

   * **button-card**
   * **apexcharts-card**
   * **card-mod**
2. Restart Home Assistant after all three are installed.

---

## 3. Add the backend package

1. Copy `packages/humidity_intelligence.yaml` from this repo into:

   ```text
   /config/packages/humidity_intelligence.yaml
   ```

2. Open the file and **edit the room humidity entities** under this block:

   ```jinja2
   # >>> EDIT THESE ENTITY IDS TO MATCH YOUR SENSORS <<<
   {% set rooms = [
     'sensor.living_room_humidity',
     'sensor.kitchen_humidity',
     'sensor.hallway_humidity',
     'sensor.bedroom_humidity',
     'sensor.kids_room_humidity',
     'sensor.bathroom_humidity',
     'sensor.toilet_humidity'
   ] %}
   ```

   Replace these with your own humidity sensor entity IDs.
   You can safely remove rooms you don’t have, or add more.

3. (Optional) Adjust the **comfort band** thresholds:

   ```jinja2
   - name: House Humidity Target Low
     state: 45        # change to your preferred lower limit

   - name: House Humidity Target High
     state: 55        # change to your preferred upper limit
   ```

4. Go to **Developer tools → Check configuration**.

5. Restart Home Assistant.

After restart you should see (under **Developer tools → States**):

* `sensor.house_average_humidity`
* `sensor.house_humidity_mean_7d`
* `sensor.house_humidity_drift_7d`
* `sensor.worst_room_condensation`
* `sensor.worst_room_condensation_risk`
* `sensor.worst_room_mould`
* `sensor.worst_room_mould_risk`
* `binary_sensor.humidity_danger`
* `binary_sensor.condensation_danger`
* `binary_sensor.mould_danger`
* `input_boolean.humidity_constellation_expanded`

If any of these are missing, re-check that the package is loaded and your YAML syntax is valid.

---

## 4. Add the Lovelace card

You can either import the card file or paste the YAML manually.

### Option A – “Manual” card (simplest)

1. Go to the dashboard where you want the card.
2. Click **⋮ → Edit dashboard → + Add card → Manual**.
3. Paste the contents of `lovelace/humidity_intelligence_card.yaml`.
4. Save.

The card will show:

* 4 badges on the first row
* Comfort Band panel
* Tapping the Comfort Band toggles the **chevron** and reveals/hides the 24-hour chart.

### Option B – Re-use across dashboards (include file)

If you like to keep your Lovelace in files:

1. Save the UI card as:

   ```text
   /config/lovelace/humidity_intelligence_card.yaml
   ```

2. In your view definition (raw YAML mode), use an include:

   ```yaml
   views:
     - title: Climate
       path: climate
       cards:
         - !include /config/lovelace/humidity_intelligence_card.yaml
   ```

3. Save and reload the dashboard.

---

## 5. Customisation

### Colour thresholds and glow

The badge borders and glows are driven by inline JavaScript in `button-card` styles.
If you want to change the thresholds (e.g. what counts as “Danger” or “Watch”), edit the relevant `if` blocks in the card YAML.

Example (humidity badge border):

```js
if (h < 45) return '2px solid rgba(56,189,248,0.75)';
if (h < 49) return '2px solid rgba(125,211,252,0.70)';
if (h < 60) return '2px solid rgba(74,222,128,0.70)';
if (h < 68) return '2px solid rgba(250,204,21,0.75)';
return '2px solid rgba(239,68,68,0.85)';
```

### Condensation / mould risk thresholds

These are set in the package file:

```jinja2
{% if h >= 80 %}
  Danger
{% elif h >= 70 %}
  Risk
{% elif h >= 60 %}
  Watch
{% else %}
  Low
{% endif %}
```

Adjust the cut-offs to fit your building and climate.

### Target band in the chart

The ApexCharts annotations use the same `House Humidity Target Low/High` sensors, so if you tweak the targets in the package, the shaded **Target band** in the chart will track automatically.

---

## 6. Troubleshooting

**The card loads but shows `unknown` everywhere**

* Check your entity IDs in the package file.
* Make sure each room sensor is actually reporting a numeric humidity value.
* `statistics` sensors need some history to produce a mean; the 7-day drift may show `0` or `unknown` right after a restart until enough samples are collected.

**The chevron doesn’t open the chart**

* Confirm `input_boolean.humidity_constellation_expanded` exists and is `on`/`off`.
* Check the `entity` for the Comfort Band button: it should be that input_boolean.
* The chart is wrapped in a `conditional` card that only shows when the boolean is `on`.

**YAML error when restarting**

* Almost always a spacing or copy/paste issue.
* Run the built-in **Check configuration** and read the line number it points to.
* Make sure the `homeassistant: packages:` line in `configuration.yaml` has the correct indentation.

---

## 7. Roadmap

* Per-room detail view / drill-down
* Optional “winter vs summer” target presets
* Temperature + humidity combined view
* HACS-ready structure & auto-release

If you have ideas, open an issue or start a discussion.

---

## 8. Contributing

Issues, ideas and pull requests are welcome:

* Tweak the thresholds, try it in different climates and report back.
* Share screenshots and alternative colour themes.
* Help test on mobile vs tablet dashboards.

When submitting a PR, please:

* Keep personal entity names out of the default config.
* Stick to standard Home Assistant practices (packages, includes, etc.).
* Aim for zero console errors in the browser.

---

## 9. License

This project is released under the **MIT License**.
You’re free to use, modify and share it in your own dashboards and automations.

---

## 10. Credits

Humidity Intelligence was built for Home Assistant users who want more than a single humidity number – they want a **story**: where the moisture is going, which room is getting risky, and whether it’s time to ventilate or relax.

If you use this card in your setup, a star on the repo and a screenshot in the issues/discussions are always appreciated 💧


