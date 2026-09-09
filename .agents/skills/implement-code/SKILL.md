---
name: implement-code
description: Apply repository-neutral implementation judgment before changing application code and when reviewing completed code. Use for tasks that create, edit, delete, or reorganize code. Do not use for discussion, research, or diagnosis that does not include implementation.
---

# Implement code

Before deciding file placement or modifying code:

1. Identify the affected ownership boundaries and public contracts.
2. Read [the implementation rules](references/implementation-rules.md).
3. Read [the profile guidance](references/profiles.md), select only profiles
   whose assumptions match the repository, and consult the relevant entries in
   [the bundled rule catalog](references/rule-catalog.md).
4. Inspect neighboring code, services, state machines, utilities, and tests.
5. Decide how the change extends the existing structure before creating a new
   file or abstraction.

Rules express preferred direction, not permission for unrelated restructuring.
Use [technology guidance](references/technology-guidance.md) only for
technologies present in the target codebase.

## Automate before documenting

When a preference is deterministic, enforce it with types, lint, tests,
compilation checks, or diff alerts instead of adding another instruction.
Skills own contextual judgment only.

Run every locally reproducible verification boundary affected by the change.
Use available databases, containers, browsers, servers, and diagnostics to
verify end to end rather than delegating routine manual checks to a person.

When changing an automated rule in the upstream reference repository, follow
the matching [upstream recipe](https://github.com/typeonce-dev/ai-automation/tree/main/docs/recipes),
preserve positive and negative cases, and regenerate the catalog. When
extracting a pattern into another codebase, read
[the extraction guidance](references/extracting-patterns.md) to distinguish code
to copy from examples and guidance to adapt.
