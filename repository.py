"""Repository layer for products, inventory, stock movements, and shipments."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from database import get_db


class ProductRepository:
    """Repository for product catalogue operations."""

    @staticmethod
    def list_products(search: str = "", is_active: bool | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        """List products with optional search and filters."""
        with get_db() as conn:
            query = "SELECT * FROM products WHERE 1=1"
            params = []
            
            if search:
                query += " AND (sku LIKE ? OR name LIKE ? OR aliases LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
            
            if is_active is not None:
                query += " AND is_active = ?"
                params.append(is_active)
            
            query += " ORDER BY name LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_product(sku: str) -> dict | None:
        """Get a single product by SKU."""
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def create_product(data: dict) -> dict:
        """Create a new product."""
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            try:
                # Convert price to integer minor currency units (paise)
                price_float = float(data.get("unit_price", "0"))
                price_minor = int(round(price_float * 100))
            except (TypeError, ValueError):
                raise ValueError("Invalid unit_price")
            
            conn.execute("""
                INSERT INTO products (
                    sku, name, aliases, category, base_unit, sellable_unit,
                    supported_conversions, unit_price, low_stock_threshold,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["sku"],
                data["name"],
                data.get("aliases", ""),
                data.get("category", "general"),
                data.get("base_unit", data.get("sellable_unit", "piece")),
                data["sellable_unit"],
                data.get("supported_conversions", ""),
                price_minor,
                data.get("low_stock_threshold", 10),
                data.get("is_active", True),
                now,
                now
            ))
            
            # Initialize inventory
            conn.execute("""
                INSERT INTO inventory (sku, on_hand_quantity, reserved_quantity,
                                      incoming_quantity, low_stock_threshold, last_updated)
                VALUES (?, 0, 0, 0, ?, ?)
            """, (data["sku"], data.get("low_stock_threshold", 10), now))
            
            conn.commit()
            return ProductRepository.get_product(data["sku"])

    @staticmethod
    def update_product(sku: str, data: dict) -> dict | None:
        """Update an existing product."""
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            updates = []
            params = []
            
            for field in ["name", "aliases", "category", "base_unit", "sellable_unit",
                         "supported_conversions", "low_stock_threshold", "is_active"]:
                if field in data:
                    updates.append(f"{field} = ?")
                    params.append(data[field])
            
            if "unit_price" in data:
                try:
                    price_float = float(data["unit_price"])
                    price_minor = int(round(price_float * 100))
                    updates.append("unit_price = ?")
                    params.append(price_minor)
                except (TypeError, ValueError):
                    raise ValueError("Invalid unit_price")
            
            if not updates:
                return ProductRepository.get_product(sku)
            
            updates.append("updated_at = ?")
            params.append(now)
            params.append(sku)
            
            conn.execute(f"UPDATE products SET {', '.join(updates)} WHERE sku = ?", params)
            conn.commit()
            return ProductRepository.get_product(sku)


class InventoryRepository:
    """Repository for inventory operations."""

    @staticmethod
    def get_inventory(sku: str) -> dict | None:
        """Get inventory for a specific SKU."""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT i.*, p.name, p.sellable_unit, p.low_stock_threshold as product_threshold
                FROM inventory i
                JOIN products p ON i.sku = p.sku
                WHERE i.sku = ?
            """, (sku,))
            row = cursor.fetchone()
            if not row:
                return None
            
            data = dict(row)
            # Calculate available quantity
            data["available_quantity"] = data["on_hand_quantity"] - data["reserved_quantity"]
            return data

    @staticmethod
    def list_inventory(low_stock_only: bool = False, limit: int = 100, offset: int = 0) -> list[dict]:
        """List all inventory with optional filter for low stock."""
        with get_db() as conn:
            query = """
                SELECT i.*, p.name, p.sellable_unit, p.low_stock_threshold as product_threshold
                FROM inventory i
                JOIN products p ON i.sku = p.sku
                WHERE 1=1
            """
            params = []
            
            if low_stock_only:
                query += " AND (i.on_hand_quantity - i.reserved_quantity) <= i.low_stock_threshold"
            
            query += " ORDER BY p.name LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = conn.execute(query, params)
            results = []
            for row in cursor.fetchall():
                data = dict(row)
                data["available_quantity"] = data["on_hand_quantity"] - data["reserved_quantity"]
                results.append(data)
            return results

    @staticmethod
    def adjust_stock(sku: str, quantity_delta: int, movement_type: str,
                     reason: str, reference_id: str | None = None,
                     reference_type: str | None = None, actor: str = "system") -> dict:
        """Adjust stock with audit trail. Returns updated inventory."""
        if quantity_delta == 0:
            raise ValueError("Quantity delta cannot be zero")
        
        now = datetime.now(timezone.utc).isoformat()
        
        with get_db() as conn:
            # Get current inventory
            cursor = conn.execute("SELECT * FROM inventory WHERE sku = ?", (sku,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Product {sku} not found in inventory")
            
            current = dict(row)
            new_on_hand = current["on_hand_quantity"] + quantity_delta
            
            if new_on_hand < 0:
                raise ValueError(f"Insufficient stock: cannot reduce below zero (current: {current['on_hand_quantity']}, delta: {quantity_delta})")
            
            # Update inventory
            conn.execute("""
                UPDATE inventory
                SET on_hand_quantity = ?, last_updated = ?
                WHERE sku = ?
            """, (new_on_hand, now, sku))
            
            # Record movement
            conn.execute("""
                INSERT INTO stock_movements (sku, quantity, movement_type, reference_id,
                                            reference_type, reason, actor, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sku, quantity_delta, movement_type, reference_id, reference_type, reason, actor, now))
            
            conn.commit()
            return InventoryRepository.get_inventory(sku)

    @staticmethod
    def reserve_stock(order_id: str, sku: str, quantity: int) -> bool:
        """Reserve stock for an order. Returns True if successful."""
        now = datetime.now(timezone.utc).isoformat()
        
        with get_db() as conn:
            # Check available stock
            cursor = conn.execute("""
                SELECT on_hand_quantity, reserved_quantity
                FROM inventory WHERE sku = ?
            """, (sku,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Product {sku} not found")
            
            available = row["on_hand_quantity"] - row["reserved_quantity"]
            if available < quantity:
                return False
            
            # Update reserved quantity
            conn.execute("""
                UPDATE inventory
                SET reserved_quantity = reserved_quantity + ?, last_updated = ?
                WHERE sku = ?
            """, (quantity, now, sku))
            
            # Create reservation record
            conn.execute("""
                INSERT INTO stock_reservations (order_id, sku, quantity, created_at, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (order_id, sku, quantity, now))
            
            conn.commit()
            return True

    @staticmethod
    def release_reservation(order_id: str, sku: str | None = None) -> None:
        """Release stock reservation for an order (optionally for specific SKU)."""
        now = datetime.now(timezone.utc).isoformat()
        
        with get_db() as conn:
            query = """
                SELECT id, sku, quantity FROM stock_reservations
                WHERE order_id = ? AND is_active = 1
            """
            params = [order_id]
            
            if sku:
                query += " AND sku = ?"
                params.append(sku)
            
            cursor = conn.execute(query, params)
            reservations = cursor.fetchall()
            
            for res in reservations:
                # Update inventory
                conn.execute("""
                    UPDATE inventory
                    SET reserved_quantity = reserved_quantity - ?, last_updated = ?
                    WHERE sku = ?
                """, (res["quantity"], now, res["sku"]))
                
                # Mark reservation as released
                conn.execute("""
                    UPDATE stock_reservations
                    SET is_active = 0, released_at = ?
                    WHERE id = ?
                """, (now, res["id"]))
            
            conn.commit()

    @staticmethod
    def get_stock_movements(sku: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        """Get stock movement history."""
        with get_db() as conn:
            query = """
                SELECT sm.*, p.name as product_name
                FROM stock_movements sm
                JOIN products p ON sm.sku = p.sku
                WHERE 1=1
            """
            params = []
            
            if sku:
                query += " AND sm.sku = ?"
                params.append(sku)
            
            query += " ORDER BY sm.created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


class ShipmentRepository:
    """Repository for shipment/transport operations."""

    @staticmethod
    def create_shipment(data: dict) -> dict:
        """Create a new shipment."""
        shipment_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        with get_db() as conn:
            # Validate order exists and is approved
            cursor = conn.execute("SELECT state FROM orders WHERE id = ?", (data["order_id"],))
            order = cursor.fetchone()
            if not order:
                raise ValueError("Order not found")
            if order["state"] != "APPROVED":
                raise ValueError("Only approved orders can have shipments")
            
            # Validate delivery dates
            dispatch_date = data.get("dispatch_date")
            expected_date = data.get("expected_delivery_date")
            actual_date = data.get("actual_delivery_date")
            
            if dispatch_date and expected_date:
                if dispatch_date > expected_date:
                    raise ValueError("Dispatch date cannot be after expected delivery date")
            
            if actual_date and dispatch_date:
                if actual_date < dispatch_date:
                    raise ValueError("Actual delivery date cannot be before dispatch date")
            
            # Convert freight cost to integer minor currency units
            freight_cost_minor = None
            if data.get("freight_cost") is not None:
                try:
                    freight_cost_float = float(data["freight_cost"])
                    freight_cost_minor = int(round(freight_cost_float * 100))
                except (TypeError, ValueError):
                    raise ValueError("Invalid freight_cost")
            
            conn.execute("""
                INSERT INTO shipments (
                    id, order_id, transporter_name, transport_mode, tracking_reference,
                    dispatch_date, expected_delivery_date, actual_delivery_date,
                    status, freight_cost, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                shipment_id,
                data["order_id"],
                data.get("transporter_name"),
                data.get("transport_mode"),
                data.get("tracking_reference"),
                dispatch_date,
                expected_date,
                actual_date,
                data.get("status", "planned"),
                freight_cost_minor,
                data.get("notes"),
                now,
                now
            ))
            
            # Link shipment to order
            conn.execute("UPDATE orders SET shipment_id = ? WHERE id = ?", (shipment_id, data["order_id"]))
            
            conn.commit()
            return ShipmentRepository.get_shipment(shipment_id)

    @staticmethod
    def get_shipment(shipment_id: str) -> dict | None:
        """Get a shipment by ID."""
        with get_db() as conn:
            cursor = conn.execute("""
                SELECT s.*, o.state as order_state
                FROM shipments s
                JOIN orders o ON s.order_id = o.id
                WHERE s.id = ?
            """, (shipment_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def update_shipment(shipment_id: str, data: dict) -> dict | None:
        """Update shipment details."""
        now = datetime.now(timezone.utc).isoformat()
        
        with get_db() as conn:
            updates = []
            params = []
            
            for field in ["transporter_name", "transport_mode", "tracking_reference",
                         "dispatch_date", "expected_delivery_date", "actual_delivery_date",
                         "notes"]:
                if field in data:
                    updates.append(f"{field} = ?")
                    params.append(data[field])
            
            if "status" in data:
                # Validate status transition
                valid_statuses = ["planned", "ready", "in_transit", "delivered", "delayed", "cancelled"]
                if data["status"] not in valid_statuses:
                    raise ValueError(f"Invalid status: {data['status']}")
                updates.append("status = ?")
                params.append(data["status"])
            
            if "freight_cost" in data:
                try:
                    freight_cost_float = float(data["freight_cost"])
                    freight_cost_minor = int(round(freight_cost_float * 100))
                    updates.append("freight_cost = ?")
                    params.append(freight_cost_minor)
                except (TypeError, ValueError):
                    raise ValueError("Invalid freight_cost")
            
            if not updates:
                return ShipmentRepository.get_shipment(shipment_id)
            
            updates.append("updated_at = ?")
            params.append(now)
            params.append(shipment_id)
            
            conn.execute(f"UPDATE shipments SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            return ShipmentRepository.get_shipment(shipment_id)

    @staticmethod
    def list_shipments(status: str | None = None, order_id: str | None = None,
                      limit: int = 100, offset: int = 0) -> list[dict]:
        """List shipments with optional filters."""
        with get_db() as conn:
            query = """
                SELECT s.*, o.state as order_state
                FROM shipments s
                JOIN orders o ON s.order_id = o.id
                WHERE 1=1
            """
            params = []
            
            if status:
                query += " AND s.status = ?"
                params.append(status)
            
            if order_id:
                query += " AND s.order_id = ?"
                params.append(order_id)
            
            query += " ORDER BY s.created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def dispatch_shipment(shipment_id: str) -> dict:
        """Dispatch a shipment - deduct stock and update status."""
        now = datetime.now(timezone.utc).isoformat()
        
        with get_db() as conn:
            # Get shipment and order
            cursor = conn.execute("""
                SELECT s.id, s.order_id, s.status, o.state as order_state
                FROM shipments s
                JOIN orders o ON s.order_id = o.id
                WHERE s.id = ?
            """, (shipment_id,))
            shipment = cursor.fetchone()
            
            if not shipment:
                raise ValueError("Shipment not found")
            
            if shipment["status"] != "ready":
                raise ValueError("Shipment must be in 'ready' status to dispatch")
            
            if shipment["order_state"] != "APPROVED":
                raise ValueError("Order must be approved to dispatch")
            
            # Get order items
            cursor = conn.execute("""
                SELECT sku, converted_quantity FROM order_items WHERE order_id = ?
            """, (shipment["order_id"],))
            items = cursor.fetchall()
            
            # Deduct stock for each item
            for item in items:
                # Release reservation
                InventoryRepository.release_reservation(shipment["order_id"], item["sku"])
                
                # Create outgoing movement
                InventoryRepository.adjust_stock(
                    sku=item["sku"],
                    quantity_delta=-item["converted_quantity"],
                    movement_type="outgoing_dispatch",
                    reason=f"Shipment {shipment_id} dispatch",
                    reference_id=shipment_id,
                    reference_type="shipment"
                )
            
            # Update shipment status
            conn.execute("""
                UPDATE shipments
                SET status = 'in_transit', dispatch_date = ?, updated_at = ?
                WHERE id = ?
            """, (now, now, shipment_id))
            
            conn.commit()
            return ShipmentRepository.get_shipment(shipment_id)

    @staticmethod
    def mark_delivered(shipment_id: str) -> dict:
        """Mark shipment as delivered."""
        now = datetime.now(timezone.utc).isoformat()
        
        with get_db() as conn:
            cursor = conn.execute("SELECT status FROM shipments WHERE id = ?", (shipment_id,))
            shipment = cursor.fetchone()
            
            if not shipment:
                raise ValueError("Shipment not found")
            
            if shipment["status"] not in ["in_transit", "ready"]:
                raise ValueError("Shipment must be in transit or ready to mark delivered")
            
            conn.execute("""
                UPDATE shipments
                SET status = 'delivered', actual_delivery_date = ?, updated_at = ?
                WHERE id = ?
            """, (now, now, shipment_id))
            
            conn.commit()
            return ShipmentRepository.get_shipment(shipment_id)


class OrderRepository:
    """Repository for persistent order storage."""

    @staticmethod
    def create_order(data: dict) -> dict:
        """Create a new order record."""
        now = datetime.now(timezone.utc).isoformat()
        
        # Convert total to integer minor currency units
        total_amount_minor = 0
        if data.get("total_amount"):
            try:
                total_amount_minor = int(round(float(data["total_amount"]) * 100))
            except (TypeError, ValueError):
                total_amount_minor = 0
        
        with get_db() as conn:
            conn.execute("""
                INSERT INTO orders (
                    id, source_record_id, original_message, state, total_amount,
                    created_at, updated_at, correction_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["id"],
                data.get("source_record_id"),
                data["original_message"],
                data["state"],
                total_amount_minor,
                now,
                now,
                data.get("correction_count", 0)
            ))
            
            # Create order items with integer minor currency units
            for item in data.get("lines", []):
                # Convert prices and totals to integer minor currency units
                unit_price_minor = 0
                line_total_minor = 0
                try:
                    unit_price_minor = int(round(float(item.get("unit_price", 0)) * 100))
                    line_total_minor = int(round(float(item.get("line_total", 0)) * 100))
                except (TypeError, ValueError):
                    pass
                
                conn.execute("""
                    INSERT INTO order_items (
                        order_id, sku, product_name, requested_quantity, requested_unit,
                        converted_quantity, unit_price, line_total, verified, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data["id"],
                    item.get("sku"),
                    item.get("product_name"),
                    item.get("quantity", 0),
                    item.get("requested_unit"),
                    item.get("converted_quantity", 0),
                    unit_price_minor,
                    line_total_minor,
                    item.get("verified", False),
                    now
                ))
            
            conn.commit()
            return OrderRepository.get_order(data["id"])

    @staticmethod
    def get_order(order_id: str) -> dict | None:
        """Get an order with its items."""
        with get_db() as conn:
            cursor = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
            order_row = cursor.fetchone()
            if not order_row:
                return None
            
            order = dict(order_row)
            
            # Get order items
            cursor = conn.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,))
            order["lines"] = [dict(row) for row in cursor.fetchall()]
            
            return order

    @staticmethod
    def update_order_state(order_id: str, state: str) -> dict | None:
        """Update order state."""
        now = datetime.now(timezone.utc).isoformat()
        
        with get_db() as conn:
            conn.execute("""
                UPDATE orders SET state = ?, updated_at = ? WHERE id = ?
            """, (state, now, order_id))
            conn.commit()
            return OrderRepository.get_order(order_id)

    @staticmethod
    def list_orders(state: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        """List orders with optional state filter."""
        with get_db() as conn:
            query = "SELECT * FROM orders WHERE 1=1"
            params = []
            
            if state:
                query += " AND state = ?"
                params.append(state)
            
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
