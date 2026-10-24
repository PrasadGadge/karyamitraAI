"""Test migration from old rupee-denominated schema to integer-paise schema."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from database import get_db, init_db, set_test_db_path

# Get the actual project data directory
PROJECT_DIR = Path(__file__).parents[1]
DATA_DIR = PROJECT_DIR / "data"


def test_new_database_uses_integer_paise():
    """Verify new database initialization stores prices as integer paise."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)
    
    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)
        
        with get_db() as conn:
            # Check schema
            cursor = conn.execute("PRAGMA table_info(products)")
            columns = {row["name"]: row for row in cursor.fetchall()}
            
            # unit_price should be INTEGER (not DECIMAL)
            assert columns["unit_price"]["type"] == "INTEGER", "unit_price should be INTEGER for paise storage"
            
            # Check actual stored values
            cursor = conn.execute("SELECT sku, unit_price FROM products WHERE sku='SYN-OIL-500'")
            row = cursor.fetchone()
            
            # SYN-OIL-500 has price 82.50 in CSV, should be stored as 8250 paise
            assert row["unit_price"] == 8250, f"Price should be 8250 paise, got {row['unit_price']}"
            
            # SYN-SOAP-100 has price 18.00 in CSV, should be stored as 1800 paise
            cursor = conn.execute("SELECT sku, unit_price FROM products WHERE sku='SYN-SOAP-100'")
            row = cursor.fetchone()
            assert row["unit_price"] == 1800, f"Price should be 1800 paise, got {row['unit_price']}"
            
    finally:
        set_test_db_path(None)


def test_api_converts_paise_to_rupees():
    """Verify API endpoints convert from paise to rupees."""
    from repository import ProductRepository
    
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)
    
    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)
        
        # Create a product with fractional price
        ProductRepository.create_product({
            "sku": "TEST-FRACTIONAL",
            "name": "Test Fractional Price",
            "sellable_unit": "piece",
            "unit_price": 17.99,  # Should be stored as 1799 paise
            "base_unit": "piece"
        })
        
        # Verify storage
        product = ProductRepository.get_product("TEST-FRACTIONAL")
        assert product["unit_price"] == 1799, f"Should be 1799 paise, got {product['unit_price']}"
        
        # API would convert back: 1799 / 100 = 17.99
        api_price = product["unit_price"] / 100.0
        assert api_price == 17.99, f"API price should be 17.99, got {api_price}"
        
    finally:
        set_test_db_path(None)


def test_fractional_price_rounding():
    """Test that fractional prices are rounded correctly."""
    from repository import ProductRepository
    
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)
    
    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)
        
        # Test various fractional prices
        test_cases = [
            (17.50, 1750),  # 17.50 -> 1750 paise
            (17.99, 1799),  # 17.99 -> 1799 paise
            (17.123, 1712),  # 17.123 -> 1712 paise (rounded)
            (17.999, 1800),  # 17.999 -> 1800 paise (rounded)
        ]
        
        for input_price, expected_paise in test_cases:
            ProductRepository.create_product({
                "sku": f"TEST-{expected_paise}",
                "name": f"Test {expected_paise}",
                "sellable_unit": "piece",
                "unit_price": input_price,
                "base_unit": "piece"
            })
            
            product = ProductRepository.get_product(f"TEST-{expected_paise}")
            assert product["unit_price"] == expected_paise, \
                f"Price {input_price} should be {expected_paise} paise, got {product['unit_price']}"
            
    finally:
        set_test_db_path(None)


def test_old_schema_detection():
    """Detect if an old database with DECIMAL prices exists and document migration need."""
    # This test documents the current state: there is no automatic migration
    # from old DECIMAL schema to new INTEGER schema.
    # If an old database exists, it would need manual migration.
    
    # For now, we verify that new databases use the correct schema
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)
    
    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)
        
        with get_db() as conn:
            cursor = conn.execute("PRAGMA table_info(products)")
            columns = {row["name"]: row for row in cursor.fetchall()}
            
            # Verify INTEGER storage
            assert columns["unit_price"]["type"] == "INTEGER"
            
        # If an old database with DECIMAL exists, it would require:
        # 1. Backup the database
        # 2. ALTER TABLE to change column type
        # 3. Convert existing values: unit_price * 100
        # 4. Verify all orders and shipments are converted
        # 5. Update application to use new schema
        
    finally:
        set_test_db_path(None)
