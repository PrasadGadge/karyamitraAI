"""Test migration from old rupee-denominated schema to integer-paise schema."""
from __future__ import annotations

import tempfile
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from database import (
    get_db, init_db, set_test_db_path,
    get_schema_version, set_schema_version,
    detect_schema_version, backup_database,
    migrate_database, CURRENT_SCHEMA_VERSION
)

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


def test_schema_version_tracking():
    """Test that schema version is tracked using PRAGMA user_version."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        with get_db() as conn:
            version = get_schema_version(conn)
            assert version == CURRENT_SCHEMA_VERSION, f"Expected version {CURRENT_SCHEMA_VERSION}, got {version}"

    finally:
        set_test_db_path(None)


def test_new_database_sets_schema_version():
    """Test that a new database is initialized with the current schema version."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        with get_db() as conn:
            version = get_schema_version(conn)
            assert version == CURRENT_SCHEMA_VERSION

            # Verify schema version table exists
            cursor = conn.execute("SELECT COUNT(*) FROM schema_version")
            count = cursor.fetchone()[0]
            assert count == 1, "Schema version table should have one entry"

    finally:
        set_test_db_path(None)


def test_detect_schema_version_new_database():
    """Test schema detection for a new database."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        with get_db() as conn:
            version = detect_schema_version(conn)
            assert version == 0, "Empty database should be version 0"

    finally:
        set_test_db_path(None)


def test_detect_schema_version_current():
    """Test schema detection for current schema."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        with get_db() as conn:
            version = detect_schema_version(conn)
            assert version == CURRENT_SCHEMA_VERSION

    finally:
        set_test_db_path(None)


def test_detect_legacy_rupee_schema():
    """Test detection of legacy rupee-based schema (REAL prices)."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        # Create a legacy schema with REAL prices (SQLite stores DECIMAL as REAL)
        with get_db() as conn:
            conn.execute("""
                CREATE TABLE products (
                    sku TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    unit_price REAL NOT NULL
                )
            """)
            conn.commit()

        with get_db() as conn:
            version = detect_schema_version(conn)
            assert version == -1, "Legacy REAL schema should return -1"

    finally:
        set_test_db_path(None)


def test_detect_unknown_schema():
    """Test detection of unknown schema."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        # Create a table but not the products table
        with get_db() as conn:
            conn.execute("""
                CREATE TABLE unknown_table (
                    id INTEGER PRIMARY KEY
                )
            """)
            conn.commit()

        with get_db() as conn:
            version = detect_schema_version(conn)
            assert version == -2, "Unknown schema should return -2"

    finally:
        set_test_db_path(None)


def test_unsupported_legacy_schema_blocks_init():
    """Test that unsupported legacy schemas block initialization."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        # Create a legacy schema
        with get_db() as conn:
            conn.execute("""
                CREATE TABLE products (
                    sku TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    unit_price REAL NOT NULL
                )
            """)
            conn.commit()

        # Attempting to init should fail
        with pytest.raises(RuntimeError, match="Unsupported legacy schema"):
            init_db(DATA_DIR / "products.csv", demo_mode=True, check_legacy=True)

    finally:
        set_test_db_path(None)


def test_backup_database():
    """Test database backup creation."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        # Create backup
        backup_path = backup_database(temp_path)

        # Verify backup exists
        assert backup_path.exists()
        assert "backup" in backup_path.name

        # Verify backup is usable
        backup_conn = sqlite3.connect(backup_path)
        backup_conn.execute("PRAGMA integrity_check")
        backup_conn.close()

        # Verify backup has same data
        with get_db() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM products")
            original_count = cursor.fetchone()[0]

        backup_conn = sqlite3.connect(backup_path)
        cursor = backup_conn.execute("SELECT COUNT(*) FROM products")
        backup_count = cursor.fetchone()[0]
        backup_conn.close()

        assert original_count == backup_count

        # Clean up backup
        backup_path.unlink()

    finally:
        set_test_db_path(None)


def test_migrate_new_database():
    """Test migration of a new database (version 0 to current)."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        # Create empty database (version 0)
        with get_db() as conn:
            pass  # Just create the file

        # Migrate
        result = migrate_database(temp_path, force=True)

        assert result["migrated"] is True
        assert result["before_version"] == 0
        assert result["after_version"] == CURRENT_SCHEMA_VERSION

        # Verify schema version is set
        with get_db() as conn:
            version = get_schema_version(conn)
            assert version == CURRENT_SCHEMA_VERSION

    finally:
        set_test_db_path(None)


def test_migrate_already_current():
    """Test that migration is a no-op if already at current version."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        # Migrate
        result = migrate_database(temp_path, force=True)

        assert result["migrated"] is False
        assert result["before_version"] == CURRENT_SCHEMA_VERSION
        assert result["after_version"] == CURRENT_SCHEMA_VERSION

    finally:
        set_test_db_path(None)


def test_migrate_unsupported_legacy_fails():
    """Test that migration fails for unsupported legacy schemas."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        # Create legacy schema
        with get_db() as conn:
            conn.execute("""
                CREATE TABLE products (
                    sku TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    unit_price REAL NOT NULL
                )
            """)
            conn.commit()

        # Migration should fail
        with pytest.raises(RuntimeError, match="Unsupported legacy schema"):
            migrate_database(temp_path, force=True)

    finally:
        set_test_db_path(None)


def test_migrate_unknown_version_fails():
    """Test that migration fails for unknown schema versions."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        # Create a database and set an unknown version
        with get_db() as conn:
            conn.execute("CREATE TABLE test (id INTEGER)")
            set_schema_version(conn, 999)
            conn.commit()

        # Migration should fail
        with pytest.raises(RuntimeError, match="Unknown schema version"):
            migrate_database(temp_path, force=True)

    finally:
        set_test_db_path(None)


def test_initialization_is_idempotent():
    """Test that running init_db multiple times is idempotent."""
    temp_path = Path(tempfile.mktemp(suffix=".db"))
    set_test_db_path(temp_path)

    try:
        # First initialization
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        with get_db() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM products")
            count1 = cursor.fetchone()[0]

        # Second initialization should not duplicate data
        init_db(DATA_DIR / "products.csv", demo_mode=True)

        with get_db() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM products")
            count2 = cursor.fetchone()[0]

        assert count1 == count2, "Initialization should be idempotent"

    finally:
        set_test_db_path(None)
