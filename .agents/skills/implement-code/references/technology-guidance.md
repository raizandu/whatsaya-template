# Opt-in technology guidance

Apply a section only when its technology and architectural style already exist
in the target codebase.

## Effect

Put each invariant in the Effect service that owns it. Compose reusable Layers
on the owning service or module so memoization works across the graph. Provide
dependencies near the service, endpoint group, job, or runtime unit that
consumes them.

Group independent Layer dependencies in one provision step. Use staged
provision only when one Layer needs another Layer's output. Keep structured
errors in the Effect error channel and sanitize them at public boundaries.

## XState and React

Keep React components focused on rendering a machine snapshot and sending
events. State transitions, validation, data transformation, asynchronous work,
and coordination belong in events, actions, guards, actors, and selectors.

Framework-required hooks may acquire a router, ref, or transition capability.
Pass the capability into the machine through input or an established actor
boundary; keep decisions in the machine.

Extend an existing machine when it owns the same flow or lifecycle. Create a
machine or actor for an independent lifecycle or clear composition boundary,
not for static rendering. Test behavior through actors, events, snapshots, and
outputs.

## React and Next.js

Use server-rendered components for static content and data access when the local
application supports them. Introduce a client boundary for browser APIs,
interactivity, or client-owned state, and keep that boundary as focused as the
feature permits.

Keep page-specific behavior with the page, shared route structure in the nearest
layout, and application-wide UI only in an established shared owner.

## Tailwind CSS

Start the theme with `--*: initial;` to remove every default theme token. Define
only the colors, spacing, typography, radii, breakpoints, shadows, and other
values owned by the target design system.

Prefer those custom tokens and established utilities. Keep class composition in
the approved helper, and configure that helper name explicitly in formatting
and lint profiles. Reject alternate styling paths such as JSX `style`, unknown
or arbitrary classes, and native interactive elements outside the approved
component library.

Compile the stylesheet and assert that representative custom utilities exist
and representative default utilities do not. Treat stylesheet entry points as
target configuration rather than layout assumptions.
