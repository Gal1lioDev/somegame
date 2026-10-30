import hmac
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from typing import Any
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.database import database, initialize_db
from app.security import hash_password, verify_password


BASE_DIR = Path(__file__).resolve().parent

INITIAL_BUYER_BALANCE = int(os.environ.get("INITIAL_BUYER_BALANCE", "1000"))
SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(48)
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")

templates = Jinja2Templates(directory=BASE_DIR / "templates")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if INITIAL_BUYER_BALANCE < 0:
        raise RuntimeError("INITIAL_BUYER_BALANCE must be non-negative")
    initialize_db()
    yield


app = FastAPI(title="Minimal E-Commerce", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="ecom_session",
    same_site="lax",
    https_only=os.environ.get("SESSION_HTTPS_ONLY", "false").lower() == "true",
    max_age=60 * 60 * 24 * 7,
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static"
)

class PageError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message


def get_user(request: Request) -> sqlite3.Row | None:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        return None
    with database() as connection:
        return connection.execute(
            "SELECT id, username, role, balance FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def require_role(request: Request, role: str) -> sqlite3.Row:
    user = get_user(request)
    if user is None:
        raise PageError(401, "Please log in to continue.")
    if user["role"] != role:
        raise PageError(403, "You do not have permission to access this page.")
    return user


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def validate_csrf(request: Request, token: str) -> None:
    expected = request.session.get("csrf_token")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, token):
        raise PageError(403, "Your form has expired. Please reload the page and try again.")


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    page_context = {
        "request": request,
        "user": get_user(request),
        "csrf_token": csrf_token(request),
        "message": request.session.pop("message", None),
        "initial_balance": INITIAL_BUYER_BALANCE,
    }
    if context:
        page_context.update(context)
    return templates.TemplateResponse(
        request=request, name=template, context=page_context, status_code=status_code
    )


def redirect(request: Request, path: str, message: str | None = None) -> RedirectResponse:
    if message:
        request.session["message"] = message
    return RedirectResponse(path, status_code=303)


def validated_product_fields(name: str, description: str, price: str, stock: str):
    clean_name = name.strip()
    clean_description = description.strip()
    if not clean_name or len(clean_name) > 120:
        raise PageError(400, "Product name must be between 1 and 120 characters.")
    if len(clean_description) > 2000:
        raise PageError(400, "Description must be 2,000 characters or fewer.")
    try:
        parsed_price = int(price)
        parsed_stock = int(stock)
    except ValueError:
        raise PageError(400, "Price and stock must be whole numbers.")
    if parsed_price <= 0 or parsed_stock < 0:
        raise PageError(400, "Price must be positive and stock cannot be negative.")
    return clean_name, clean_description, parsed_price, parsed_stock


@app.exception_handler(PageError)
async def page_error_handler(request: Request, exc: PageError):
    return render(
        request,
        "error.html",
        {"error_message": exc.message},
        status_code=exc.status_code,
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = get_user(request)
    if user is None:
        return redirect(request, "/marketplace")
    if user["role"] == "buyer":
        return redirect(request, "/buyer")
    return redirect(request, "/seller")


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if get_user(request):
        return redirect(request, "/")
    return render(request, "register.html")


@app.post("/register")
def register(
    request: Request,
    csrf: str = Form(),
    username: str = Form(),
    password: str = Form(),
    role: str = Form(),
):
    validate_csrf(request, csrf)
    username = username.strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise PageError(400, "Username must be 3–32 letters, numbers, underscores, or hyphens.")
    if len(password) < 10 or len(password) > 256:
        raise PageError(400, "Password must be between 10 and 256 characters.")
    if role not in ("buyer", "seller"):
        raise PageError(400, "Choose either a buyer or seller account.")
    balance = INITIAL_BUYER_BALANCE if role == "buyer" else 0
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO users (username, password_hash, role, balance) VALUES (?, ?, ?, ?)",
                (username, hash_password(password), role, balance),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise PageError(400, "That username is already taken.")
    request.session.clear()
    request.session["user_id"] = user_id
    return redirect(request, "/", "Your account has been created.")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_user(request):
        return redirect(request, "/")
    return render(request, "login.html")


@app.post("/login")
def login(
    request: Request,
    csrf: str = Form(),
    username: str = Form(),
    password: str = Form(),
):
    validate_csrf(request, csrf)
    with database() as connection:
        user = connection.execute(
            "SELECT id, password_hash FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        raise PageError(401, "Invalid username or password.")
    request.session.clear()
    request.session["user_id"] = user["id"]
    return redirect(request, "/", "You are now logged in.")


@app.post("/logout")
def logout(request: Request, csrf: str = Form()):
    validate_csrf(request, csrf)
    request.session.clear()
    return redirect(request, "/login", "You have been logged out.")


@app.get("/marketplace", response_class=HTMLResponse)
def marketplace(request: Request, q: str = ""):
    search = q.strip()[:100]
    with database() as connection:
        products = connection.execute(
            """
            SELECT p.*, u.username AS seller_name
            FROM products p JOIN users u ON u.id = p.seller_id
            WHERE p.is_available = 1 AND (? = '' OR p.name LIKE ? ESCAPE '\\')
            ORDER BY p.created_at DESC, p.id DESC
            """,
            (search, "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"),
        ).fetchall()
    return render(request, "marketplace.html", {"products": products, "search": search})


@app.get("/products/{product_id}", response_class=HTMLResponse)
def product_detail(request: Request, product_id: int):
    with database() as connection:
        product = connection.execute(
            """
            SELECT p.*, u.username AS seller_name
            FROM products p JOIN users u ON u.id = p.seller_id
            WHERE p.id = ? AND p.is_available = 1
            """,
            (product_id,),
        ).fetchone()
    if product is None:
        raise PageError(404, "Product not found.")
    return render(request, "product.html", {"product": product})


@app.get("/buyer", response_class=HTMLResponse)
def buyer_dashboard(request: Request):
    buyer = require_role(request, "buyer")
    return render(request, "buyer.html", {"buyer": buyer})


@app.post("/products/{product_id}/wishlist")
def add_to_wishlist(request: Request, product_id: int, csrf: str = Form()):
    buyer = require_role(request, "buyer")
    validate_csrf(request, csrf)
    with database() as connection:
        product = connection.execute(
            "SELECT id FROM products WHERE id = ? AND is_available = 1", (product_id,)
        ).fetchone()
        if product is None:
            raise PageError(404, "Product not found.")
        connection.execute(
            "INSERT OR IGNORE INTO wishlists (buyer_id, product_id) VALUES (?, ?)",
            (buyer["id"], product_id),
        )
    return redirect(request, "/wishlist", "Product added to your wishlist.")


@app.get("/wishlist", response_class=HTMLResponse)
def wishlist(request: Request):
    buyer = require_role(request, "buyer")
    with database() as connection:
        products = connection.execute(
            """
            SELECT p.id, p.name, p.price, p.stock, p.is_available
            FROM wishlists w JOIN products p ON p.id = w.product_id
            WHERE w.buyer_id = ? ORDER BY w.created_at DESC
            """,
            (buyer["id"],),
        ).fetchall()
    return render(request, "wishlist.html", {"products": products})


@app.post("/wishlist/{product_id}/remove")
def remove_from_wishlist(request: Request, product_id: int, csrf: str = Form()):
    buyer = require_role(request, "buyer")
    validate_csrf(request, csrf)
    with database() as connection:
        connection.execute(
            "DELETE FROM wishlists WHERE buyer_id = ? AND product_id = ?",
            (buyer["id"], product_id),
        )
    return redirect(request, "/wishlist", "Wishlist entry removed.")


@app.post("/products/{product_id}/purchase")
def purchase_product(
    request: Request,
    product_id: int,
    csrf: str = Form(),
    quantity: str = Form(),
):
    buyer = require_role(request, "buyer")
    validate_csrf(request, csrf)
    try:
        amount = int(quantity)
    except ValueError:
        raise PageError(400, "Quantity must be a whole number.")
    if amount < 1 or amount > 10000:
        raise PageError(400, "Quantity must be between 1 and 10,000.")

    with database() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            product = connection.execute(
                "SELECT * FROM products WHERE id = ? AND is_available = 1", (product_id,)
            ).fetchone()
            account = connection.execute(
                "SELECT balance FROM users WHERE id = ? AND role = 'buyer'", (buyer["id"],)
            ).fetchone()
            if product is None:
                raise PageError(404, "Product not found.")
            if account is None:
                raise PageError(401, "Please log in to continue.")
            if product["stock"] < amount:
                raise PageError(400, "There is not enough stock for that quantity.")
            total = product["price"] * amount
            # if account["balance"] < total:
            #     raise PageError(400, "You do not have enough credits for this purchase.")

            connection.execute(
                "UPDATE users SET balance = balance - ? WHERE id = ?",
                (total, buyer["id"]),
            )
            connection.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (amount, product_id),
            )
            order = connection.execute(
                "INSERT INTO orders (buyer_id, total_cost) VALUES (?, ?)",
                (buyer["id"], total),
            )
            connection.execute(
                """
                INSERT INTO order_items
                    (order_id, product_id, product_name, seller_id, unit_price, quantity)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    order.lastrowid,
                    product_id,
                    product["name"],
                    product["seller_id"],
                    product["price"],
                    amount,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return redirect(request, "/orders", f"Purchase complete. Order #{order.lastrowid}.")


@app.get("/orders", response_class=HTMLResponse)
def order_history(request: Request):
    buyer = require_role(request, "buyer")
    with database() as connection:
        orders = connection.execute(
            "SELECT * FROM orders WHERE buyer_id = ? ORDER BY created_at DESC, id DESC",
            (buyer["id"],),
        ).fetchall()
        items = connection.execute(
            """
            SELECT oi.*, o.buyer_id FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE o.buyer_id = ? ORDER BY oi.id
            """,
            (buyer["id"],),
        ).fetchall()
    items_by_order: dict[int, list[sqlite3.Row]] = {}
    for item in items:
        items_by_order.setdefault(item["order_id"], []).append(item)
    return render(
        request,
        "orders.html",
        {"orders": orders, "items_by_order": items_by_order},
    )


@app.get("/seller", response_class=HTMLResponse)
def seller_dashboard(request: Request):
    seller = require_role(request, "seller")
    with database() as connection:
        products = connection.execute(
            "SELECT * FROM products WHERE seller_id = ? ORDER BY created_at DESC, id DESC",
            (seller["id"],),
        ).fetchall()
    return render(request, "seller.html", {"products": products})


@app.get("/seller/products/new", response_class=HTMLResponse)
def new_product_page(request: Request):
    require_role(request, "seller")
    return render(request, "product_form.html", {"product": None, "form_action": "/seller/products"})


@app.post("/seller/products")
def create_product(
    request: Request,
    csrf: str = Form(),
    name: str = Form(),
    description: str = Form(""),
    price: str = Form(),
    stock: str = Form(),
):
    seller = require_role(request, "seller")
    validate_csrf(request, csrf)
    product = validated_product_fields(name, description, price, stock)
    with database() as connection:
        connection.execute(
            """
            INSERT INTO products (seller_id, name, description, price, stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            (seller["id"], *product),
        )
    return redirect(request, "/seller", "Product listing created.")


# @app.get("/seller/products/{product_id}/edit", response_class=HTMLResponse)
# def edit_product_page(request: Request, product_id: int):
#     seller = require_role(request, "seller")
#     with database() as connection:
#         product = connection.execute(
#             "SELECT * FROM products WHERE id = ? AND seller_id = ? AND is_available = 1",
#             (product_id, seller["id"]),
#         ).fetchone()
#     if product is None:
#         raise PageError(404, "Listing not found.")
#     return render(
#         request,
#         "product_form.html",
#         {"product": product, "form_action": f"/seller/products/{product_id}"},
#     )
@app.get("/seller/products/{product_id}/edit", response_class=HTMLResponse)
def edit_product_page(request: Request, product_id: int):
    print("DEBUG: EDIT ROUTE FROM MY LOCAL CODE", flush=True)
    seller = require_role(request, "seller")

    with database() as connection:
        product = connection.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()

    if product is None:
        raise PageError(404, "Listing not found.")

    return render(
        request,
        "product_form.html",
        {"product": product, "form_action": f"/seller/products/{product_id}"},
    )

@app.post("/seller/products/{product_id}")
def update_product(
    request: Request,
    product_id: int,
    csrf: str = Form(),
    name: str = Form(),
    description: str = Form(""),
    price: str = Form(),
    stock: str = Form(),
):
    seller = require_role(request, "seller")
    #validate_csrf(request, csrf)
    product = validated_product_fields(name, description, price, stock)
    with database() as connection:
        # result = connection.execute(
        #     """
        #     UPDATE products SET name = ?, description = ?, price = ?, stock = ?
        #     WHERE id = ? AND seller_id = ? AND is_available = 1
        #     """,
        #     (*product, product_id, seller["id"]),
        # )
        result = connection.execute(
                    """
                    UPDATE products SET name = ?, description = ?, price = ?, stock = ?
                    WHERE id = ?
                    """,
                    (*product, product_id),
                )
    if result.rowcount != 1:
        raise PageError(404, "Listing not found.")
    return redirect(request, "/seller", "Listing updated.")


@app.post("/seller/products/{product_id}/delete")
def delete_product(request: Request, product_id: int, csrf: str = Form()):
    seller = require_role(request, "seller")
    validate_csrf(request, csrf)
    with database() as connection:
        result = connection.execute(
            "UPDATE products SET is_available = 0 WHERE id = ? AND seller_id = ? AND is_available = 1",
            (product_id, seller["id"]),
        )
    if result.rowcount != 1:
        raise PageError(404, "Listing not found.")
    return redirect(request, "/seller", "Listing archived.")


@app.post("/seller/products/{product_id}/restore")
def restore_product(request: Request, product_id: int, csrf: str = Form()):
    seller = require_role(request, "seller")
    validate_csrf(request, csrf)
    with database() as connection:
        result = connection.execute(
            "UPDATE products SET is_available = 1 WHERE id = ? AND seller_id = ? AND is_available = 0",
            (product_id, seller["id"]),
        )
    if result.rowcount != 1:
        raise PageError(404, "Archived listing not found.")
    return redirect(request, "/seller", "Listing restored to the marketplace.")
