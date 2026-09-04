# TREM Code Review & Refactoring Walkthrough

An end-to-end practical demonstration showing how problematic code is audited against the TREM framework and refactored into modern, production-grade code.

---

## 🚩 The Target Code (Before TREM)

Consider this TypeScript order processing service:

```typescript
// Legacy OrderProcessor.ts
import { PostgresClient } from './db';
import axios from 'axios';

export class OrderProcessor {
  public async process(orderData: any): Promise<any> {
    // Check if orderData exists
    if (orderData) {
      if (orderData.items && orderData.items.length > 0) {
        if (orderData.paymentMethod === 'CREDIT_CARD' || orderData.paymentMethod === 'PAYPAL' || orderData.paymentMethod === 'CRYPTO') {
          const db = new PostgresClient();
          await db.connect();
          
          let total = 0;
          for (let i = 0; i < orderData.items.length; i++) {
            total += orderData.items[i].price * orderData.items[i].qty;
          }

          // Apply discount if weekend
          const today = new Date();
          if (today.getDay() === 0 || today.getDay() === 6) {
            total = total * 0.9; // 10% off
          }

          try {
            if (orderData.paymentMethod === 'CREDIT_CARD') {
              await axios.post('https://api.stripe.com/v1/charges', { amount: total, token: orderData.token });
            } else if (orderData.paymentMethod === 'PAYPAL') {
              await axios.post('https://api.paypal.com/v2/checkout/orders', { amount: total });
            } else if (orderData.paymentMethod === 'CRYPTO') {
              await axios.post('https://api.coinbase.com/v2/charges', { amount: total });
            }
            
            await db.query('INSERT INTO orders (id, total, status) VALUES ($1, $2, $3)', [orderData.id, total, 'PAID']);
            return { success: true, total };
          } catch (err) {
            // handle error
            return null;
          }
        } else {
          throw new Error('bad payment');
        }
      } else {
        throw new Error('no items');
      }
    } else {
      throw new Error('no order data');
    }
  }
}
```

---

## 🔍 The TREM Review Report

# 🛡️ TREM Code Review Report

## Executive Summary
The `OrderProcessor` contains significant architectural risks across all 4 pillars. It tightly couples database connections and external HTTP payment gateways inside business logic, relies on static `new Date()` calls, suffers from deep nesting (arrow anti-pattern), uses hardcoded type branching, and swallows payment failures silently.

## 📊 TREM Scorecard

| Pillar | Status | Key Observations |
| :--- | :---: | :--- |
| **Testable** | 🔴 **Blocker** | Instantiates `PostgresClient`, calls live HTTP endpoints via `axios`, and calls `new Date()`. Cannot be unit tested without real DB & network. |
| **Readable** | 🔴 **Blocker** | 4 levels of nested `if` statements (Pyramid of Doom), `any` types throughout, cryptic variable names (`qty`, `err`). |
| **Extensible** | 🔴 **Blocker** | Violates Open-Closed Principle. Adding a new payment method requires modifying the core processing loop and adding another `else if` branch. |
| **Maintainable** | 🔴 **Blocker** | God method handling validation, calculation, discount rules, payment dispatch, and DB persistence. Silent error swallow on payment failure. |

---

## 🔍 Detailed Findings & Recommendations

### 1. Testability (T)
- 🚨 **Direct DB & HTTP Instantiation** (Lines 10, 24-30): Hardcoded `new PostgresClient()` and `axios.post()` prevent isolated unit testing.
  - **Remediation**: Inject `OrderRepository`, `PaymentGatewayStrategy`, and `Clock` through constructor.
- ⚠️ **Non-deterministic Time** (Line 18): `new Date()` makes weekend discount testing non-deterministic.
  - **Remediation**: Abstract time provider or pass current timestamp to discount calculator.

### 2. Readability (R)
- 🚨 **Pyramid of Doom** (Lines 7-38): Deep nested `if/else` checks.
  - **Remediation**: Use Guard Clauses (early returns) for validation upfront.
- 💡 **Type Safety & Magic Strings** (Lines 5, 9): Uses `any` type and untyped string literals.
  - **Remediation**: Define explicit domain interfaces (`Order`, `OrderItem`, `PaymentMethod`).

### 3. Extensibility (E)
- 🚨 **Payment Type Branching** (Lines 23-29): Hardcoded `if/else` on payment methods.
  - **Remediation**: Implement the **Strategy Pattern** with `PaymentGateway` interface and a registry/factory.

### 4. Maintainability (M)
- 🚨 **Swallowed Exceptions** (Lines 34-37): `catch (err) { return null; }` loses stack trace and failure context.
  - **Remediation**: Throw typed domain exceptions (`PaymentFailedException`) with error details.
- ⚠️ **Violates Single Responsibility Principle**: The class does 5 distinct things.
  - **Remediation**: Separate into `OrderValidator`, `PricingService`, `PaymentService`, and `OrderRepository`.

---

## 🚀 Refactored Implementation (TREM Compliant)

```typescript
// ==========================================
// 1. Domain Types & Contracts (Readability & Extensibility)
// ==========================================
export interface OrderItem {
  readonly id: string;
  readonly price: number;
  readonly quantity: number;
}

export type PaymentMethod = 'CREDIT_CARD' | 'PAYPAL' | 'CRYPTO';

export interface Order {
  readonly id: string;
  readonly items: readonly OrderItem[];
  readonly paymentMethod: PaymentMethod;
  readonly paymentToken?: string;
}

export interface ProcessedOrderResult {
  readonly orderId: string;
  readonly total: number;
  readonly status: 'PAID';
}

// ==========================================
// 2. Extensible Strategy Pattern for Payments (Extensibility & Testability)
// ==========================================
export interface PaymentGateway {
  supports(method: PaymentMethod): boolean;
  charge(amount: number, token?: string): Promise<{ transactionId: string }>;
}

export class PaymentGatewayRegistry {
  constructor(private readonly gateways: readonly PaymentGateway[]) {}

  public getGateway(method: PaymentMethod): PaymentGateway {
    const gateway = this.gateways.find((g) => g.supports(method));
    if (!gateway) {
      throw new Error(`Unsupported payment method: ${method}`);
    }
    return gateway;
  }
}

// ==========================================
// 3. Isolated Dependencies & Contracts (Testability & Maintainability)
// ==========================================
export interface OrderRepository {
  save(orderId: string, total: number, status: string): Promise<void>;
}

export interface Clock {
  now(): Date;
}

export class SystemClock implements Clock {
  public now(): Date {
    return new Date();
  }
}

// ==========================================
// 4. Pure Business Logic (Readability & Maintainability)
// ==========================================
export class PricingService {
  constructor(private readonly clock: Clock) {}

  public calculateTotal(items: readonly OrderItem[]): number {
    const subtotal = items.reduce((sum, item) => sum + item.price * item.quantity, 0);
    
    // Weekend promotion: 10% discount on Saturday (6) and Sunday (0)
    const dayOfWeek = this.clock.now().getDay();
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
    
    return isWeekend ? Number((subtotal * 0.9).toFixed(2)) : subtotal;
  }
}

// ==========================================
// 5. Orchestrator Service (TREM Compliant)
// ==========================================
export class OrderProcessor {
  constructor(
    private readonly pricingService: PricingService,
    private readonly paymentRegistry: PaymentGatewayRegistry,
    private readonly orderRepository: OrderRepository
  ) {}

  public async process(order: Order): Promise<ProcessedOrderResult> {
    // Guard Clauses: Flat, readable validation (Readability)
    this.validateOrder(order);

    // Calculate pure domain total (Testable & Maintainable)
    const total = this.pricingService.calculateTotal(order.items);

    // Resolve strategy and execute payment (Extensible & Testable)
    const gateway = this.paymentRegistry.getGateway(order.paymentMethod);
    try {
      await gateway.charge(total, order.paymentToken);
    } catch (error) {
      // Structured error propagation (Maintainability)
      throw new Error(`Payment processing failed for order ${order.id}: ${(error as Error).message}`);
    }

    // Persist via injected repository (Testable)
    await this.orderRepository.save(order.id, total, 'PAID');

    return {
      orderId: order.id,
      total,
      status: 'PAID'
    };
  }

  private validateOrder(order: Order): void {
    if (!order) {
      throw new Error('Order payload is required');
    }
    if (!order.items || order.items.length === 0) {
      throw new Error('Order must contain at least one item');
    }
  }
}
```
