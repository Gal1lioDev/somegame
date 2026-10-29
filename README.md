# Simple Market

A minimal e-commerce demo using FastAPI, server-rendered Jinja templates, and SQLite. FastAPI is used for its lightweight routing and form handling; SQLite and the Python standard library keep persistence and password hashing simple.

## Run with Docker Compose

```powershell
$env:SESSION_SECRET = "replace-this-with-a-long-random-secret"
docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000), then register a buyer and a seller. The database is stored in the `shop-data` Docker volume and survives container restarts. To stop the app, run `docker compose down`; the named volume is preserved.

If `SESSION_SECRET` is omitted, the app generates a random key at startup, so logged-in sessions will be invalidated if the container restarts. Set a strong secret to keep sessions valid across restarts.

Set `INITIAL_BUYER_BALANCE` to configure the credits assigned to new buyer accounts (default `1000`). For HTTPS deployments, set `SESSION_HTTPS_ONLY=true` and provide a strong, private `SESSION_SECRET`.

## Workflows

- **Buyer:** register or log in, browse/search the marketplace, view product details, add/remove wishlist entries, purchase available stock with credits, and review order history.
- **Seller:** register or log in, create listings, edit name/description/price/stock, and archive or restore listings from the seller dashboard.
- User roles are selected only at registration. Buyers and sellers are restricted to their respective account and management actions.

## Database

SQLite initializes automatically on application startup:

- `users`: unique username, password hash, fixed role, virtual balance, and creation time.
- `products`: seller ownership, listing details, positive integer credit price, non-negative stock, timestamp, and availability flag.
- `wishlists`: buyer/product association with a unique constraint preventing duplicates.
- `orders`: buyer, total paid in credits, status, and timestamp.
- `order_items`: product reference plus name, seller, unit-price, and quantity snapshots, preserving order history when a product is archived or its listing changes.

Purchases use a SQLite write transaction to debit the buyer, decrement stock, and create the order and item together. Listing deletion archives the product rather than deleting it. Product prices and balances use whole virtual credits.
