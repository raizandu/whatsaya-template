# Extracting a pattern

Use the repository as a source of focused patterns, not as a template to copy
wholesale.

## 1. Classify the artifact

- **Copy:** executable rule implementations and their behavioral tests.
- **Copy and adapt:** configuration, discovery globs, path-sensitive options,
  test policy, and smoke checks.
- **Reference:** catalog generation, profile rationale, and implementation
  guidance.

Before copying prose, ask whether the target codebase can enforce the preference
with a type, lint rule, test, compilation check, or diff alert. Prefer the
executable form.

## 2. Select the smallest applicable slice

Start from the goal rather than the folder tree. A syntax rule normally needs
its rule file, registry entry, metadata, profile assignment, and positive and
negative tests. A typed rule also needs the engine interfaces and project
discovery that supply its type information. A testing pattern needs the
relevant factory or example config, not every testing technology shown here.

## 3. Replace local assumptions

Review import allowlists, directory names, route conventions, stylesheet
entries, project globs, exclusions, environment files, and command names.
Path-sensitive rule options are listed in the
[bundled catalog](rule-catalog.md).

For Tailwind, adapting the stylesheet includes retaining `--*: initial;`,
defining only target-owned tokens, and preserving a negative compilation probe
that proves defaults remain unavailable.

## 4. Preserve observable behavior

Move positive and negative cases with a rule. For command-line tools, preserve
configuration errors, normalized output, sorting, deduplication, and exit
statuses. For testing patterns, keep unit, integration, and browser boundaries
explicit.

Ensure the agent can run those boundaries locally. A copied check that still
depends on manual setup does not provide end-to-end verification.

## 5. Reconnect local ownership

Place copied code beside the target codebase’s existing lint or test ownership.
Extend its current configuration and naming. Do not reproduce this repository’s
top-level layout unless it also fits the target.
