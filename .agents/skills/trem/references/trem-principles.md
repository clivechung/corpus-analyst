# TREM Principles In-Depth: Modern Engineering Standards

This document establishes the technical benchmarks and architectural patterns that define the **TREM** framework.

---

## 1. Testability (T)

Testable code is code whose correctness can be verified in isolation quickly, deterministically, and with minimal test setup ceremony.

### Core Principles & Standards

1. **Dependency Inversion & Injection (DI)**
   - High-level modules must not instantiate low-level dependencies directly (`new DatabaseConnection()`, `fetch()`, `fs.readFile()`).
   - All I/O, storage, network, and external systems must be injected via constructors, factory parameters, or container mechanisms.
   - **Benefit**: Enables fast in-memory unit tests using mocks/stubs without spinning up external infrastructure.

2. **Temporal & Non-Deterministic Decoupling**
   - System clock (`Date.now()`, `time.time()`), random number generators, and environment variables should be abstracted or passed as parameters.
   - Tests must not rely on `sleep()` or non-deterministic race conditions.

3. **Separation of Pure Logic from I/O (Hexagonal / Ports & Adapters)**
   - Domain logic and business rules should be pure functions whenever possible (Input $\to$ Transformation $\to$ Output).
   - Side effects (I/O, database writes, message publishing) should be pushed to the boundaries of the application.

4. **Observability & Assertion Clarity**
   - Functions should produce observable outcomes: return values, state changes, or explicit typed errors rather than silent internal mutations.

---

## 2. Readability (R)

Readable code reduces the cognitive load required for another engineer (or an AI agent) to understand the system's intent, control flow, and edge case handling.

### Core Principles & Standards

1. **Intention-Revealing Naming**
   - Names must reflect *domain concepts* and *intent*, not data types or generic terms (`processData` $\to$ `calculateMonthlyInterestRates`).
   - Booleans must be phrased as predicates (`isValid`, `hasPermission`, `canRetry`).

2. **Low Cognitive Complexity & Flat Control Flow**
   - Avoid deep nesting (maximum 2-3 levels).
   - Use **Guard Clauses (Early Returns)** to handle edge cases, validations, and preconditions upfront before executing the happy path.
   - Avoid nested ternary expressions, long chained methods without line breaks, and confusing double negatives.

3. **Explanatory Comments: The *Why*, Not the *What***
   - **Do NOT** explain what the code already says (`// increment counter: i++`).
   - **DO** document the non-obvious rationale: business domain constraints, edge-case workarounds, performance trade-offs, bug fixes with issue tickets, or complex mathematical formulas.

4. **Self-Documenting Type Contracts**
   - Use strict typing (TypeScript, Python type hints, Go structs, Java/C# generics) with descriptive custom types/enums rather than primitive obsession (`string` everywhere).

---

## 3. Extensibility (E)

Extensible code accommodates new features and changing requirements with minimal modifications to existing, tested code.

### Core Principles & Standards

1. **Open-Closed Principle (OCP)**
   - Modules should be open for extension, but closed for modification.
   - Adding a new capability (e.g., a new notification channel, a new export format, a new payment provider) should be done by adding a new class/module implementing an interface, not by adding another branch to a 50-line `switch` statement.

2. **Composition Over Inheritance**
   - Favor object composition, functional pipelines, and mixins over deep class inheritance hierarchies.
   - Deep inheritance creates brittle base classes where changes unintentionally break subclasses.

3. **Modern Behavioral & Structural Design Patterns**
   - **Strategy Pattern**: Interchangeable algorithms or business policies.
   - **Adapter Pattern**: Translating third-party or legacy APIs into domain contracts.
   - **Factory / Builder Pattern**: Separating object construction complexity from usage.
   - **Middleware / Pipeline Pattern**: Composing cross-cutting concerns (auth, logging, validation, rate limiting).

4. **Loose Coupling via Interfaces**
   - Depend on abstract contracts/interfaces rather than concrete implementations.
   - Keep interfaces narrow and role-focused (Interface Segregation Principle).

---

## 4. Maintainability (M)

Maintainable code is easy to refactor, debug, and evolve over years without creating regression cascades or "shotgun surgery."

### Core Principles & Standards

1. **Single Responsibility Principle (SRP) & High Cohesion**
   - Each module, class, and function should have one, and only one, reason to change.
   - Keep functions focused (typically 10-30 lines) and cohesive.

2. **Small Blast Radius & Encapsulation**
   - Internal state and implementation details must be private/encapsulated.
   - Changing the internal data structure of a service should not break consumers across the codebase.

3. **Structured & Predictable Error Handling**
   - Never swallow exceptions silently (`catch (e) {}` with no logging or recovery).
   - Use typed custom error classes or Result envelopes (`Ok(val)` / `Err(e)`).
   - Distinguish operational errors (transient network failure, bad user input) from programmer errors (null pointer, assertion failure).

4. **DRY vs AHA (Avoid Hasty Abstractions)**
   - Eliminate genuine structural duplication, but do not prematurely abstract two pieces of code that happen to look similar today but have different reasons to change.
