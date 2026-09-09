# Implementation rules

These guidelines cover implementation judgment that static checks cannot
reliably enforce. Prefer a coherent established local pattern over an isolated
new abstraction.

## Extend existing ownership

Before creating a file, function, service, utility, formatter, or abstraction,
inspect the relevant application and shared packages for an existing owner.

Keep route-specific loading and one-use behavior at the usage site when it
remains legible. Extend an existing utility or formatter when it has the same
ownership and audience. Avoid thin forwarding modules that merely shorten a
caller, and do not move application-specific behavior into a shared package for
a single use.

Operations belong to the service that owns the capability. Extend that service
instead of accumulating standalone operations or creating a parallel service.
Create a service only for a distinct responsibility with a meaningful boundary.

Separate files are appropriate for cohesive shared schemas, utilities,
formatters, services, runtime infrastructure, configuration, and other
established local categories.

## Choose meaningful UI and route boundaries

Inline one-use presentational markup when it is clearer at the call site. A
separate component is justified by reuse, a server/client boundary, an
independent state lifecycle, or a substantial screen or feature boundary, not
merely file length.

Keep static server-rendered page content in its route. Use the nearest route
layout for structure stable across descendants; keep page-specific or
client-state-driven regions in their owning page or client component.

Use separate routes for distinct user flows. Use search parameters for steps,
filters, or state within one flow.

## Preserve contract and service boundaries

Public schemas describe public requests, responses, middleware, and errors.
Keep persistence records, secrets, authorization state, job data, and other
internal models beside the feature that owns them. Share public scalars or enums
only when they represent the same contract.

Put each invariant in the service that owns it. Other services should call that
service rather than reproduce normalization, defaults, authorization, conflict
handling, or persistence coordination.

Transport handlers should decode input, read request context, call the owning
service, and translate its result into the public contract. Domain orchestration
belongs in the service.

## Keep public failures stable

Preserve structured errors inside repositories and services. At a public
boundary, map expected domain errors and translate internal failures into
stable, sanitized errors.

Never expose database errors, parser details, upstream response bodies, secrets,
or incidental exception messages. Record useful diagnostic detail only in
trusted internal telemetry.

## Finish ownership changes

When behavior moves to a focused service or route, remove obsolete operations
and state from the previous owner after confirming nothing depends on them.
Avoid dormant duplicate implementations that can diverge.

## Test meaningful behavior

Add or update a locally reproducible test when a change affects decisions,
invariants, transitions, authorization, calculations, transformations, error
behavior, or another externally observable rule.

Exercise public service operations through observable results. Test stateful
behavior through events, snapshots, and outputs. Do not export internals solely
for testing.

Use unit tests for focused decisions, integration tests for real boundaries and
resource behavior, and browser tests for meaningful user flows. Let the agent
own local resource startup, teardown, browser control, and failure evidence
whenever those operations are reproducible.

Skip trivial wiring and behavior already guaranteed by a library. Follow nearby
test structure and extend existing fixtures or test files when they own the same
subject. Tests must not depend on production state, manual setup, execution
order, or unavailable external systems.
