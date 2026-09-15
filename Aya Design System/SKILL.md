---
name: aya-design
description: Use this skill to create branded WhatsAya interfaces, dashboards, prototypes, and visual assets with the Aya palette, typography, components, and interaction rules.
user-invocable: true
---

Read `README.md` completely before creating or changing an Aya interface. Use
`colors_and_type.css` as the token source, inspect the relevant isolated example
in `preview/`, and reuse components from `ui_kits/aya-platform/` where practical.

Key rules:

- The only brand colors are orange `#F26E22`, beige `#F0E7DD`, green
  `#4CDE59`, and black `#070B0D`. Other states come from transparency or from
  the derived tones already in the token layer (`--primary-hover/active/edge/
  deep`, `--green-*`); never add a new hex.
- Text on orange and on green is black (`--primary-foreground`). Orange as text,
  link or focus ring on light uses `--primary-deep`.
- Use Open Sans for UI, Geist for numerics, and Aya only for display/brand use.
- Keep the header black in light and dark themes.
- Orange is the default primary action; green means WhatsApp, connection, or
  success. The `.whatsapp` context may promote green to primary.
- Wrap every form control in the label + field + hint/error structure shown in
  the input previews.
- Use Flaticon UIcons v3.3.1 regular-rounded (`fi fi-rr-*`).
- Never use ALL CAPS for headings. Only the 8px KPI eyebrow may be uppercase.
- Every surface declares an elevation level (`--shadow-hairline/xs/sm/md/lg/xl`
  paired with `--z-*`); shadows are tinted (`--shadow-tint`), never neutral
  black, and dark mode elevates by surface (`--surface-*`), not by shadow.
- Motion uses `--duration-*` and `--ease-*`; buttons press with
  `translateY(1px)`; popovers enter with scale(.96) from the trigger side.
- Do not introduce gradients, bounces, springs, decorative emoji, or raw colors
  outside the token layer.
