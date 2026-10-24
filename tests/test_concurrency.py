"""Concurrency test for inventory reservation race conditions."""
from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from catalogue import Catalogue
from database import get_db, init_db, set_test_db_path
from orders import OrderService
from repository import InventoryRepository

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
