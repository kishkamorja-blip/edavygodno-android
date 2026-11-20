"""Шаблон адаптера официального источника.

Реализовывать fetch_products можно только после получения официального API,
партнёрского фида или письменного разрешения на автоматическую выгрузку.
Не подставляйте сюда внутренние/неофициальные эндпоинты сайта.
"""
from abc import ABC, abstractmethod

class OfficialRetailerAdapter(ABC):
    store_name: str

    @abstractmethod
    def fetch_products(self, city: str, region: str = "") -> list[dict]:
        """Вернуть нормализованные товары; цена обязана быть привязана к городу."""
        raise NotImplementedError

    def normalize(self, raw: dict, city: str, region: str = "") -> dict:
        return {
            "name": raw["name"],
            "store": self.store_name,
            "category": raw.get("category", "Другое"),
            "price": float(raw["price"]),
            "unit": raw.get("unit", ""),
            "city": city,
            "region": region,
            "observed_at": raw.get("observed_at"),
            "source": "official_feed",
            "source_url": raw.get("source_url", ""),
            "status": "official"
        }

class PyaterochkaAdapter(OfficialRetailerAdapter):
    store_name = "Пятёрочка"
    def fetch_products(self, city: str, region: str = "") -> list[dict]:
        raise RuntimeError("Нет подтверждённого официального API/фида для этого приложения.")

class MagnitAdapter(OfficialRetailerAdapter):
    store_name = "Магнит"
    def fetch_products(self, city: str, region: str = "") -> list[dict]:
        raise RuntimeError("Публичная документация найденного API относится к партнёрам, не к розничному каталогу.")

class PerekrestokAdapter(OfficialRetailerAdapter):
    store_name = "Перекрёсток"
    def fetch_products(self, city: str, region: str = "") -> list[dict]:
        raise RuntimeError("Нужен согласованный официальный интерфейс/фид для автоматической выгрузки.")
