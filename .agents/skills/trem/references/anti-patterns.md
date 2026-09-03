# TREM Anti-Patterns & Code Smells

A diagnostic catalog of common anti-patterns organized by the TREM pillar they violate.

---

## 1. Testability Anti-Patterns

### ❌ Hardcoded Dependency Instantiation (`new` Operator Abuse)
- **Symptom**: Functions instantiate third-party clients, database connectors, or HTTP clients directly inside method bodies.
- **Problem**: Impossible to test the method without connecting to a real external system.
- **Fix**: Pass dependencies through constructor or function parameters as interfaces.

### ❌ Hidden Global State & Singletons
- **Symptom**: Methods read from/write to global variables, static singletons, or environment variables mid-routine.
- **Problem**: Tests leak state into other tests, causing non-deterministic flakiness when tests run concurrently.
- **Fix**: Encapsulate configuration and state into instances passed explicitly.

### ❌ The "Untestable Time" Trap
- **Symptom**: Calling `new Date()` or `time.time()` deep in business logic.
- **Problem**: Cannot write deterministic unit tests for time-sensitive logic (e.g., expiration, billing cycles).
- **Fix**: Inject a `Clock` or `TimeProvider` interface, or pass `timestamp` as an explicit argument.

---

## 2. Readability Anti-Patterns

### ❌ The Pyramid of Doom (Arrow Anti-Pattern)
- **Symptom**: Deeply nested `if/else`, loops, and callback closures cascading 5+ indentation levels to the right.
- **Problem**: Mental stack overflow; developers lose track of which conditions must hold for execution.
- **Fix**: Invert conditions and use Guard Clauses with early returns.

### ❌ Cryptic & Disinformation Naming
- **Symptom**: Variables named `data`, `item`, `temp`, `x`, `arr`, `flag2`, or `mgr`.
- **Problem**: Requires reading the entire implementation to understand what a variable represents.
- **Fix**: Use domain-accurate, intent-revealing names (`pendingInvoices`, `isRetryLimitExceeded`).

### ❌ Parrot Comments
- **Symptom**: Comments that merely translate code syntax into English (e.g. `// set status to active: status = 'active'`).
- **Problem**: Noise that clutters the file without providing insight.
- **Fix**: Remove trivial comments. Only document non-obvious business requirements, edge cases, and architectural constraints.

---

## 3. Extensibility Anti-Patterns

### ❌ The Ever-Growing Type Switch
- **Symptom**: Giant `switch (type)` or `if (type === 'A') ... else if (type === 'B')` blocks duplicated across multiple files.
- **Problem**: Adding a new type requires modifying and re-testing every single switch block in the codebase (violates Open-Closed Principle).
- **Fix**: Polymorphism via Strategy Pattern, Factory maps, or Command dispatchers.

### ❌ Deep Class Inheritance Hierarchies
- **Symptom**: `class EnterpriseAuditLogBillingService extends BaseBillingService extends AbstractTransactionalService extends BaseEntityService`.
- **Problem**: "Fragile Base Class" problem—modifying a method in `AbstractTransactionalService` breaks unrelated subclasses.
- **Fix**: Refactor to composition: inject an `AuditLogger` and a `TransactionManager` into `BillingService`.

---

## 4. Maintainability Anti-Patterns

### ❌ The God Object / Monolithic Function
- **Symptom**: A single 800-line class or a 150-line function that validates inputs, calls database, sends emails, formats HTML, and logs metrics.
- **Problem**: Too many reasons to change; any modification introduces high risk of regression across unrelated features.
- **Fix**: Break apart into single-responsibility services, validators, and notification handlers.

### ❌ Swallowed Errors & Silent Failures
- **Symptom**: `try { ... } catch (e) { /* do nothing */ }` or returning `null` without indication of what failed.
- **Problem**: Disasters happen silently in production; debugging root cause becomes impossible.
- **Fix**: Throw meaningful typed domain errors, log with structured context, or return explicit Result/Either types.

### ❌ Shotgun Surgery
- **Symptom**: Making a single logical change (e.g., adding a field to `User`) requires modifying 12 different files across 4 folders.
- **Problem**: Indicates poor cohesion and lack of domain boundary encapsulation.
- **Fix**: Colocate related domain logic and encapsulate data representations behind domain models.
