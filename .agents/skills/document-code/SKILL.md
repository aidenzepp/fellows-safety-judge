---
name: document-code
description: Use when writing or reviewing Python functions, methods, classes, pydantic models, enums, type aliases, module constants, private helpers, or other named program units, and when debugging, upstream documentation, source inspection, or experiments reveal a non-obvious constraint the code must preserve.
---

# Document Code

Make each program unit's contract and system role clear before a reader studies its implementation.

## Required coverage

Add a docstring to every module-scope function, class (pydantic models, enums, and exceptions included), PEP 695 `type` alias, and `Final` module constant. Also document every named private helper: `_name` functions and methods, and any named `def` nested in another function. Methods and `__init__` follow the same rule. Local values declared inside a function are not program units unless the declaration is itself a helper function.

Module constants and type aliases take an attribute docstring: a string literal on the line after the assignment or `type` statement ([PEP 257](https://peps.python.org/pep-0257/) names this form).

A class docstring owns the constructor contract of a dataclass-style model, such as a pydantic `BaseModel` or a dataclass, because its constructor is generated and its fields are the keyword arguments. A standalone domain or service type owns its own contract because callers consume that type directly.

Ruff enforces only public-API docstrings. Its D1xx rules require a docstring on each public module, package, class, function, method, and `__init__`; they skip underscore-private names and never inspect constants or aliases. Private-helper, constant, and alias coverage is therefore enforced by this skill and by review, not by lint. Once a function or class docstring exists, ruff checks its sections and form even on private helpers.

Tests are exempt: `pyproject.toml` ignores D100 through D104 under `tests/`, and tests state their contract in sentence-like test names.

## Format Every Docstring

Write Google-style docstrings. One sentence stays on one line; ruff D200 rejects a one-sentence docstring split across lines, and D212 requires a longer docstring's summary to start on the first line:

```python
MAXIMUM_USERNAME_LENGTH: Final = 32
"""The largest username accepted by the authentication boundary."""
```

Add `Args:`, `Returns:`, `Raises:`, `Attributes:`, and `Yields:` sections only when the contract needs them:

```python
def create_normalized_username(raw_text: str) -> str:
    """Create the comparison form of a username.

    Args:
        raw_text: The username exactly as entered by the person.

    Returns:
        The trimmed, lowercase username used for validation and uniqueness.
    """
    return raw_text.strip().lower()
```

Ruff's pydocstyle rules do not check attribute docstrings, so review keeps those to the same one-sentence shape. Keep every docstring line within 88 columns (ruff W505, which also covers attribute docstrings). Ruff skips a line that is a single unbroken URL, so a permalink in `See Also:` stays on one line.

## Write in the repository's voice

Follow `src/safety_judge/errors.py` and `src/safety_judge/settings.py`:

- Open with a direct, complete sentence that defines a type or states what a function does.
- Start functions with an active verb in the imperative, such as “Create,” “Select,” or “Insert.” Where it is natural, choose the verb the function's name starts with, from the vocabulary that `tests/test_naming_conventions.py` enforces.
- Start types with a definitional noun phrase such as “A short, trimmed name…” or “The deployment context…”.
- Add one concise follow-up only for a mental model, invariant, rationale, ecosystem fit, or ownership boundary.
- Describe the consumer-facing contract, not the implementation sequence.
- Reuse the exact vocabulary of the domain, framework, and underlying library, such as pydantic, pydantic-settings, and pytest.
- Put identifiers, setting names, and file names in double backticks, as those files do.
- Omit filler. A docstring that only expands the symbol's name is incomplete documentation.

## Preserve Consequential Knowledge

After debugging, reading documentation or upstream source, or running experiments reveals new knowledge, re-review the documentation on the affected code even when an existing docstring already looks complete.

Embed the knowledge when all three conditions hold:

1. It changes which implementation is correct, safe, or interoperable.
2. It is not apparent from the current code, types, or ordinary ecosystem knowledge.
3. A reasonable maintainer could remove the constraint or repeat costly discovery without it.

Write qualifying knowledge for a first-time reader:

1. State the program unit's current contract or role.
2. Give the causal chain as present facts: the governing invariant, why it requires the current design, and the guarantee that design provides.
3. Add navigation for the causal chain: name a local owning symbol in `See Also:` when the relationship crosses a module boundary, link canonical documentation for public behavior, and link pinned upstream source when exact implementation matters.

The explanation must stand alone without knowledge of past implementations or the incidents, prior defaults, successes, and failures that led to it. Translate discovery history into present-tense invariants; do not write “previously,” “this fixes,” “after this failed,” or similar chronology.

Put the knowledge in the smallest owning program unit's docstring. Use an inline `#` comment only when the constraint belongs to one statement or to execution order and moving it outward would obscure the relationship.

Do not add a knowledge comment when the code or types already make the fact clear, when another skill or lint rule owns the policy, or when the information is only temporary debugging evidence. Those comments add maintenance cost without improving understanding.

## Apply sections by contract

| Program unit | Required documentation |
| --- | --- |
| Function, method, or named private helper | An `Args:` entry for every argument except `self` and `cls`, with `*args` and `**kwargs` described by name (ruff D417 rejects a missing description), and a `Returns:` section for its semantic result (ruff DOC201 requires it when the function returns a value, and DOC202 rejects it when the function does not). |
| Generator | A `Yields:` section for what each iteration produces (ruff DOC402 requires it, and DOC403 rejects it on a function that does not yield). |
| Dataclass-style model, such as a pydantic model | The class docstring owns the constructor contract. Do not describe the generated constructor a second time. |
| Standalone domain, service, or library class, including an enum | The class docstring defines the whole contract. Document every callable member with its arguments and semantic result. Add an `Attributes:` entry for a data attribute or enum member only when it adds a constraint, invariant, or domain meaning that the class docstring does not already establish. |
| Standalone callback type | Describe the capability or intent. For a `Protocol` with `__call__`, document the arguments and completion on `__call__`. For a `Callable[...]` alias, say in the attribute docstring what each argument means and what completion guarantees, because an alias has no `Args:` section. |
| Module-scope constant or type alias | In an attribute docstring, state the invariant, policy, shared consumers, or system role that the value establishes. |
| Overloaded function | Ruff D418 rejects a docstring on an `@overload` stub, so the implementation's docstring is the one place callers read. Leave the stubs bare. In that docstring, describe each public form whose contract differs: what it accepts, what it returns, and what it raises. Document the forms, not the implementation's union signature. |

For a function that returns `None`, omit `Returns:`, because DOC202 rejects the section when no value is returned. Describe a meaningful completion guarantee in the description instead, such as what later reads can observe once an awaited call returns.

Document each fact once at the surface that owns it. For a model with a generated constructor, that is the class docstring. For a standalone class, that is the class and its non-obvious members, not every function that happens to accept it.

For a parameter that is itself a mapping or structured object, its `Args:` entry defines the object as a whole and names the keys that matter; do not add a second description elsewhere. Overloads differ when they accept different representations, return different guarantees, or expose different failures. State a shared invariant once in the description, and repeat it for a form only when callers of that form need it.

Use optional sections only when their condition holds:

- `See Also:` and inline references to `module.symbol` for a useful relationship to a real program unit, composition, counterpart, or protocol.
- `Example:` for non-obvious public usage, with one focused, valid snippet in a fenced `python` block and no `>>>` doctest prompts.
- `Raises:` for each failure the function raises on purpose and the condition that causes it. Ruff DOC501 requires an entry for every exception the body raises explicitly, and DOC502 rejects an entry for an exception the body does not raise itself, so describe a failure that only propagates from a callee in a prose sentence instead.
- Deprecation only for a deprecated unit: apply the `warnings.deprecated` decorator, and add a docstring sentence that names the supported replacement with a `See Also:` entry pointing at it.

Do not repeat annotations in prose or add sections with no information; Google-style entries omit types because the signature owns them. Small private helpers still receive a concise purpose plus applicable `Args:` and `Returns:` sections; they do not receive optional sections by default.

## Cite Authoritative Sources

Add `See Also:` links whenever a reader would otherwise need to rediscover the external rule behind the code. Common triggers include library behavior, provider configuration, protocol requirements, version-specific values, compatibility constraints, and adaptations of an upstream primitive.

- Link canonical documentation for the supported public behavior.
- Also link a versioned source permalink when the exact implementation or emitted value matters.
- Name a repository unit in double backticks, with its module path when it lives elsewhere, for a useful relationship to another unit.
- Place the link on the smallest unit that owns the sourced behavior; for a constant or alias, that is its attribute docstring.
- Omit generic homepages and links that add nothing beyond an import or parameter annotation.

## Labeled Examples

**REQUIRED REFERENCE:** Read [references/examples.md](references/examples.md) before writing or reviewing code documentation. Treat each `POSITIVE` and `NEGATIVE` label as acceptance data: reproduce the documented contract quality, not merely the docstring shape.

## Review

Confirm every required unit, including each private helper, constant, and alias, and every argument is documented; generated-constructor models keep their contract on the class docstring and do not duplicate it; standalone classes retain their own contracts; one-sentence docstrings sit on one line and every line fits within 88 columns; sections follow the unit's contract; overloaded functions describe each public form in the implementation's docstring; authoritative links sit beside sourced behavior; and references resolve to useful relationships. After learning a non-obvious constraint, confirm the owning docstring captures its present-tense causal chain for a first-time reader. Reject docstrings that narrate syntax, duplicate annotations, merely restate names, recount implementation history, or repeat policy already enforced elsewhere. Run `ruff check` and `ruff format --check`; they verify public docstrings and section completeness, so the review covers what they skip: private helpers, constants, aliases, and whether each docstring says anything the name does not.
