#!/usr/bin/env python3
"""
Сервис B — заказы.

При создании заказа обращается к сервису A (каталог) по HTTP, получает
название и цену товара, считает сумму и СОХРАНЯЕТ название с ценой внутри
заказа. Благодаря этому чтение заказа работает даже при выключенном A.

Запуск:
    python3 orders_service.py --port 5002 --catalog-url http://127.0.0.1:5001
"""

from __future__ import annotations

import argparse
import threading

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False

# Хранилище заказов в памяти процесса
_orders: dict[int, dict] = {}
_next_id = 1
_lock = threading.Lock()

# Настройки связи с сервисом A задаются при запуске
CATALOG_URL = "http://127.0.0.1:5001"
REQUEST_TIMEOUT = 2.0      # секунды; применяется к запросам B → A


class CatalogUnavailable(Exception):
    """Сервис A не ответил: не запущен, недоступен или превышен таймаут."""


class ProductNotFound(Exception):
    """Сервис A ответил, но товара с таким id нет."""


def fetch_product(product_id: int) -> dict:
    """
    Запрос товара у сервиса A.

    Таймаут обязателен: без него при зависшем A поток сервиса B ждал бы
    ответа неопределённо долго и постепенно исчерпал бы пул потоков.
    """
    url = f"{CATALOG_URL}/products/{product_id}"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.ConnectionError as exc:
        raise CatalogUnavailable(f"нет соединения с каталогом: {exc.__class__.__name__}")
    except requests.exceptions.Timeout:
        raise CatalogUnavailable(
            f"каталог не ответил за {REQUEST_TIMEOUT} с")
    except requests.exceptions.RequestException as exc:
        raise CatalogUnavailable(f"ошибка запроса к каталогу: {exc.__class__.__name__}")

    if response.status_code == 404:
        raise ProductNotFound(f"товар с id={product_id} отсутствует в каталоге")
    if response.status_code != 200:
        raise CatalogUnavailable(
            f"каталог вернул неожиданный код {response.status_code}")

    try:
        return response.json()
    except ValueError:
        raise CatalogUnavailable("каталог вернул не JSON")


@app.errorhandler(404)
def handle_404(error):
    return jsonify({"error": "not_found",
                    "message": "Запрошенный ресурс не найден"}), 404


@app.errorhandler(405)
def handle_405(error):
    return jsonify({"error": "method_not_allowed",
                    "message": "Метод не поддерживается для этого адреса"}), 405


@app.post("/orders")
def create_order():
    """POST /orders — создать заказ. Тело: {"product_id": ..., "quantity": ...}"""
    global _next_id

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "bad_request",
                        "message": "Ожидается тело запроса в формате JSON"}), 400

    product_id = data.get("product_id")
    if not isinstance(product_id, int) or isinstance(product_id, bool):
        return jsonify({
            "error": "validation_error",
            "message": "Поле 'product_id' обязательно и должно быть целым числом",
        }), 400

    quantity = data.get("quantity")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        return jsonify({
            "error": "validation_error",
            "message": "Поле 'quantity' обязательно и должно быть целым числом ≥ 1",
        }), 400

    # --- обращение к сервису A ---
    try:
        product = fetch_product(product_id)
    except CatalogUnavailable as exc:
        # 503 Service Unavailable: виноват не клиент, а недоступная зависимость.
        # Сервис B при этом продолжает работать и отвечать на другие запросы.
        return jsonify({
            "error": "catalog_unavailable",
            "message": f"Сервис каталога недоступен: {exc}",
        }), 503
    except ProductNotFound as exc:
        return jsonify({"error": "product_not_found", "message": str(exc)}), 404

    # --- сохранение заказа вместе с данными товара ---
    name = product.get("name")
    price = product.get("price")
    if not isinstance(name, str) or not isinstance(price, (int, float)):
        return jsonify({
            "error": "catalog_bad_response",
            "message": "Каталог вернул запись товара без имени или цены",
        }), 502

    with _lock:
        order = {
            "id": _next_id,
            "product_id": product_id,
            "name": name,       # копия из каталога — заказ не зависит от A
            "price": price,     # цена на момент заказа
            "quantity": quantity,
            "total": price * quantity,
        }
        _orders[_next_id] = order
        _next_id += 1

    return jsonify(order), 201, {"Location": f"/orders/{order['id']}"}


@app.get("/orders/<int:order_id>")
def get_order(order_id: int):
    """
    GET /orders/<id> — сохранённый заказ.

    К сервису A здесь обращения нет: название и цена уже лежат в заказе,
    поэтому чтение работает и при выключенном каталоге.
    """
    with _lock:
        order = _orders.get(order_id)
    if order is None:
        return jsonify({
            "error": "not_found",
            "message": f"Заказ с id={order_id} не найден",
        }), 404
    return jsonify(order), 200


@app.get("/orders")
def list_orders():
    """GET /orders — список заказов (для удобства проверки)."""
    with _lock:
        items = [_orders[k] for k in sorted(_orders)]
    return jsonify({"count": len(items), "items": items}), 200


@app.get("/health")
def health():
    return jsonify({"service": "orders", "status": "ok",
                    "catalog_url": CATALOG_URL,
                    "timeout": REQUEST_TIMEOUT}), 200


def main() -> None:
    global CATALOG_URL, REQUEST_TIMEOUT

    parser = argparse.ArgumentParser(description="Сервис B — заказы")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--catalog-url", default="http://127.0.0.1:5001",
                        help="адрес сервиса A")
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="таймаут запросов к сервису A, с")
    args = parser.parse_args()

    CATALOG_URL = args.catalog_url.rstrip("/")
    REQUEST_TIMEOUT = args.timeout
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
