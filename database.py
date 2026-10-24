"""SQLite database schema and initialization for persistent inventory and transport management."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Generator

from catalogue import Catalogue

DB_PATH = Path(__file__).parent / "karyamitra.db"
_test_db_path = None  # For isolated testing


def set_test_db_path(path: Path) -> None:
    """Set a custom database path for isolated testing."""
    global _test_db_path
    _test_db_path = path


def get_actual_db_path() -> Path:
    """Get the actual database path to use (test path if set, otherwise default)."""
    return _test_db_path if _test_db_path else DB_PATH


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections with proper configuration."""
    db_path = get_actual_db_path()
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db(catalogue_path: Path | None = None, demo_mode: bool = False) -> None:
    """Initialize database schema and import initial catalogue data if needed.
    
    Args:
        catalogue_path: Path to products.csv
        demo_mode: If True, seeds synthetic demo stock for demonstration.
    """
    with get_db() as conn:
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
