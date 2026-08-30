from datetime import datetime, timezone
import json
from functools import wraps
import hmac
import os
from pathlib import Path
import sqlite3

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for


BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(
	os.getenv("DATABASE_PATH")
	 or ("/tmp/tienda.db" if os.getenv("VERCEL") or os.getenv("VERCEL_ENV") else str(BASE_DIR / "tienda.db"))
)

app = Flask(__name__)
app.config["DATABASE"] = str(DATABASE)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-only-change-this-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


@app.route("/", methods=["GET"])
def storefront():
	return render_template("index.html")


def get_db():
	if "db" not in g:
		g.db = sqlite3.connect(app.config["DATABASE"])
		g.db.row_factory = sqlite3.Row
		g.db.execute("PRAGMA foreign_keys = ON")
		init_db(g.db)
	return g.db


@app.teardown_appcontext
def close_db(exception=None):
	db = g.pop("db", None)
	if db is not None:
		db.close()


def init_db(db=None):
	if db is None:
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

		CREATE TABLE IF NOT EXISTS Configuracion (
			clave TEXT PRIMARY KEY,
			valor TEXT NOT NULL
		);
		"""
	)
	product_columns = {row["name"] for row in db.execute("PRAGMA table_info(Productos)")}
	if "categoria" not in product_columns:
		db.execute("ALTER TABLE Productos ADD COLUMN categoria TEXT NOT NULL DEFAULT 'skincare'")
	venta_columns = {row["name"] for row in db.execute("PRAGMA table_info(Ventas)")}
	if "detalle" not in venta_columns:
		db.execute("ALTER TABLE Ventas ADD COLUMN detalle TEXT NOT NULL DEFAULT '[]'")
	compra_columns = {row["name"] for row in db.execute("PRAGMA table_info(Compras)")}
	if "producto_id" not in compra_columns:
		db.execute("ALTER TABLE Compras ADD COLUMN producto_id INTEGER")

	if db.execute("SELECT COUNT(*) FROM Productos").fetchone()[0] == 0:
		db.executemany(
		"INSERT INTO Productos (nombre, precio, stock, imagen_url, categoria) VALUES (?, ?, ?, ?, ?)",
		[
			("Base liquida luminosa", 24.90, 30, "https://www.maybelline.com/-/media/project/loreal/brand-sites/mny/americas/us/face-makeup/foundation/fit-me-matte-poreless-foundation/warm-sun/maybelline-fit-me-matte-poreless-334-warm-sun-041554539639-av11.jpg?rev=2d8ce64adbf648c5bda965bd01b9ee3b&cx=0.25&cy=0.31&cw=760&ch=1138&hash=B11761DE2B8F6926EFFB4BF42BC803DC", "maquillaje"),
			("Rubor en crema", 16.50, 30, "https://ecobysonyadriver.eu/cdn/shop/files/EBS-Cream-Blush.png?v=1768876986&width=900", "maquillaje"),
			("Paleta de sombras nude", 29.90, 30, "https://vanitymakeup.com/cdn/shop/products/the-signature-eyeshadow-palette-209077.jpg?v=1694476304&width=900", "maquillaje"),
			("Balsamo labial con color", 12.00, 30, "https://cdn.berryglobal.com/product-images/13183935/.75%20Bias%20Cut%20Lip%20Balm%20for%20Web.jpg", "maquillaje"),
			("Mascara de pestanas", 18.90, 30, "https://es.maybelline.com/-/media/project/loreal/brand-sites/mny/americas/us/products/eye-makeup/mascara/lash-sensational-sky-tubes-tubing-mascara/maybelline-lash-sensational-sky-tubes-801-very-black-041554108637-square-packshot.jpg?rev=ec3ccaa88b4f42849ec8bcdc67541ca2&cx=0.25&cy=0.31&cw=1500&ch=1500&hash=4EE1DCF5FEA3D06AD4D53E9B16728DA6", "maquillaje"),
			("Limpiador facial suave", 19.90, 30, "https://moogoo.com.au/cdn/shop/files/MG-FACE-Callouts-FoamingFaceCleanser.jpg?v=1752191434", "skincare"),
			("Suero de vitamina C", 27.50, 30, "https://image.shutterstock.com/image-photo/vitamin-c-serum-cosmetic-bottle-260nw-1409131697.jpg", "skincare"),
			("Crema hidratante", 22.00, 30, "https://www.thegreenkiss.com/cdn/shop/files/GlowJarBeautyMoisturizingFaceCream_55e134b6-c771-410f-aad0-28f5c47aa287.jpg?v=1768885438&width=1200", "skincare"),
			("Protector solar SPF 50", 25.90, 30, "https://thumbs.dreamstime.com/z/sunscreen-lotion-bottle-summer-sun-tanning-concept-container-sun-cream-isolated-white-glossy-background-33363873.jpg", "skincare"),
			("Mascarilla facial de arcilla", 15.90, 30, "https://www.pocobeauty.com/cdn/shop/files/individual-sheet-mask-with-shadow-edited.jpg?v=1737570876&width=540", "skincare"),
		],
	)
	if db.execute("SELECT 1 FROM Configuracion WHERE clave = ?", ("stock_inicial_30",)).fetchone() is None:
		db.execute("UPDATE Productos SET stock = 30")
		db.execute("INSERT INTO Configuracion (clave, valor) VALUES (?, ?)", ("stock_inicial_30", "aplicado"))
	db.executemany(
		"UPDATE Productos SET imagen_url = ? WHERE nombre = ?",
		[
			("https://www.maybelline.com/-/media/project/loreal/brand-sites/mny/americas/us/face-makeup/foundation/fit-me-matte-poreless-foundation/warm-sun/maybelline-fit-me-matte-poreless-334-warm-sun-041554539639-av11.jpg?rev=2d8ce64adbf648c5bda965bd01b9ee3b&cx=0.25&cy=0.31&cw=760&ch=1138&hash=B11761DE2B8F6926EFFB4BF42BC803DC", "Base liquida luminosa"),
			("https://ecobysonyadriver.eu/cdn/shop/files/EBS-Cream-Blush.png?v=1768876986&width=900", "Rubor en crema"),
			("https://vanitymakeup.com/cdn/shop/products/the-signature-eyeshadow-palette-209077.jpg?v=1694476304&width=900", "Paleta de sombras nude"),
			("https://cdn.berryglobal.com/product-images/13183935/.75%20Bias%20Cut%20Lip%20Balm%20for%20Web.jpg", "Balsamo labial con color"),
			("https://es.maybelline.com/-/media/project/loreal/brand-sites/mny/americas/us/products/eye-makeup/mascara/lash-sensational-sky-tubes-tubing-mascara/maybelline-lash-sensational-sky-tubes-801-very-black-041554108637-square-packshot.jpg?rev=ec3ccaa88b4f42849ec8bcdc67541ca2&cx=0.25&cy=0.31&cw=1500&ch=1500&hash=4EE1DCF5FEA3D06AD4D53E9B16728DA6", "Mascara de pestanas"),
			("https://moogoo.com.au/cdn/shop/files/MG-FACE-Callouts-FoamingFaceCleanser.jpg?v=1752191434", "Limpiador facial suave"),
			("https://image.shutterstock.com/image-photo/vitamin-c-serum-cosmetic-bottle-260nw-1409131697.jpg", "Suero de vitamina C"),
			("https://www.thegreenkiss.com/cdn/shop/files/GlowJarBeautyMoisturizingFaceCream_55e134b6-c771-410f-aad0-28f5c47aa287.jpg?v=1768885438&width=1200", "Crema hidratante"),
			("https://thumbs.dreamstime.com/z/sunscreen-lotion-bottle-summer-sun-tanning-concept-container-sun-cream-isolated-white-glossy-background-33363873.jpg", "Protector solar SPF 50"),
			("https://www.pocobeauty.com/cdn/shop/files/individual-sheet-mask-with-shadow-edited.jpg?v=1737570876&width=540", "Mascarilla facial de arcilla"),
		],
	)
	db.commit()


def json_error(message, status_code=400):
	return jsonify({"error": message}), status_code


def product_to_dict(product):
	return dict(product)


def admin_required(view):
	@wraps(view)
	def wrapped_view(*args, **kwargs):
		if not session.get("admin_email"):
			if request.path.startswith("/api/") or request.is_json:
				return json_error("Autenticación de administrador requerida", 401)
			return redirect(url_for("admin_login"))
		return view(*args, **kwargs)
	return wrapped_view


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
	if request.method == "POST":
		data = request.form
		email = data.get("email", "").strip().lower()
		password = data.get("password", "")
		admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
		admin_password = os.getenv("ADMIN_PASSWORD", "")
		if admin_email and admin_password and hmac.compare_digest(email, admin_email) and hmac.compare_digest(password, admin_password):
			session.clear()
			session["admin_email"] = email
			return redirect(url_for("admin_dashboard"))
		return render_template("admin_login.html", error="Correo o contraseña incorrectos"), 401
	return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
	session.clear()
	return redirect(url_for("storefront"))


@app.route("/admin", methods=["GET"])
@admin_required
def admin_dashboard():
	return render_template("admin.html", admin_email=session["admin_email"])


@app.route("/api/admin/resumen", methods=["GET"])
@admin_required
def admin_summary():
	db = get_db()
	today = datetime.now(timezone.utc).date().isoformat()
	products = db.execute(
		"SELECT id, nombre, precio, stock, imagen_url, categoria "
		"FROM Productos WHERE stock = 0 ORDER BY nombre"
	).fetchall()
	sales = db.execute(
		"SELECT COUNT(*) AS cantidad, COALESCE(SUM(total), 0) AS monto "
		"FROM Ventas WHERE substr(fecha, 1, 10) = ?",
		(today,),
	).fetchone()
	purchases = db.execute(
		"SELECT COUNT(*) AS cantidad, COALESCE(SUM(cantidad), 0) AS unidades, "
		"COALESCE(SUM(total), 0) AS monto FROM Compras WHERE substr(fecha, 1, 10) = ?",
		(today,),
	).fetchone()
	sales_today = db.execute(
		"SELECT id, fecha, total FROM Ventas WHERE substr(fecha, 1, 10) = ? ORDER BY fecha DESC",
		(today,),
	).fetchall()
	purchases_today = db.execute(
		"SELECT Compras.id, Compras.fecha, Productos.nombre, Compras.cantidad, Compras.total "
		"FROM Compras LEFT JOIN Productos ON Productos.id = Compras.producto_id "
		"WHERE substr(Compras.fecha, 1, 10) = ? ORDER BY Compras.fecha DESC",
		(today,),
	).fetchall()
	units_sold = db.execute(
		"SELECT COALESCE(SUM(json_extract(value, '$.cantidad')), 0) AS unidades "
		"FROM Ventas, json_each(Ventas.detalle) WHERE substr(Ventas.fecha, 1, 10) = ?",
		(today,),
	).fetchone()["unidades"]
	available = db.execute("SELECT COUNT(*) FROM Productos WHERE stock > 0").fetchone()[0]
	return jsonify({
		"fecha": today,
		"ventas": {"cantidad": sales["cantidad"], "monto": round(sales["monto"], 2), "unidades": units_sold},
		"compras": {"cantidad": purchases["cantidad"], "monto": round(purchases["monto"], 2), "unidades": purchases["unidades"]},
		"inventario": {"disponibles": available, "agotados": len(products)},
		"agotados": [product_to_dict(product) for product in products],
		"ventas_del_dia": [dict(sale) for sale in sales_today],
		"compras_del_dia": [dict(purchase) for purchase in purchases_today],
	})


@app.route("/api/asesoria", methods=["POST"])
def product_advice():
	data = request.get_json(silent=True) or {}
	answers = {
		"necesidad": str(data.get("necesidad", "")).strip(),
		"presupuesto": str(data.get("presupuesto", "")).strip(),
		"preferencias": str(data.get("preferencias", "")).strip(),
	}
	if not answers["necesidad"]:
		return json_error("Indica qué producto estás buscando")

	api_key = os.getenv("GEMINI_API_KEY", "").strip()
	if not api_key or api_key == "TU_CLAVE_NUEVA":
		return json_error("Configura una clave real en GEMINI_API_KEY y reinicia Flask", 503)

	products = get_db().execute(
		"SELECT id, nombre, precio, stock, imagen_url, categoria FROM Productos WHERE stock > 0 ORDER BY nombre"
	).fetchall()
	if not products:
		return jsonify({"respuesta": "No hay productos disponibles en este momento.", "productos": []})

	catalog = "\n".join(
		f"- ID {product['id']}: {product['nombre']} | categoria: {product['categoria']} | ${product['precio']:.2f} | stock: {product['stock']}"
		for product in products
	)
	prompt = f"""Eres el asesor de una tienda. Responde en español, de forma breve y útil.
Sugiere entre 1 y 3 productos únicamente del catálogo disponible que aparece abajo.
No inventes productos, precios ni características. Explica en una frase por qué cada sugerencia encaja.

Lo que busca el cliente: {answers['necesidad']}
Presupuesto: {answers['presupuesto'] or 'no indicado'}
Preferencias: {answers['preferencias'] or 'no indicadas'}

Catálogo disponible:
{catalog}
"""

	try:
		from google import genai
	except ImportError:
		return json_error("Falta instalar google-genai. Ejecuta: python -m pip install -r requirements.txt", 503)

	try:
		client = genai.Client(api_key=api_key)
		response = client.models.generate_content(
			model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
			contents=prompt,
		)
		advice = (response.text or "").strip()
		if not advice:
			return json_error("Gemini no devolvió una recomendación", 502)
	except Exception as error:
		app.logger.exception("No se pudo consultar Gemini")
		error_text = str(error).lower()
		if "401" in error_text or "403" in error_text or "api key" in error_text or "permission" in error_text:
			message = "La clave de Gemini no es válida o no tiene permisos. Genera una nueva y reinicia Flask"
		elif "429" in error_text or "quota" in error_text or "resource exhausted" in error_text:
			message = "Gemini alcanzó el límite de uso. Espera unos minutos o revisa la cuota de tu proyecto"
		elif "timeout" in error_text or "connect" in error_text or "network" in error_text:
			message = "No se pudo conectar con Gemini. Revisa tu conexión a Internet"
		else:
			safe_detail = str(error).replace(api_key, "[clave oculta]").replace("\n", " ").strip()
			message = f"Gemini rechazó la solicitud: {safe_detail[:240]}"
		return json_error(message, 502)

	return jsonify({"respuesta": advice, "productos": [product_to_dict(product) for product in products]})


@app.route("/productos", methods=["GET"])
def list_products():
	estado = request.args.get("estado", "todos").lower()
	if estado not in {"todos", "disponibles", "agotados"}:
		return json_error("estado debe ser: todos, disponibles o agotados")

	query = "SELECT id, nombre, precio, stock, imagen_url, categoria FROM Productos"
	if estado == "disponibles":
		query += " WHERE stock > 0"
	elif estado == "agotados":
		query += " WHERE stock = 0"
	query += " ORDER BY nombre"

	products = get_db().execute(query).fetchall()
	return jsonify([product_to_dict(product) for product in products])


@app.route("/productos/disponibles", methods=["GET"])
def available_products():
	return list_products_with_state("disponibles")


@app.route("/productos/agotados", methods=["GET"])
def out_of_stock_products():
	return list_products_with_state("agotados")


def list_products_with_state(estado):
	products = get_db().execute(
		"SELECT id, nombre, precio, stock, imagen_url, categoria "
		"FROM Productos WHERE stock "
		+ ("> 0" if estado == "disponibles" else "= 0")
		+ " ORDER BY nombre"
	).fetchall()
	return jsonify([product_to_dict(product) for product in products])


@app.route("/productos", methods=["POST"])
def create_product():
	data = request.get_json(silent=True) or {}
	required = {"nombre", "precio", "stock"}
	missing = required - data.keys()
	if missing:
		return json_error("Faltan campos: " + ", ".join(sorted(missing)))

	try:
		nombre = str(data["nombre"]).strip()
		precio = float(data["precio"])
		stock = int(data["stock"])
		if not nombre or precio < 0 or stock < 0:
			raise ValueError
	except (TypeError, ValueError):
		return json_error("nombre, precio y stock deben tener valores válidos")

	db = get_db()
	cursor = db.execute(
		"INSERT INTO Productos (nombre, precio, stock, imagen_url, categoria) VALUES (?, ?, ?, ?, ?)",
		(nombre, precio, stock, data.get("imagen_url"), data.get("categoria", "skincare")),
	)
	db.commit()
	product = db.execute(
		"SELECT id, nombre, precio, stock, imagen_url, categoria FROM Productos WHERE id = ?",
		(cursor.lastrowid,),
	).fetchone()
	return jsonify(product_to_dict(product)), 201


@app.route("/compras", methods=["POST"])
@admin_required
def register_purchase():
	data = request.get_json(silent=True) or {}
	try:
		product_id = int(data["producto_id"])
		cantidad = int(data["cantidad"])
		if cantidad <= 0:
			raise ValueError
	except (KeyError, TypeError, ValueError):
		return json_error("producto_id y cantidad deben ser enteros positivos")

	db = get_db()
	product = db.execute("SELECT * FROM Productos WHERE id = ?", (product_id,)).fetchone()
	if product is None:
		return json_error("Producto no encontrado", 404)

	db.execute("UPDATE Productos SET stock = stock + ? WHERE id = ?", (cantidad, product_id))
	db.execute(
		"INSERT INTO Compras (fecha, producto_id, cantidad, total) VALUES (?, ?, ?, ?)",
		(datetime.now(timezone.utc).isoformat(), product_id, cantidad, round(product["precio"] * cantidad, 2)),
	)
	db.commit()
	updated = db.execute("SELECT * FROM Productos WHERE id = ?", (product_id,)).fetchone()
	return jsonify({"mensaje": "Compra registrada", "producto": product_to_dict(updated)}), 200


@app.route("/ventas", methods=["POST"])
def register_sale():
	data = request.get_json(silent=True) or {}
	items = data.get("productos", data.get("items"))
	if not isinstance(items, list) or not items:
		return json_error("productos debe ser una lista no vacía")

	db = get_db()
	try:
		total = 0.0
		for item in items:
			product_id = int(item["producto_id"])
			cantidad = int(item["cantidad"])
			if cantidad <= 0:
				raise ValueError
			product = db.execute("SELECT * FROM Productos WHERE id = ?", (product_id,)).fetchone()
			if product is None:
				return json_error(f"Producto {product_id} no encontrado", 404)
			if product["stock"] < cantidad:
				return json_error(f"Stock insuficiente para el producto {product_id}", 409)
			total += product["precio"] * cantidad

		for item in items:
			db.execute(
				"UPDATE Productos SET stock = stock - ? WHERE id = ?",
				(int(item["cantidad"]), int(item["producto_id"])),
			)
		cursor = db.execute(
			"INSERT INTO Ventas (fecha, total, detalle) VALUES (?, ?, ?)",
			(datetime.now(timezone.utc).isoformat(), round(total, 2), json.dumps(items)),
		)
		db.commit()
	except (KeyError, TypeError, ValueError):
		db.rollback()
		return json_error("Cada producto debe incluir producto_id y cantidad válidos")

	return jsonify({"mensaje": "Venta registrada", "venta_id": cursor.lastrowid, "total": round(total, 2)}), 201


@app.route("/ventas", methods=["GET"])
def list_sales():
	sales = get_db().execute("SELECT id, fecha, total FROM Ventas ORDER BY fecha DESC").fetchall()
	return jsonify([dict(sale) for sale in sales])


if __name__ == "__main__":
	app.run(debug=True)
