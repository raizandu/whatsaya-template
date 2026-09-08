# Aya Platform · UI Kit (web)

High-fidelity, interactive recreation of the Aya web management shell. Built from `apps/platform-shell-app` and the shared component libs in `libs/shared/components/ui/*`.

**Open** `index.html` to explore. Components exposed to `window` for easy reuse across files.

## Components
- `Sidebar` — collapsible left rail with icon-only collapsed state
- `Topbar` — header with tenant switcher, notifications, profile menu
- `PageHeader` — screen title + subtitle + action buttons
- `KpiTile` — dashboard stat card (numeric, delta pill)
- `DataTable` — check-ins / members table with status badges
- `Modal` — center modal with standard header + footer
- `Button`, `Input`, `Select`, `Badge` — atoms

## Screens (click-through)
1. **Dashboard** — KPIs + recent check-ins
2. **Check-ins** — validate check-in flow with modal
3. **Members** — searchable member list
4. **Settings** — profile form

Note: this is a cosmetic recreation, not production code. Business logic is stubbed.
