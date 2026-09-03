# TREM Review Rubric & Scoring Guide

A standardized grading rubric to evaluate code quality, categorize severity, and determine readiness for merge.

---

## 🚦 Status Indicators & Severity Levels

When reviewing code, assign a rating to each of the 4 pillars:

| Status | Meaning | Action Required |
| :---: | :--- | :--- |
| 🟢 **Pass** | Meets modern engineering standards. No major violations. | Ready to merge. Minor suggestions are optional. |
| 🟡 **Needs Work** | Contains code smells or anti-patterns that increase tech debt. | Should address recommendations before merge. |
| 🔴 **Blocker** | Severe architectural violation (e.g. untestable side-effects, god method, swallowed exceptions). | Must be refactored before proceeding. |

---

## 📋 Evaluation Matrix

### 1. Testability (T)

- 🟢 **Pass**:
  - All external dependencies (I/O, network, database, time, crypto) are injected.
  - Business logic is isolated from infrastructure.
  - 100% of branch logic can be unit-tested without network/DB mocks or monkey-patching.
- 🟡 **Needs Work**:
  - Some optional dependencies instantiated inline with default fallbacks.
  - Unit testing requires extensive mocking libraries or reflection.
- 🔴 **Blocker**:
  - Direct database/HTTP calls embedded in core business logic.
  - Global mutable state or static singletons preventing concurrent testing.

---

### 2. Readability (R)

- 🟢 **Pass**:
  - Clear, intent-revealing names conforming to domain terms.
  - Cognitive complexity is low: shallow nesting ($\le 2$ levels), guard clauses used.
  - Comments explain non-obvious business rules or performance trade-offs without restating code.
- 🟡 **Needs Work**:
  - 3-4 levels of nesting or overly dense inline boolean expressions.
  - A few vague names (`data`, `temp`, `res`).
- 🔴 **Blocker**:
  - Deep pyramid of doom ($\ge 5$ levels of indentation).
  - Obfuscated "clever" one-liners or misleading variable names.

---

### 3. Extensibility (E)

- 🟢 **Pass**:
  - Follows Open-Closed Principle: new variants can be plugged in via interfaces/strategies.
  - Uses composition over inheritance.
  - Zero tight coupling to third-party SDK types in domain layer.
- 🟡 **Needs Work**:
  - Switch/case branching used for variants, but isolated in a single factory.
- 🔴 **Blocker**:
  - Sprawling switch statements across multiple files to handle type variants.
  - Hardcoded vendor APIs directly intertwined with core domain rules.

---

### 4. Maintainability (M)

- 🟢 **Pass**:
  - Strict Single Responsibility Principle; functions are focused ($\le 30$ lines).
  - Explicit error handling with structured context; no silent failures.
  - Clear module boundaries with minimal blast radius.
- 🟡 **Needs Work**:
  - Functions doing slightly too much (40-60 lines) but still understandable.
  - Generic error messages without domain context.
- 🔴 **Blocker**:
  - Monolithic God object/function (>100 lines).
  - Catch-all exception blocks swallowing errors silently.
  - High risk of regression cascade across unrelated modules.
