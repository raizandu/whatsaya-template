# Profile selection

Profiles are independent policy bundles. Enable only the bundles whose
assumptions match the target codebase.

| Profile         | Use when                                                                          | Avoid when                                                                                  |
| --------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `core`          | Strict TypeScript code needs stack-neutral safety and maintainability checks      | A specific rule conflicts with an established local contract; override that rule explicitly |
| `effect`        | Effect owns errors, services, Layers, collections, and runtime capabilities       | The source does not use Effect                                                              |
| `react`         | React components follow repository-wide export, composition, and state boundaries | The source tree is not React or follows a different state architecture                      |
| `xstate`        | XState owns component behavior and actor composition                              | Components use another explicit state model                                                 |
| `next-tailwind` | Next.js routing and a closed, project-owned Tailwind theme are configured         | Default theme tokens remain enabled or stylesheet, route, and UI ownership are not mapped   |
| `architecture`  | Service, repository, API, and UI boundaries are encoded as local paths/imports    | Those boundaries have not been mapped                                                       |

Profile selection is the starting point, not the complete configuration.
Path-sensitive rules require local options or file overrides. Severity and
all available options are in the
[bundled rule catalog](rule-catalog.md).

Type-aware rules are selected independently in a typed-lint config.
Workspace rules can inspect files that do not enter a TypeScript program.

The added-lines-only policy is separate from profiles and regular validation.
It is intended for review-time checks against a known base revision.
