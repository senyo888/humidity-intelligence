## UI Gallery Pull Request

Thank you for submitting a UI contribution to **Humidity Intelligence**.

This repository is **HACS-facing**. Submissions are reviewed for clarity,
canonical compatibility, and portability.

---

## 📌 Summary

**UI / Card ID:**
<!-- Must match the ui-gallery/<card-id>/ folder name -->

**Short description:**
<!-- One sentence explaining what this UI demonstrates or improves -->

**Optimised for:**
<!-- Mobile / Tablet / Desktop / Wall panel -->

---

## 📁 Gallery Structure (REQUIRED)

Confirm your submission follows this structure:

```text
/ui-gallery/<card-id>/
├── <card-id>_ui.png          ← REQUIRED (minimum one)
└── <card-id>_dashboard.yaml
````

> ⚠️ Note: Gallery folders must be created **locally** and committed.
> GitHub’s web editor cannot reliably create nested gallery submissions.

Submissions without at least one `_ui.png` preview will be rejected.

---

## 🧾 README.md Entry (REQUIRED)

Confirm you have added a compliant entry to the gallery `README.md`
using the **exact required format**.

Example reference:

```md
### **DEFAULT UI**
- Style: 4 badges-first, dropdown-mod, opens humidity constellation
- Optimised for: Mobile / Tablet
- Author: @your-handle
- [![UI Preview](default-lovelace-ui/default-lovelace_ui.png)](default-lovelace-ui/default-lovelace_ui.png)
- [Default Dashboard.yaml](default-lovelace-ui/default-lovelace-ui_dashboard.yaml)
```

---

## 🧩 Canonical Compatibility Checklist (MANDATORY)

Please confirm all of the following:

* [ ] Folder name matches the **card-id**
* [ ] All links are **relative**
* [ ] At least one preview image ending in `_ui.png` is included
* [ ] YAML is a **single, importable dashboard or card**
* [ ] No private or personal entity IDs are used
* [ ] Canonical semantics are preserved (`OK`, `Watch`, `Risk`, `Danger`)
* [ ] Canonical expander helper is used where applicable:
  `input_boolean.humidity_constellation_expanded`
* [ ] Required custom cards are documented in YAML comments
* [ ] UI works when copied into a clean Home Assistant instance
* [ ] Backend logic, helpers, and sensors are **not modified**

Submissions that break canonical assumptions may be rejected,
even if visually polished.

---

## 🔀 Branch & PR Requirements

* [ ] PR targets the **`develop` branch**
* [ ] PR title follows:
  `UI Gallery: <short description>`

PRs opened against `main` will be closed.

---

## 🧠 Design Intent (Optional but encouraged)

Briefly explain:

* What problem this UI helps solve
* What insight it prioritises
* Why this layout may be useful to others

---

## 🙏 Attribution

If this UI is inspired by existing work:

* Author(s) credited
* Source(s) linked where appropriate

---

Thank you for contributing.
**Clarity, consistency, and intent matter more than polish.**
