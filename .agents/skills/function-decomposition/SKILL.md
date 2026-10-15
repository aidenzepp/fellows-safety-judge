---
name: function-decomposition
description: Use when writing, changing, or reviewing Python functions, methods, or substantial callbacks in this repository.
---

# Function Decomposition

Make each function easy to understand at a glance by giving it one coherent responsibility. Size, reuse, and line count never determine a boundary.

## Extract a Semantic Boundary

Extract a function only when all three conditions hold:

1. Its responsibility has a precise domain, framework, or library-standard name.
2. It owns one coherent decision, transformation, or operation with explicit inputs and a clear result or completion contract.
3. Its call site is simpler to understand than its implementation.

Re-evaluate the boundary as logic changes. A transparent expression may stay inline today and earn a function later when it accumulates policy such as discounts, jurisdictional taxes, states, or rounding.

Preserve evaluation order, validation order, and the order of externally visible actions such as persistence and notification when moving logic across boundaries unless a behavior change is explicitly requested.

## Preserve the Workflow Outline

A cohesive workflow is one responsibility even when it coordinates several operations. Keep direct dependency calls visible. Do not wrap an existing method or transparent expression merely to shorten the coordinator.

A coordinator should name independently identifiable internal stages instead of implementing their rules inline. Separate parsing, validation, transformation, calculation, and provider translation when each stage passes the three-part test.

## Keep Internals Local

- Put extracted helpers at module scope, not nested inside their consumer, and define them before their first consumer.
- Pass required values and capabilities explicitly instead of capturing parent state in a closure.
- Keep related helpers in the same file by default.
- Split a file only for another real consumer or a distinct domain, dependency, or runtime boundary.
- Mark a module-private helper with a leading underscore. Make a name public only for an actual external consumer: add no `__all__` or re-export without one, and add no barrel `__init__` re-exports. Decomposition never expands the module API by itself.
- Keep leaf callbacks with no independent responsibility inline (lambdas, nested functions, `key=` callbacks); apply the same extraction test when a callback gains one.

Follow established domain, framework, and library nomenclature instead of inventing synonyms.

## Name By The Repository Vocabulary

Every extracted helper is named under the owner's function-name rule, and `tests/test_naming_conventions.py` enforces it for module-level functions. The first underscore-separated word of the name, ignoring leading underscores, is one of `create`, `delete`, `update`, `remove`, `select`, `insert`, or `rename`.

- `select`, `insert`, `delete`, `update`, and `rename` perform I/O against a store or the environment: a file, database, network, environment variable, clock, or random source.
- `create` and `remove` are pure in-memory construction or derivation.

A boundary function that mixes I/O and pure derivation is usually two functions: a `select_` or `insert_` edge and a `create_` or `remove_` core. Split along that line only when each half passes the three-part extraction test. Domain nomenclature chooses the noun; this vocabulary chooses the leading verb.

## Labeled Examples

**REQUIRED REFERENCE:** Read [references/examples.md](references/examples.md) before making a function-boundary decision. Treat each `POSITIVE` and `NEGATIVE` label as acceptance data and follow its decisive evidence rather than copying its surface shape.

This skill owns function structure, not code documentation. Apply `document-code` separately.
