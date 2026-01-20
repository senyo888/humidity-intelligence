

````md
## Contributing UI & Dashboards

Thank you for your interest in contributing to **Humidity Intelligence**.

This guide covers **UI, dashboard, and Lovelace layout contributions only**.  
Backend logic, sensors, and semantics are **out of scope**.

This repository is **HACS-facing**. Submissions are reviewed accordingly.

---

## 🎯 Scope (HACS-aligned)

The backend provides:

- Stable, documented sensors
- Canonical risk semantics
- Decision-ready signals

UI contributions explore **how that intelligence is presented**.

Visual creativity is welcome.  
**Structural consistency and canonical alignment are mandatory.**

---

## 🖼️ What you can contribute

You may submit:

- Full dashboards
- Individual cards
- Variants of the default UI
- Mobile / tablet / wall-panel layouts
- Experimental or unfinished designs (clearly marked)

Polish is optional.  
**Breakage, ambiguity, or undocumented assumptions are not.**

---

## 📁 UI Gallery submissions (IMPORTANT)

Due to **GitHub web UI limitations**, gallery submissions **must be prepared locally**.

Creating nested folders via the GitHub browser editor is not supported.

### Required process

1. Fork the repository
2. Create your gallery folder **locally**:

```text
/ui-gallery/<card-id>/
````

Example:

```text
/ui-gallery/default-lovelace-ui/
```

3. Include the following files:

```text
<card-id>_ui.png        (required)
<card-id>_ui.png         (if applicable)
<card-id>_dashboard.yaml       (required)
```

4. Commit and push the folder to your fork
5. Open a **Pull Request to the `develop` branch only**

PR title format:

```
UI Gallery: <short description>
```

PRs opened against `main` will be closed.

---

## 🧾 README.md — REQUIRED ENTRY FORMAT

Every submission **must** add an entry to `README.md`
using the **exact format below**.

Example:

```md
### **DEFAULT UI**
- Style: 4 badges-first, dropdown-mod, expands to humidity constellation
- Optimised for: Mobile / Tablet
- Author: @senyo888
- [![Collapsed UI Preview.png](default-lovelace-ui/default_ui.png)](default-lovelace-ui/default_ui.png)
- [View Expanded UI Preview.png](default-lovelace-ui/default_ui.png)
- [Default Dashboard.yaml](default-lovelace-ui/default_dashboard.yaml)
```

### Rules

* `card-id` **must exactly match the folder name**
* All links must be **relative**
* Images must be `.png`
* YAML must be a **single, importable dashboard or card**
* README entries are not optional

Submissions without a compliant README entry will be rejected.

---

## 🧩 Canonical compatibility rules (STRICT)

To meet **HACS and project standards**, all submissions must:

* Use **public, documented entity IDs only**
* Preserve **canonical semantics** (`OK`, `Watch`, `Risk`, `Danger`)
* Reuse shared helpers (e.g. expanders) where applicable
* Document all required custom cards
* Avoid hard-coded personal rooms, names, or layouts
* Avoid modifying backend logic or sensors
* Remain functional when copied into a clean Home Assistant instance

> If a submission breaks canonical behaviour or assumptions,
> **it is likely to be rejected**, regardless of visual quality.

---

## ✅ Pull Request checklist (REQUIRED)

Before opening a PR, confirm:

* [ ] Folder was created **locally**, not via GitHub web editor
* [ ] Folder name matches the `card-id`
* [ ] Required `.png` files are included
* [ ] YAML contains **no private entity IDs**
* [ ] Canonical entities and semantics are preserved
* [ ] Required custom cards are documented
* [ ] README.md entry follows the exact required format
* [ ] PR targets the `develop` branch
* [ ] PR title follows: `UI Gallery: <short description>`

PRs missing checklist items may be closed without revision.

---

## 🧠 Design intent

UIs should clearly help answer:

* Where is the risk?
* How serious is it?
* What should I do now?

If your UI improves understanding of a building’s moisture health,
it belongs here.

---

## 🙏 Credit & respect

If your UI is inspired by existing work:

* Credit authors
* Link to original sources where appropriate

---

Thank you for contributing.
**Consistency enables scale.**



