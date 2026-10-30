"""Concurrency test for inventory reservation race conditions."""
from __future__ import annotations

import tempfile
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pytest

from catalogue import Catalogue
from database import get_db, init_db, set_test_db_path
from orders import OrderService
from repository import InventoryRepository, InventoryReservationError, OrderRepository

# Get the actual project data directory
PROJECT_DIR = Path(__file__).parents[1]
DATA_DIR = PROJECT_DIR / "data"


def test_concurrent_stock_reservation():
    """Test that concurrent reservation attempts do not oversell stock."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        # Set limited stock: 10 units
        InventoryRepository.adjust_stock(
            sku="SYN-OIL-500",
            quantity_delta=-90,  # Start with 100, reduce to 10
            movement_type="manual_adjustment",
            reason="Test: set limited stock for concurrency test"
        )

        catalogue = Catalogue(DATA_DIR / "products.csv")

        # Create two independent order services (simulating two concurrent users)
        service1 = OrderService(catalogue, enable_inventory=True)
        service2 = OrderService(catalogue, enable_inventory=True)

        def attempt_approval(order_text):
            """Attempt to approve an order with 7 units (each exceeds half of available)."""
            try:
                order = service1.process(order_text)
                if order["state"] == "VERIFIED":
                    service1.approve(order["id"])
                    return True, order["id"]
            except Exception as e:
                return False, str(e)

        # Both requests compete for 7 units each, but only 10 are available
        # Under no-backorder policy, at most one should succeed
        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(attempt_approval, "Send 7 bottle oil")
            future2 = executor.submit(attempt_approval, "Send 7 bottle oil")

            result1 = future1.result(timeout=5)
            result2 = future2.result(timeout=5)

        # At most one should succeed
        success_count = sum(1 for success, _ in [result1, result2] if success)
        assert success_count <= 1, f"At most one approval should succeed, but {success_count} succeeded"

        # Verify final inventory state
        inv = InventoryRepository.get_inventory("SYN-OIL-500")

        if success_count == 1:
            # If one succeeded, 7 units should be reserved
            assert inv["reserved_quantity"] == 7, f"Expected 7 reserved, got {inv['reserved_quantity']}"
            assert inv["available_quantity"] == 3, f"Expected 3 available, got {inv['available_quantity']}"
        else:
            # If both failed, no stock should be reserved
            assert inv["reserved_quantity"] == 0, f"Expected 0 reserved, got {inv['reserved_quantity']}"
            assert inv["available_quantity"] == 10, f"Expected 10 available, got {inv['available_quantity']}"

    finally:
        set_test_db_path(None)


def test_multi_sku_reservation_rolls_back_when_one_sku_is_short():
    """A transaction must not leave a partial reservation behind."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)
        InventoryRepository.adjust_stock(
            sku="SYN-SOAP-100",
            quantity_delta=-95,
            movement_type="manual_adjustment",
            reason="Limit soap stock for rollback test",
        )
        before_movements = len(InventoryRepository.get_stock_movements())

        # Create the order record first to satisfy foreign key constraint
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            conn.execute("""
                INSERT INTO orders (id, original_message, state, total_amount, created_at, updated_at)
                VALUES (?, 'Test rollback order', 'APPROVED', 0, ?, ?)
            """, ("ROLLBACK-ORDER", now, now))
            conn.commit()

        with pytest.raises(InventoryReservationError, match="Insufficient inventory"):
            InventoryRepository.reserve_order_stock(
                "ROLLBACK-ORDER",
                {"SYN-OIL-500": 7, "SYN-SOAP-100": 12},
            )

        oil = InventoryRepository.get_inventory("SYN-OIL-500")
        soap = InventoryRepository.get_inventory("SYN-SOAP-100")
        assert oil["reserved_quantity"] == 0
        assert soap["reserved_quantity"] == 0
        assert oil["available_quantity"] >= 0
        assert soap["available_quantity"] >= 0
        assert len(InventoryRepository.get_stock_movements()) == before_movements
        with get_db() as conn:
            reservations = conn.execute("SELECT COUNT(*) AS count FROM stock_reservations").fetchone()["count"]
        assert reservations == 0
    finally:
        set_test_db_path(None)


def test_atomic_reservation_aggregates_duplicate_skus():
    """Repeated order lines must consume stock once per SKU within one transaction."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        # Create the order record first to satisfy foreign key constraint
        now = datetime.now(timezone.utc).isoformat()
        order_data = {
            "id": "AGGREGATE-ORDER",
            "original_message": "Test order",
            "state": "APPROVED",
            "lines": []
        }
        with get_db() as conn:
            conn.execute("""
                INSERT INTO orders (id, original_message, state, total_amount, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?)
            """, (order_data["id"], order_data["original_message"], order_data["state"], now, now))
            conn.commit()

        InventoryRepository.reserve_order_stock(
            "AGGREGATE-ORDER",
            [("SYN-OIL-500", 3), ("SYN-OIL-500", 4)],
        )

        inventory = InventoryRepository.get_inventory("SYN-OIL-500")
        assert inventory["reserved_quantity"] == 7
        assert inventory["available_quantity"] == 93
        with get_db() as conn:
            reservations = conn.execute(
                "SELECT sku, quantity FROM stock_reservations WHERE order_id = ?", ("AGGREGATE-ORDER",)
            ).fetchall()
        assert [dict(row) for row in reservations] == [{"sku": "SYN-OIL-500", "quantity": 7}]
    finally:
        set_test_db_path(None)


def test_multiple_concurrent_reservations_same_sku():
    """Multiple concurrent reservations competing for the same SKU must not oversell."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        # Set limited stock: 10 units
        InventoryRepository.adjust_stock(
            sku="SYN-OIL-500",
            quantity_delta=-90,
            movement_type="manual_adjustment",
            reason="Test: set limited stock for concurrency test"
        )

        # Create 5 order records
        now = datetime.now(timezone.utc).isoformat()
        order_ids = [f"CONCURRENT-ORDER-{i}" for i in range(5)]
        for order_id in order_ids:
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO orders (id, original_message, state, total_amount, created_at, updated_at)
                    VALUES (?, 'Test concurrent order', 'APPROVED', 0, ?, ?)
                """, (order_id, now, now))
                conn.commit()

        def attempt_reservation(order_id, quantity):
            """Attempt to reserve stock from a separate connection."""
            try:
                with get_db() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    updated = conn.execute("""
                        UPDATE inventory
                        SET reserved_quantity = reserved_quantity + ?, last_updated = ?
                        WHERE sku = ? AND reserved_quantity + ? <= on_hand_quantity
                    """, (quantity, now, "SYN-OIL-500", quantity)).rowcount
                    if updated == 1:
                        conn.execute("""
                            INSERT INTO stock_reservations (order_id, sku, quantity, created_at, is_active)
                            VALUES (?, ?, ?, ?, 1)
                        """, (order_id, "SYN-OIL-500", quantity, now))
                        conn.commit()
                        return True
                    else:
                        conn.rollback()
                        return False
            except Exception:
                return False

        # All 5 reservations compete for 3 units each (15 total requested, only 10 available)
        # Under no-backorder policy, at most 3 should succeed (3 + 3 + 3 = 9 <= 10)
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(attempt_reservation, order_id, 3) for order_id in order_ids]
            results = [f.result(timeout=5) for f in as_completed(futures)]

        success_count = sum(results)
        assert success_count <= 3, f"At most 3 reservations should succeed, but {success_count} succeeded"

        # Verify final inventory state
        inv = InventoryRepository.get_inventory("SYN-OIL-500")
        assert inv["reserved_quantity"] == success_count * 3
        assert inv["available_quantity"] == 10 - (success_count * 3)
        assert inv["reserved_quantity"] <= inv["on_hand_quantity"], "Reserved quantity must not exceed on-hand"
    finally:
        set_test_db_path(None)


def test_seven_from_ten_exactly_one_succeeds():
    """Two reservations each requesting 7 units from 10 available: exactly one must succeed."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        # Set stock to exactly 10 units
        InventoryRepository.adjust_stock(
            sku="SYN-OIL-500",
            quantity_delta=-90,
            movement_type="manual_adjustment",
            reason="Test: set 10 units for exact test"
        )

        # Create 2 order records
        now = datetime.now(timezone.utc).isoformat()
        order_ids = ["ORDER-A", "ORDER-B"]
        for order_id in order_ids:
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO orders (id, original_message, state, total_amount, created_at, updated_at)
                    VALUES (?, 'Test exact order', 'APPROVED', 0, ?, ?)
                """, (order_id, now, now))
                conn.commit()

        def attempt_reservation(order_id):
            """Attempt to reserve 7 units."""
            try:
                with get_db() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    updated = conn.execute("""
                        UPDATE inventory
                        SET reserved_quantity = reserved_quantity + 7, last_updated = ?
                        WHERE sku = ? AND reserved_quantity + 7 <= on_hand_quantity
                    """, (now, "SYN-OIL-500")).rowcount
                    if updated == 1:
                        conn.execute("""
                            INSERT INTO stock_reservations (order_id, sku, quantity, created_at, is_active)
                            VALUES (?, ?, 7, ?, 1)
                        """, (order_id, "SYN-OIL-500", now))
                        conn.commit()
                        return True
                    else:
                        conn.rollback()
                        return False
            except Exception:
                return False

        # Both request 7 units, only 10 available - exactly one must succeed
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt_reservation, order_id) for order_id in order_ids]
            results = [f.result(timeout=5) for f in as_completed(futures)]

        success_count = sum(results)
        assert success_count == 1, f"Exactly one reservation should succeed, but {success_count} succeeded"

        # Verify final state: 7 reserved, 3 available
        inv = InventoryRepository.get_inventory("SYN-OIL-500")
        assert inv["reserved_quantity"] == 7
        assert inv["available_quantity"] == 3
        assert inv["on_hand_quantity"] == 10
    finally:
        set_test_db_path(None)


def test_transaction_rollback_on_exception():
    """Exception during reservation must not leave partial state."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        # Create order record
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            conn.execute("""
                INSERT INTO orders (id, original_message, state, total_amount, created_at, updated_at)
                VALUES (?, 'Test rollback order', 'APPROVED', 0, ?, ?)
            """, ("ROLLBACK-TEST", now, now))
            conn.commit()

        inv_before = InventoryRepository.get_inventory("SYN-OIL-500")
        before_reserved = inv_before["reserved_quantity"]

        # Attempt to reserve more than available - should fail and rollback
        with pytest.raises(InventoryReservationError, match="Insufficient inventory"):
            InventoryRepository.reserve_order_stock(
                "ROLLBACK-TEST",
                {"SYN-OIL-500": 1000}  # Way more than available
            )

        # Verify state is unchanged
        inv_after = InventoryRepository.get_inventory("SYN-OIL-500")
        assert inv_after["reserved_quantity"] == before_reserved
        assert inv_after["on_hand_quantity"] == inv_before["on_hand_quantity"]

        # Verify no reservation record was created
        with get_db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM stock_reservations WHERE order_id = ?", ("ROLLBACK-TEST",)).fetchone()[0]
        assert count == 0
    finally:
        set_test_db_path(None)


def test_sqlite_connection_cleanup():
    """SQLite connections must be properly closed after operations."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        # Perform multiple operations
        for i in range(10):
            InventoryRepository.adjust_stock(
                sku="SYN-OIL-500",
                quantity_delta=1,
                movement_type="test",
                reason=f"Test iteration {i}"
            )

        # Verify database is accessible
        inv = InventoryRepository.get_inventory("SYN-OIL-500")
        assert inv["on_hand_quantity"] == 110

        # Create and release reservation
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            conn.execute("""
                INSERT INTO orders (id, original_message, state, total_amount, created_at, updated_at)
                VALUES (?, 'Test cleanup order', 'APPROVED', 0, ?, ?)
            """, ("CLEANUP-TEST", now, now))
            conn.commit()

        InventoryRepository.reserve_order_stock("CLEANUP-TEST", {"SYN-OIL-500": 5})
        InventoryRepository.release_reservation("CLEANUP-TEST")

        # Verify final state
        inv_final = InventoryRepository.get_inventory("SYN-OIL-500")
        assert inv_final["reserved_quantity"] == 0
        assert inv_final["on_hand_quantity"] == 110
    finally:
        set_test_db_path(None)
