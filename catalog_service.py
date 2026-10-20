#!/usr/bin/env python3
"""
Сервис A — каталог товаров.

Хранит товары в памяти процесса и отдаёт их по HTTP.
Сервис B (заказы) обращается сюда за данными товара.

Запуск:
    python3 catalog_service.py --port 5001
"""

from __future__ import annotations

import argparse
import threading
import time

from flask import Flask, jsonify, request

app = Flask(__name__)
app.json.ensure_ascii = False      # кириллица в ответах без \uXXXX
app.json.sort_keys = False

# Хранилище в памяти. Flask обрабатывает запросы в нескольких потоках,
# поэтому доступ к общему словарю защищён блокировкой.
_products: dict[int, dict] = {}
_next_id = 1
_lock = threading.Lock()

# Искусственная задержка ответа. Нужна только для демонстрации того,
# что таймаут в сервисе B действительно срабатывает.
SLOW_SECONDS = 0.0


def create_product(name: str, price: float) -> dict:
    global _next_id
    with _lock:
        product = {"id": _next_id, "name": name, "price": price}
        _products[_next_id] = product
        _next_id += 1
    return product


def seed() -> None:
    """Пара товаров при старте, чтобы было что заказывать сразу."""
    create_product("Мышь", 5000)
    create_product("Клавиатура", 12000)


@app.errorhandler(404)
def handle_404(error):
    return jsonify({"error": "not_found",
                    "message": "Запрошенный ресурс не найден"}), 404


@app.errorhandler(405)
def handle_405(error):
    return jsonify({"error": "method_not_allowed",
                    "message": "Метод не поддерживается для этого адреса"}), 405


@app.post("/products")
def add_product():
    """POST /products — создать товар. Тело: {"name": ..., "price": ...}"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "bad_request",
                        "message": "Ожидается тело запроса в формате JSON"}), 400

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return jsonify({
            "error": "validation_error",
            "message": "Поле 'name' обязательно и должно быть непустой строкой",
        }), 400

    price = data.get("price")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0:
        return jsonify({
            "error": "validation_error",
            "message": "Поле 'price' обязательно и должно быть неотрицательным числом",
        }), 400

    product = create_product(name.strip(), price)
    return jsonify(product), 201, {"Location": f"/products/{product['id']}"}


@app.get("/products/<int:product_id>")
def get_product(product_id: int):
    """GET /products/<id> — товар по идентификатору."""
    if SLOW_SECONDS:
        time.sleep(SLOW_SECONDS)
    with _lock:
        product = _products.get(product_id)
    if product is None:
        return jsonify({
            "error": "not_found",
            "message": f"Товар с id={product_id} не найден",
        }), 404
    return jsonify(product), 200


@app.get("/products")
def list_products():
    """GET /products — список товаров (для удобства проверки)."""
    with _lock:
        items = [_products[k] for k in sorted(_products)]
    return jsonify({"count": len(items), "items": items}), 200


@app.get("/health")
def health():
    """Проверка доступности сервиса."""
    return jsonify({"service": "catalog", "status": "ok"}), 200


def main() -> None:
    parser = argparse.ArgumentParser(description="Сервис A — каталог товаров")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--no-seed", action="store_true",
                        help="не создавать демонстрационные товары")
    parser.add_argument("--slow", type=float, default=0.0,
                        help="задержка ответа GET /products/<id>, с — "
                             "для демонстрации таймаута в сервисе B")
    args = parser.parse_args()

    global SLOW_SECONDS
    SLOW_SECONDS = args.slow

    if not args.no_seed:
        seed()
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
