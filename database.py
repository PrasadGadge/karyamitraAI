"""SQLite database schema and initialization for persistent inventory and transport management."""
from __future__ import annotations

import shutil
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Generator

from catalogue import Catalogue

# Schema versioning
CURRENT_SCHEMA_VERSION = 1  # Integer paise storage for all monetary fields
SCHEMA_VERSION_TABLE = "schema_version"
SUPPORTED_LEGACY_VERSIONS = []  # No legacy schemas supported yet

DB_PATH = Path(__file__).parent / "karyamitra.db"
_test_db_path = None  # For isolated testing


def set_test_db_path(path: Path | None) -> None:
    """Set a custom database path for isolated testing."""
    global _test_db_path
    _test_db_path = path


def get_actual_db_path() -> Path:
    """Get the actual database path to use (test path if set, otherwise default)."""
    if _test_db_path:
        return _test_db_path
    configured_path = os.getenv("KARYAMITRA_DB_PATH")
    return Path(configured_path) if configured_path else DB_PATH


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections with proper configuration."""
    db_path = get_actual_db_path()
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def write_transaction() -> Generator[sqlite3.Connection, None, None]:
    """Run a write transaction that serializes competing SQLite writers."""
    with get_db() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Get the current schema version from PRAGMA user_version."""
    cursor = conn.execute("PRAGMA user_version")
    return cursor.fetchone()[0]


def set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Set the schema version using PRAGMA user_version."""
    conn.execute(f"PRAGMA user_version = {version}")


def create_schema_version_table(conn: sqlite3.Connection) -> None:
    """Create the schema version tracking table (for documentation purposes)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT
        )
    """)


def record_schema_version(conn: sqlite3.Connection, version: int, description: str) -> None:
    """Record a schema version application in the tracking table."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO schema_version (version, applied_at, description)
        VALUES (?, ?, ?)
    """, (version, now, description))


def detect_schema_version(conn: sqlite3.Connection) -> int:
    """Detect the current schema version from database structure."""
    # Check PRAGMA user_version first
    pragma_version = get_schema_version(conn)
    if pragma_version > 0:
        return pragma_version

    # Fall back to detecting from table structure
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}

    # If no tables exist, this is a new database
    if not tables:
        return 0

    # Check for current schema: all monetary fields are INTEGER
    if "products" in tables:
        cursor = conn.execute("PRAGMA table_info(products)")
        columns = {row["name"]: row for row in cursor.fetchall()}

        if "unit_price" in columns:
            if columns["unit_price"]["type"] == "INTEGER":
                # Current schema: integer paise storage
                return CURRENT_SCHEMA_VERSION
            elif columns["unit_price"]["type"] in ("REAL", "FLOAT"):
                # Legacy schema: floating-point rupee storage (not supported without migration)
                # SQLite stores DECIMAL as REAL/TEXT, so check for REAL type
                return -1

    # Unknown schema
    return -2


def backup_database(db_path: Path) -> Path:
    """Create a backup of the database file.

    Args:
        db_path: Path to the database file to backup

    Returns:
        Path to the backup file

    Raises:
        RuntimeError: If backup cannot be created
    """
    if not db_path.exists():
        raise RuntimeError(f"Database file does not exist: {db_path}")

    # Create backup path with timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.stem}_backup_{timestamp}.db"

    # Check if backup already exists
    if backup_path.exists():
        raise RuntimeError(f"Backup file already exists: {backup_path}")

    try:
        # Copy the database file
        shutil.copy2(db_path, backup_path)

        # Verify the backup is usable
        test_conn = sqlite3.connect(backup_path)
        test_conn.execute("PRAGMA integrity_check")
        test_conn.close()

        return backup_path
    except Exception as e:
        # Clean up failed backup if it was created
        if backup_path.exists():
            try:
                backup_path.unlink()
            except:
                pass
        raise RuntimeError(f"Failed to create backup: {e}") from e


def migrate_database(db_path: Path | None = None, force: bool = False) -> dict:
    """Explicitly migrate a database to the current schema version.

    This is a deliberate operation that requires explicit invocation.
    It is NOT called automatically during normal application startup.

    Args:
        db_path: Path to the database file (uses default if None)
        force: If True, bypass confirmation checks (use with caution)

    Returns:
        Dict with migration status and details

    Raises:
        RuntimeError: If migration cannot be performed safely
    """
    if db_path is None:
        db_path = get_actual_db_path()

    result = {
        "db_path": str(db_path),
        "before_version": None,
        "after_version": None,
        "backup_path": None,
        "migrated": False,
        "error": None
    }

    try:
        with get_db() as conn:
            detected_version = detect_schema_version(conn)
            result["before_version"] = detected_version

            # If already at current version, nothing to do
            if detected_version == CURRENT_SCHEMA_VERSION:
                result["after_version"] = CURRENT_SCHEMA_VERSION
                result["migrated"] = False
                return result

            # If this is a new database (version 0), just set current version
            if detected_version == 0:
                create_schema_version_table(conn)
                set_schema_version(conn, CURRENT_SCHEMA_VERSION)
                record_schema_version(conn, CURRENT_SCHEMA_VERSION, "Initial schema with integer paise storage")
                conn.commit()
                result["after_version"] = CURRENT_SCHEMA_VERSION
                result["migrated"] = True
                return result

            # Check if this is a supported legacy version
            if detected_version not in SUPPORTED_LEGACY_VERSIONS:
                if detected_version < 0:
                    error_msg = f"Unsupported legacy schema detected (version {detected_version}). "
                    if detected_version == -1:
                        error_msg += "Legacy rupee-based schema requires manual migration. "
                        error_msg += "Contact database administrator for migration procedures."
                    else:
                        error_msg += "Unknown or ambiguous schema structure. "
                        error_msg += "Cannot safely determine migration path."
                    raise RuntimeError(error_msg)
                else:
                    raise RuntimeError(
                        f"Unknown schema version {detected_version}. "
                        f"Supported versions: {SUPPORTED_LEGACY_VERSIONS + [CURRENT_SCHEMA_VERSION]}"
                    )

            # Create backup before migrating persistent databases
            if not force and db_path == DB_PATH:
                backup_path = backup_database(db_path)
                result["backup_path"] = str(backup_path)

            # Apply migrations (none currently - legacy schema not supported)
            # When legacy schemas are supported, this would call specific migration functions

            # Update schema version
            set_schema_version(conn, CURRENT_SCHEMA_VERSION)
            record_schema_version(conn, CURRENT_SCHEMA_VERSION, f"Migrated from version {detected_version}")
            conn.commit()

            result["after_version"] = CURRENT_SCHEMA_VERSION
            result["migrated"] = True

    except Exception as e:
        result["error"] = str(e)
        raise

    return result


def init_db(catalogue_path: Path | None = None, demo_mode: bool = False, check_legacy: bool = True) -> None:
    """Initialize database schema and import initial catalogue data if needed.

    Args:
        catalogue_path: Path to products.csv
        demo_mode: If True, seeds synthetic demo stock for demonstration.
        check_legacy: If True, check for unsupported legacy schemas on startup.

    Raises:
        RuntimeError: If an unsupported legacy schema is detected.
    """
    with get_db() as conn:
        # Check for unsupported legacy schemas on existing databases
        if check_legacy:
            detected_version = detect_schema_version(conn)
            if detected_version < 0:
                error_msg = f"Unsupported legacy schema detected (version {detected_version}). "
                if detected_version == -1:
                    error_msg += "Legacy rupee-based schema found. "
                    error_msg += "Use migrate_database() to upgrade with backup. "
                    error_msg += "DO NOT use the application until migration is complete."
                else:
                    error_msg += "Unknown or ambiguous schema structure. "
                    error_msg += "Contact database administrator for assistance."
                raise RuntimeError(error_msg)

        # Products table - store prices as integer minor currency units (paise)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                sku TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                aliases TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                base_unit TEXT NOT NULL,
                sellable_unit TEXT NOT NULL,
                supported_conversions TEXT NOT NULL,
                unit_price INTEGER NOT NULL,
                low_stock_threshold INTEGER DEFAULT 10,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Inventory table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                sku TEXT PRIMARY KEY,
                on_hand_quantity INTEGER NOT NULL DEFAULT 0,
                reserved_quantity INTEGER NOT NULL DEFAULT 0,
                incoming_quantity INTEGER NOT NULL DEFAULT 0,
                low_stock_threshold INTEGER DEFAULT 10,
                last_updated TEXT NOT NULL,
                FOREIGN KEY (sku) REFERENCES products(sku) ON DELETE CASCADE
            )
        """)

        # Stock movements table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                reference_id TEXT,
                reference_type TEXT,
                reason TEXT,
                actor TEXT DEFAULT 'system',
                created_at TEXT NOT NULL,
                FOREIGN KEY (sku) REFERENCES products(sku) ON DELETE CASCADE
            )
        """)

        # Orders table (persistent storage) - store amounts as integer minor currency units
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                source_record_id TEXT,
                original_message TEXT NOT NULL,
                state TEXT NOT NULL,
                total_amount INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                correction_count INTEGER DEFAULT 0,
                shipment_id TEXT,
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL
            )
        """)

        # Order items table - store prices and totals as integer minor currency units
        conn.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                requested_quantity INTEGER NOT NULL,
                requested_unit TEXT NOT NULL,
                converted_quantity INTEGER NOT NULL,
                unit_price INTEGER NOT NULL,
                line_total INTEGER NOT NULL,
                verified BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY (sku) REFERENCES products(sku) ON DELETE RESTRICT
            )
        """)

        # Stock reservations table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                released_at TEXT,
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY (sku) REFERENCES products(sku) ON DELETE CASCADE,
                UNIQUE(order_id, sku)
            )
        """)

        # Shipments table - store freight cost as integer minor currency units
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                transporter_name TEXT,
                transport_mode TEXT,
                tracking_reference TEXT,
                dispatch_date TEXT,
                expected_delivery_date TEXT,
                actual_delivery_date TEXT,
                status TEXT NOT NULL DEFAULT 'planned',
                freight_cost INTEGER,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            )
        """)

        # Audit log table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT DEFAULT 'system',
                details TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Schema version tracking table
        create_schema_version_table(conn)

        # Create indexes for common queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movements_sku ON stock_movements(sku)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movements_created ON stock_movements(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reservations_order ON stock_reservations(order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reservations_sku ON stock_reservations(sku)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reservations_active ON stock_reservations(is_active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipments(order_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id)")

        # Set schema version if not already set
        current_version = get_schema_version(conn)
        if current_version == 0:
            set_schema_version(conn, CURRENT_SCHEMA_VERSION)
            record_schema_version(conn, CURRENT_SCHEMA_VERSION, "Initial schema with integer paise storage")

        conn.commit()

    # Import catalogue data if products table is empty
    if catalogue_path:
        _import_catalogue_if_empty(catalogue_path, demo_mode=demo_mode)


def _import_catalogue_if_empty(catalogue_path: Path, demo_mode: bool = False) -> None:
    """Import products from CSV if the products table is empty (one-time import).

    Args:
        catalogue_path: Path to products.csv
        demo_mode: If True, seeds synthetic demo stock (100 units per product) for demonstration.
                   If False, products are imported with zero stock, requiring explicit opening-stock workflow.
    """
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) as count FROM products")
        count = cursor.fetchone()["count"]

        if count > 0:
            return  # Already initialized, skip import

        catalogue = Catalogue(catalogue_path)
        now = datetime.now(timezone.utc).isoformat()

        for product in catalogue.products:
            try:
                # Convert price to integer minor currency units (paise)
                price_float = float(product.get("price", "0"))
                price_minor = int(round(price_float * 100))
            except (TypeError, ValueError):
                price_minor = 0

            conn.execute("""
                INSERT INTO products (
                    sku, name, aliases, category, base_unit, sellable_unit,
                    supported_conversions, unit_price, low_stock_threshold,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                product["sku"],
                product["name"],
                product["aliases"],
                "general",
                product["sellable_unit"],
                product["sellable_unit"],
                product["supported_conversions"],
                price_minor,
                10,
                True,
                now,
                now
            ))

            # Initialize inventory with zero stock by default
            opening_stock = 100 if demo_mode else 0
            conn.execute("""
                INSERT INTO inventory (sku, on_hand_quantity, reserved_quantity,
                                      incoming_quantity, low_stock_threshold, last_updated)
                VALUES (?, ?, 0, 0, ?, ?)
            """, (product["sku"], opening_stock, 10, now))

            # If demo mode, record the synthetic opening stock movement
            if demo_mode and opening_stock > 0:
                conn.execute("""
                    INSERT INTO stock_movements (sku, quantity, movement_type, reference_id,
                                                reference_type, reason, actor, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (product["sku"], opening_stock, "opening_stock", "demo_bootstrap",
                      "catalogue_import", "Synthetic demo stock seeded for demonstration", "system", now))

        conn.commit()


def reset_db() -> None:
    """Danger: Drop all tables and recreate schema. Only for testing."""
    db_path = get_actual_db_path()
    if db_path.exists():
        db_path.unlink()
    init_db()
