# Function Decomposition Examples

Use these examples as labeled acceptance data. The text immediately above each snippet states the evidence that determines its label.

Every snippet is a complete excerpt from a module whose imports and referenced types are defined immediately above it. Surrounding imports and types are identical across each comparison and are intentionally omitted. The examples follow the repository's `document-code` contract so decomposition is the only labeled axis.

## Workflow outline

### NEGATIVE — One function implements every stage of a cohesive workflow

**Decisive evidence:** `insert_placed_order` coordinates the workflow while also implementing input parsing, line validation, catalog lookup, pricing, and aggregation. Calling the overall workflow cohesive does not make those internal rules one responsibility.

```python
async def insert_placed_order(
    order_input: OrderInput,
    dependencies: OrderDependencies,
) -> Order:
    """Place an order from submitted customer and line-item values.

    Args:
        order_input: The unvalidated values submitted for the order.
        dependencies: The pricing, persistence, and receipt capabilities.

    Returns:
        The persisted order after its receipt has been sent.

    Raises:
        InvalidValueError: When the submitted values or catalog prices are invalid.
    """
    customer_identifier = order_input.customer_identifier.strip()

    if not customer_identifier or not order_input.lines:
        message = (
            "An order requires a customer and at least one line. "
            "Add both before submitting."
        )
        raise InvalidValueError(
            message,
            context={"line_count": len(order_input.lines)},
        )

    priced_lines: list[PricedLine] = []
    for line in order_input.lines:
        if line.quantity < 1:
            message = (
                f"Order quantities must be positive integers, but {line.sku} has "
                f"{line.quantity}. Correct the quantity."
            )
            raise InvalidValueError(
                message,
                context={"sku": line.sku, "quantity": line.quantity},
            )

        unit_price = dependencies.prices.get(line.sku)

        if unit_price is None:
            message = (
                f"No catalog price exists for {line.sku}. "
                "Add the product to the catalog or remove the line."
            )
            raise InvalidValueError(message, context={"sku": line.sku})

        priced_lines.append(
            PricedLine(
                sku=line.sku,
                quantity=line.quantity,
                unit_price=unit_price,
                subtotal=line.quantity * unit_price,
            ),
        )

    total = sum(line.subtotal for line in priced_lines)
    order = await dependencies.orders.insert_order(
        PricedOrder(
            customer_identifier=customer_identifier,
            lines=tuple(priced_lines),
            total=total,
        ),
    )

    await dependencies.receipts.insert_receipt(order)

    return order
```

### POSITIVE — The coordinator reads as the workflow outline

**Decisive evidence:** `_create_order_draft` owns order-level normalization and validation, while `_create_priced_order` owns line validation, catalog pricing, and aggregation. Keeping quantity validation beside each line's catalog lookup preserves the original error order. Both helpers have precise contracts and simpler call sites. `insert_placed_order` retains the direct persistence and receipt operations, in their original order, because coordinating them is its responsibility. The helpers are module-private, stay in the same file, and take every value they use as an argument; only the coordinator is public.

```python
def _create_order_draft(order_input: OrderInput) -> OrderDraft:
    """Normalize and validate the order-level submitted values.

    Args:
        order_input: The unvalidated values submitted for the order.

    Returns:
        An order draft with a normalized customer identifier.

    Raises:
        InvalidValueError: When the order lacks a customer or lines.
    """
    customer_identifier = order_input.customer_identifier.strip()

    if not customer_identifier or not order_input.lines:
        message = (
            "An order requires a customer and at least one line. "
            "Add both before submitting."
        )
        raise InvalidValueError(
            message,
            context={"line_count": len(order_input.lines)},
        )

    return OrderDraft(
        customer_identifier=customer_identifier,
        lines=order_input.lines,
    )


def _create_priced_order(
    draft: OrderDraft,
    prices: Mapping[str, int],
) -> PricedOrder:
    """Validate and apply catalog prices to every submitted order line.

    Args:
        draft: The normalized order awaiting prices.
        prices: The catalog price indexed by product identifier.

    Returns:
        The priced lines and their combined total.

    Raises:
        InvalidValueError: When a quantity is invalid or a product has no catalog
            price.
    """
    priced_lines: list[PricedLine] = []
    for line in draft.lines:
        if line.quantity < 1:
            message = (
                f"Order quantities must be positive integers, but {line.sku} has "
                f"{line.quantity}. Correct the quantity."
            )
            raise InvalidValueError(
                message,
                context={"sku": line.sku, "quantity": line.quantity},
            )

        unit_price = prices.get(line.sku)

        if unit_price is None:
            message = (
                f"No catalog price exists for {line.sku}. "
                "Add the product to the catalog or remove the line."
            )
            raise InvalidValueError(message, context={"sku": line.sku})

        priced_lines.append(
            PricedLine(
                sku=line.sku,
                quantity=line.quantity,
                unit_price=unit_price,
                subtotal=line.quantity * unit_price,
            ),
        )

    return PricedOrder(
        customer_identifier=draft.customer_identifier,
        lines=tuple(priced_lines),
        total=sum(line.subtotal for line in priced_lines),
    )


async def insert_placed_order(
    order_input: OrderInput,
    dependencies: OrderDependencies,
) -> Order:
    """Coordinate order placement from submitted values through receipt delivery.

    Args:
        order_input: The unvalidated values submitted for the order.
        dependencies: The pricing, persistence, and receipt capabilities.

    Returns:
        The persisted order after its receipt has been sent.
    """
    draft = _create_order_draft(order_input)
    priced_order = _create_priced_order(draft, dependencies.prices)
    order = await dependencies.orders.insert_order(priced_order)

    await dependencies.receipts.insert_receipt(order)

    return order
```

## Transparent expressions

### NEGATIVE — A helper merely renames obvious arithmetic

**Decisive evidence:** `_create_subtotal` has a precise result but its call site is less direct than `quantity * unit_price`. It owns no pricing policy, so it fails the simpler-call-site condition.

```python
def _create_subtotal(quantity: int, unit_price: int) -> int:
    """Multiply a quantity by its unit price.

    Args:
        quantity: The number of purchased units.
        unit_price: The price of one unit.

    Returns:
        The line subtotal.
    """
    return quantity * unit_price


def _create_priced_line(line: OrderLine, unit_price: int) -> PricedLine:
    """Apply a unit price to one order line.

    Args:
        line: The product and quantity awaiting a price.
        unit_price: The catalog price of one product unit.

    Returns:
        The order line with its unit price and subtotal.
    """
    return PricedLine(
        sku=line.sku,
        quantity=line.quantity,
        unit_price=unit_price,
        subtotal=_create_subtotal(line.quantity, unit_price),
    )
```

### POSITIVE — Transparent arithmetic remains inside its owning transformation

**Decisive evidence:** `_create_priced_line` owns the coherent transformation from an unpriced line to a priced line. Keeping the multiplication visible makes its implementation clearer than another function call.

```python
def _create_priced_line(line: OrderLine, unit_price: int) -> PricedLine:
    """Apply a unit price to one order line.

    Args:
        line: The product and quantity awaiting a price.
        unit_price: The catalog price of one product unit.

    Returns:
        The order line with its unit price and subtotal.
    """
    return PricedLine(
        sku=line.sku,
        quantity=line.quantity,
        unit_price=unit_price,
        subtotal=line.quantity * unit_price,
    )
```

## Pass-through operations

### NEGATIVE — Helpers rename capabilities without adding a boundary

**Decisive evidence:** `_insert_order_record` and `_insert_order_receipt` repeat the names and signatures of existing dependency methods. They add no policy, translation, or control flow, so the coordinator becomes harder to trace without becoming easier to understand.

```python
async def _insert_order_record(
    repository: OrderRepository,
    order: PricedOrder,
) -> Order:
    """Delegate an order to its repository.

    Args:
        repository: The order persistence capability.
        order: The priced order to persist.

    Returns:
        The persisted order.
    """
    return await repository.insert_order(order)


async def _insert_order_receipt(receipts: ReceiptOutbox, order: Order) -> None:
    """Delegate receipt delivery to its existing capability.

    Args:
        receipts: The receipt delivery capability.
        order: The order acknowledged by the receipt.
    """
    await receipts.insert_receipt(order)


async def insert_placed_order(
    order: PricedOrder,
    dependencies: OrderDependencies,
) -> Order:
    """Coordinate persistence and receipt delivery for a priced order.

    Args:
        order: The priced order ready to persist.
        dependencies: The persistence and receipt capabilities.

    Returns:
        The persisted order after its receipt has been sent.
    """
    saved_order = await _insert_order_record(dependencies.orders, order)
    await _insert_order_receipt(dependencies.receipts, saved_order)
    return saved_order
```

### POSITIVE — The coordinator keeps direct operations visible

**Decisive evidence:** The repository and receipt calls already express the workflow in domain language. Removing the pass-through helpers shortens the trace without hiding either write.

```python
async def insert_placed_order(
    order: PricedOrder,
    dependencies: OrderDependencies,
) -> Order:
    """Coordinate persistence and receipt delivery for a priced order.

    Args:
        order: The priced order ready to persist.
        dependencies: The persistence and receipt capabilities.

    Returns:
        The persisted order after its receipt has been sent.
    """
    saved_order = await dependencies.orders.insert_order(order)

    await dependencies.receipts.insert_receipt(saved_order)

    return saved_order
```

## Growing policy

### NEGATIVE — Pricing policy is buried inside persistence orchestration

**Decisive evidence:** Discount selection, tax exemption, jurisdictional fallback, and currency rounding form a coherent pricing policy. Keeping that policy inside `insert_completed_checkout` makes the coordinator implement a separately nameable responsibility.

```python
async def insert_completed_checkout(
    checkout: CheckoutDraft,
    dependencies: CheckoutDependencies,
) -> Checkout:
    """Price and persist a checkout using the policy selected for its customer.

    Args:
        checkout: The checkout awaiting its final charge.
        dependencies: The pricing policy and checkout repository.

    Returns:
        The persisted checkout with its final charge.
    """
    discount_rate = (
        dependencies.policy.gold_discount_rate
        if checkout.customer.tier == "gold"
        else dependencies.policy.standard_discount_rate
    )
    discounted_subtotal = checkout.subtotal * (1 - discount_rate)
    tax_rate = (
        Decimal(0)
        if checkout.customer.tax_exempt
        else dependencies.policy.tax_rates.get(
            checkout.customer.state,
            dependencies.policy.default_tax_rate,
        )
    )
    taxed_subtotal = discounted_subtotal * (1 + tax_rate)
    total = int(taxed_subtotal.to_integral_value(rounding=ROUND_HALF_UP))

    return await dependencies.checkouts.insert_checkout(
        Checkout(
            customer=checkout.customer,
            subtotal=checkout.subtotal,
            total=total,
        ),
    )
```

### POSITIVE — Accumulated policy earns a named function

**Decisive evidence:** `_create_checkout_total` owns the complete pricing decision with explicit inputs and a semantic result. Its name makes the persistence workflow simpler even when it has only one current caller.

```python
def _create_checkout_total(
    subtotal: Decimal,
    customer: CustomerPricing,
    policy: CheckoutPolicy,
) -> int:
    """Apply discount, jurisdictional tax, and currency-rounding policy.

    Args:
        subtotal: The pre-discount merchandise total.
        customer: The customer attributes that select pricing policy.
        policy: The discount and tax configuration for the checkout.

    Returns:
        The final charge rounded to the smallest currency unit.
    """
    discount_rate = (
        policy.gold_discount_rate
        if customer.tier == "gold"
        else policy.standard_discount_rate
    )
    discounted_subtotal = subtotal * (1 - discount_rate)
    tax_rate = (
        Decimal(0)
        if customer.tax_exempt
        else policy.tax_rates.get(customer.state, policy.default_tax_rate)
    )
    taxed_subtotal = discounted_subtotal * (1 + tax_rate)

    return int(taxed_subtotal.to_integral_value(rounding=ROUND_HALF_UP))


async def insert_completed_checkout(
    checkout: CheckoutDraft,
    dependencies: CheckoutDependencies,
) -> Checkout:
    """Persist a checkout using the pricing policy selected for its customer.

    Args:
        checkout: The checkout awaiting its final charge.
        dependencies: The pricing policy and checkout repository.

    Returns:
        The persisted checkout with its final charge.
    """
    total = _create_checkout_total(
        checkout.subtotal,
        checkout.customer,
        dependencies.policy,
    )

    return await dependencies.checkouts.insert_checkout(
        Checkout(
            customer=checkout.customer,
            subtotal=checkout.subtotal,
            total=total,
        ),
    )
```
