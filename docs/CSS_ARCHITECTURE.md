# CSS Architecture Documentation

This document describes the CSS architecture and design system of the SpaManager v3.9 application.

## 1. Directory Structure

```text
static/css/
├── theme.css                   # Design Tokens (CSS Variables)
├── layout.css                  # Sidebar, Topbar, Main Content Layout
├── base-page.css               # Core base page classes & global resets
├── shared-table.css            # Standardized styling for data tables & search boxes
├── base/
│   └── motion.css              # Transitions, Hover animations, page loader
├── components/
│   ├── command-palette.css     # Command Palette (Omnibar) dropdown styles
│   ├── notification.css        # Unified Notification Toast styles
│   └── skeleton.css            # Loading skeleton placeholder styles
└── pages/                      # Page-specific styles & overrides
    ├── activity-log.css
    ├── appointment.css
    ├── appointment-calendar.css
    ├── backup-center.css
    ├── dashboard.css
    ├── layout-spacing.css
    ├── recycle-bin.css
    ├── setting.css
    └── statistics.css
```

---

## 2. Design Tokens (theme.css)

All files MUST consume color, spacing, radius, and elevation properties from the centralized variables declared in `theme.css`:

### Color Tokens
* **Brand Primary**: `var(--spa-primary)` (`#a67c52`) - consumed by main buttons, active links, primary text headers.
* **Success**: `var(--spa-success)` (`#2ec4b6`) - consumed by completed appointments, invoice paid states.
* **Danger**: `var(--spa-danger)` (`#e71d36`) - consumed by cancelled appointments, delete buttons, recycle bin.
* **Warning**: `var(--spa-warning)` (`#ff9f1c`) - consumed by pending states, alerts.
* **Info**: `var(--spa-info)` (`#00b4d8`) - consumed by statistics cards, helper links.

### Semantic Tints & Borders
* `var(--spa-info-light)` - `rgba(0, 180, 216, 0.08)`
* `var(--spa-info-border)` - `rgba(0, 180, 216, 0.15)`
* `var(--spa-success-border)` - `rgba(46, 196, 182, 0.15)`
* `var(--spa-warning-border)` - `rgba(255, 159, 28, 0.15)`
* `var(--spa-danger-border)` - `rgba(231, 29, 54, 0.15)`

---

## 3. Z-Index Layer Hierarchy

We standardize z-indices to prevent random overlapping elements:

| Variable | Value | Description |
| :--- | :--- | :--- |
| `--z-index-dropdown` | `1000` | Dropdown menus (`.status-dropdown`) |
| `--z-index-sticky` | `1020` | Sticky navigation elements |
| `--z-index-fixed` | `1030` | Fixed headers or sidebars |
| `--z-index-modal-backdrop` | `1040` | Backdrop of Bootstrap modal overlays |
| `--z-index-modal` | `1050` | Modal dialogue boxes |
| `--z-index-popover` | `1060` | Tooltips, popovers (`.cal-popover`, `.select2-dropdown`) |
| `--z-index-toast` | `1090` | Toast notifications (`.toast-container`) |
| `--z-index-command-palette` | `2000` | Omnibar search overlay (`.command-palette-overlay`) |
| `--z-index-loader` | `9999` | Page transition overlay (`.page-loader`) |

---

## 4. Responsive Breakpoints

We consume Bootstrap 5's standard breakpoints using CSS media queries:

* **Mobile Portait / Landscape**: `@media (max-width: 767.98px)`
* **Tablets / Medium Screens**: `@media (min-width: 768px) and (max-width: 991.98px)`
* **Desktops / Large Screens**: `@media (min-width: 992px)`
