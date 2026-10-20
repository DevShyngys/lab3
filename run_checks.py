#!/usr/bin/env python3
"""
Автоматический прогон трёх проверок из задания ЛР 3.

Скрипт сам запускает оба сервиса, выполняет проверки, останавливает
каталог в нужный момент и печатает запросы вместе с ответами.

Запуск:
    python3 run_checks.py
    python3 run_checks.py --catalog-port 5001 --orders-port 5002
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import requests

PY = sys.executable


def show(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def call(method: str, url: str, payload: dict | None = None) -> None:
    """Выполнить запрос и напечатать его вместе с ответом."""
    if payload is None:
        print(f"$ curl -i {url}")
    else:
        body = json.dumps(payload, ensure_ascii=False)
        print(f"$ curl -i -X {method} {url} \\")
        print(f"       -H 'Content-Type: application/json' \\")
        print(f"       -d '{body}'")
    try:
        response = requests.request(method, url, json=payload, timeout=10)
    except requests.exceptions.RequestException as exc:
        print(f"  !! запрос не выполнен: {exc.__class__.__name__}")
        return

    print(f"HTTP/1.1 {response.status_code} {response.reason}")
    print(f"Content-Type: {response.headers.get('Content-Type')}")
    if "Location" in response.headers:
        print(f"Location: {response.headers['Location']}")
    print()
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print(response.text)
    print()


def start(script: str, args: list[str]) -> subprocess.Popen:
    return subprocess.Popen([PY, script, *args],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--catalog-port", type=int, default=5001)
    ap.add_argument("--orders-port", type=int, default=5002)
    ap.add_argument("--timeout", type=float, default=2.0)
    a = ap.parse_args()

    catalog_url = f"http://{a.host}:{a.catalog_port}"
    orders_url = f"http://{a.host}:{a.orders_port}"

    catalog = start("catalog_service.py",
                    ["--host", a.host, "--port", str(a.catalog_port),
                     "--no-seed"])
    orders = start("orders_service.py",
                   ["--host", a.host, "--port", str(a.orders_port),
                    "--catalog-url", catalog_url,
                    "--timeout", str(a.timeout)])
    time.sleep(2.0)

    try:
        show("ПРОВЕРКА 1. Оба сервиса работают: создание товара и заказа")
        print(f"Сервис A (каталог): {catalog_url}")
        print(f"Сервис B (заказы):  {orders_url}")
        print(f"Таймаут запросов B → A: {a.timeout} с")
        print()
        call("POST", f"{catalog_url}/products",
             {"name": "Мышь", "price": 5000})
        call("POST", f"{orders_url}/orders",
             {"product_id": 1, "quantity": 3})

        show("Останавливаем сервис A (каталог)")
        stop(catalog)
        catalog = None
        time.sleep(1.0)
        print("Сервис A остановлен. Сервис B продолжает работать.")
        call("GET", f"{orders_url}/health")

        show("ПРОВЕРКА 2. Каталог выключен: создание заказа возвращает 503")
        call("POST", f"{orders_url}/orders",
             {"product_id": 1, "quantity": 2})
        print("Сервис B не упал — отвечает на следующие запросы.")

        show("ПРОВЕРКА 3. Каталог выключен: чтение заказа возвращает 200")
        call("GET", f"{orders_url}/orders/1")
        print("Название и цена взяты из самого заказа, обращения к A не было.")

        show("Дополнительно: несуществующий товар при работающем каталоге")
        catalog = start("catalog_service.py",
                        ["--host", a.host, "--port", str(a.catalog_port),
                         "--no-seed"])
        time.sleep(2.0)
        call("POST", f"{orders_url}/orders",
             {"product_id": 999, "quantity": 1})
        print("Каталог доступен, но товара нет — это 404, а не 503.")
    finally:
        stop(catalog)
        stop(orders)
        print()
        print("Оба сервиса остановлены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
