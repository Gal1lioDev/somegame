import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", "data/shop.db"))


def connect_db() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    connection = connect_db()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
# CREATE TABLE IF NOT EXISTS users (
#                 id INTEGER PRIMARY KEY,
#                 username TEXT NOT NULL COLLATE NOCASE UNIQUE,
#                 password_hash TEXT NOT NULL,
#                 role TEXT NOT NULL CHECK (role IN ('buyer', 'seller')),
#                 balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
#                 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
#             );


# CREATE TABLE IF NOT EXISTS orders (
#                 id INTEGER PRIMARY KEY,
#                 buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
#                 total_cost INTEGER NOT NULL CHECK (total_cost > 0),
#                 status TEXT NOT NULL DEFAULT 'completed',
#                 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
#             );
def initialize_db() -> None:
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('buyer', 'seller')),
                balance INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                seller_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price INTEGER NOT NULL CHECK (price > 0),
                stock INTEGER NOT NULL CHECK (stock >= 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_available INTEGER NOT NULL DEFAULT 1 CHECK (is_available IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS wishlists (
                id INTEGER PRIMARY KEY,
                buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (buyer_id, product_id)
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                total_cost INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
                product_name TEXT NOT NULL,
                seller_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                unit_price INTEGER NOT NULL CHECK (unit_price > 0),
                quantity INTEGER NOT NULL CHECK (quantity > 0)
            );

            CREATE INDEX IF NOT EXISTS idx_products_available ON products(is_available);
            CREATE INDEX IF NOT EXISTS idx_wishlists_buyer ON wishlists(buyer_id);
            CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id);
            """
        )
