import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template_string, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "tienda.db"

app = Flask(__name__)
app.config["DATABASE"] = str(DATABASE)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-only-change-this-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS Productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            precio REAL NOT NULL CHECK (precio >= 0),
            stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
            imagen_url TEXT,
            categoria TEXT NOT NULL DEFAULT 'skincare'
        );

        CREATE TABLE IF NOT EXISTS Ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            total REAL NOT NULL CHECK (total >= 0),
            detalle TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS Compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            producto_id INTEGER,
            cantidad INTEGER NOT NULL CHECK (cantidad > 0),
            total REAL NOT NULL CHECK (total >= 0)
        );
        """
    )
    db.commit()


def json_error(message, status_code=400):
    response = jsonify({"error": message})
    response.status_code = status_code
    return response


def product_to_dict(product):
    return {
        "id": product["id"],
        "nombre": product["nombre"],
        "precio": float(product["precio"]),
        "stock": int(product["stock"]),
        "imagen_url": product["imagen_url"],
        "categoria": product["categoria"],
    }


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.route("/", methods=["GET"])
def home():
    return jsonify({"mensaje": "Sistema de tienda funcionando"})


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""

        admin_email = os.getenv("ADMIN_EMAIL", "admin@tienda.local")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

        if email == admin_email and password == admin_password:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template_string("""
            <h1>Login Admin</h1>
            <p>Credenciales incorrectas</p>
            <form method="POST">
                <input name="email" type="email" required><br><br>
                <input name="password" type="password" required><br><br>
                <button type="submit">Entrar</button>
            </form>
        """)

    return render_template_string("""
        <h1>Login Admin</h1>
        <form method="POST">
            <input name="email" type="email" required><br><br>
            <input name="password" type="password" required><br><br>
            <button type="submit">Entrar</button>
        </form>
    """)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin", methods=["GET"])
@admin_required
def admin_dashboard():
    return jsonify({"mensaje": "Panel de administración", "admin": True})


@app.route("/api/admin/resumen", methods=["GET"])
@admin_required
def admin_summary():
    db = get_db()
    ventas = db.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM Ventas").fetchone()
    compras = db.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM Compras").fetchone()
    productos = db.execute("SELECT COUNT(*), COALESCE(SUM(stock), 0) FROM Productos").fetchone()

    return jsonify({
        "ventas": {"count": ventas[0], "total": float(ventas[1] or 0)},
        "compras": {"count": compras[0], "total": float(compras[1] or 0)},
        "productos": {"count": productos[0], "stock_total": productos[1]}
    })


@app.route("/api/asesoria", methods=["POST"])
def asesoria():
    payload = request.get_json(silent=True) or {}
    consulta = (payload.get("consulta") or "").strip()

    if not consulta:
        return json_error("Debes enviar una consulta válida.", 400)

    return jsonify({
        "mensaje": "Te recomiendo elegir productos con ingredientes suaves y revisar el stock disponible.",
        "consulta": consulta
    })


@app.route("/productos", methods=["GET"])
def get_products():
    rows = get_db().execute("SELECT * FROM Productos ORDER BY id DESC").fetchall()
    return jsonify({"productos": [product_to_dict(r) for r in rows]})


@app.route("/productos/disponibles", methods=["GET"])
def get_available_products():
    rows = get_db().execute("SELECT * FROM Productos WHERE stock > 0 ORDER BY id DESC").fetchall()
    return jsonify({"productos": [product_to_dict(r) for r in rows]})


@app.route("/productos/agotados", methods=["GET"])
def get_sold_out_products():
    rows = get_db().execute("SELECT * FROM Productos WHERE stock = 0 ORDER BY id DESC").fetchall()
    return jsonify({"productos": [product_to_dict(r) for r in rows]})


@app.route("/productos", methods=["POST"])
@admin_required
def create_product():
    data = request.get_json(silent=True) or {}
    nombre = (data.get("nombre") or "").strip()
    precio = data.get("precio")
    stock = data.get("stock", 0)
    imagen_url = data.get("imagen_url")
    categoria = (data.get("categoria") or "skincare").strip()

    if not nombre:
        return json_error("El nombre del producto es obligatorio.", 400)

    try:
        precio = float(precio)
        stock = int(stock)
    except (TypeError, ValueError):
        return json_error("Precio y stock deben ser válidos.", 400)

    if precio < 0 or stock < 0:
        return json_error("Precio y stock no pueden ser negativos.", 400)

    db = get_db()
    cursor = db.execute(
        "INSERT INTO Productos (nombre, precio, stock, imagen_url, categoria) VALUES (?, ?, ?, ?, ?)",
        (nombre, precio, stock, imagen_url, categoria),
    )
    db.commit()

    product = db.execute("SELECT * FROM Productos WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify({"producto": product_to_dict(product)}), 201


@app.route("/compras", methods=["POST"])
@admin_required
def register_purchase():
    data = request.get_json(silent=True) or {}
    producto_id = data.get("producto_id")
    cantidad = data.get("cantidad")

    try:
        producto_id = int(producto_id)
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        return json_error("producto_id y cantidad deben ser enteros válidos.", 400)

    if cantidad <= 0:
        return json_error("La cantidad debe ser mayor a 0.", 400)

    db = get_db()
    product = db.execute("SELECT * FROM Productos WHERE id = ?", (producto_id,)).fetchone()
    if product is None:
        return json_error("Producto no encontrado.", 404)

    total = float(product["precio"]) * cantidad
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    db.execute(
        "INSERT INTO Compras (fecha, producto_id, cantidad, total) VALUES (?, ?, ?, ?)",
        (fecha, producto_id, cantidad, total),
    )
    db.execute(
        "UPDATE Productos SET stock = stock + ? WHERE id = ?",
        (cantidad, producto_id),
    )
    db.commit()

    return jsonify({
        "mensaje": "Compra registrada correctamente",
        "producto_id": producto_id,
        "cantidad": cantidad,
        "total": total
    }), 201


@app.route("/ventas", methods=["POST"])
def register_sale():
    data = request.get_json(silent=True) or {}
    items = data.get("items")

    if not isinstance(items, list) or not items:
        return json_error("Debes enviar una lista de productos en 'items'.", 400)

    db = get_db()
    total = 0.0
    detalle = []

    for item in items:
        try:
            producto_id = int(item["producto_id"])
            cantidad = int(item["cantidad"])
        except (KeyError, TypeError, ValueError):
            return json_error("Cada item debe tener producto_id y cantidad válidos.", 400)

        if cantidad <= 0:
            return json_error("La cantidad debe ser mayor a 0.", 400)

        product = db.execute("SELECT * FROM Productos WHERE id = ?", (producto_id,)).fetchone()
        if product is None:
            return json_error(f"Producto con id {producto_id} no existe.", 404)
        if product["stock"] < cantidad:
            return json_error(f"Stock insuficiente para '{product['nombre']}'.", 400)

        subtotal = float(product["precio"]) * cantidad
        total += subtotal

        detalle.append({
            "producto_id": producto_id,
            "nombre": product["nombre"],
            "cantidad": cantidad,
            "precio_unitario": float(product["precio"]),
            "subtotal": subtotal
        })

        db.execute("UPDATE Productos SET stock = stock - ? WHERE id = ?", (cantidad, producto_id))

    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor = db.execute(
        "INSERT INTO Ventas (fecha, total, detalle) VALUES (?, ?, ?)",
        (fecha, total, str(detalle)),
    )
    db.commit()

    return jsonify({"mensaje": "Venta registrada correctamente", "total": total, "detalle": detalle}), 201


@app.route("/ventas", methods=["GET"])
def get_sales():
    rows = get_db().execute("SELECT * FROM Ventas ORDER BY id DESC").fetchall()
    ventas = []
    for row in rows:
        ventas.append({
            "id": row["id"],
            "fecha": row["fecha"],
            "total": float(row["total"]),
            "detalle": row["detalle"]
        })
    return jsonify({"ventas": ventas})


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)