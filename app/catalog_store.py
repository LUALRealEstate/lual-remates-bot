from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from app.state_schema import PropertyRecord


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(without_accents.lower().strip().split())


class CatalogStore:
    CITY_ALIASES = {
        "tijuana": "Tijuana",
        "cdmx": "Ciudad de México",
        "ciudad de mexico": "Ciudad de México",
        "mexico city": "Ciudad de México",
        "ciudad de méxico": "Ciudad de México",
    }

    ZONE_ALIASES = {
        "zona rio": "Zona Río",
        "rio": "Zona Río",
        "playas": "Playas de Tijuana",
        "playas de tijuana": "Playas de Tijuana",
        "cacho": "Cacho",
        "el refugio": "El Refugio",
        "refugio": "El Refugio",
        "villafontana": "Villafontana",
        "narvarte": "Narvarte",
        "coyoacan": "Coyoacán",
        "coyoacán": "Coyoacán",
        "del valle": "Del Valle",
        "cuauhtemoc": "Cuauhtémoc",
        "cuauhtémoc": "Cuauhtémoc",
    }

    ZONE_TO_CITY = {
        "Zona Río": "Tijuana",
        "Playas de Tijuana": "Tijuana",
        "Cacho": "Tijuana",
        "El Refugio": "Tijuana",
        "Villafontana": "Tijuana",
        "Narvarte": "Ciudad de México",
        "Coyoacán": "Ciudad de México",
        "Del Valle": "Ciudad de México",
        "Cuauhtémoc": "Ciudad de México",
    }

    NO_INVENTORY_ZONES = {"El Refugio", "Villafontana"}

    def __init__(self, catalog_path: Path) -> None:
        raw_items = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.properties = [PropertyRecord(**item) for item in raw_items]
        self.properties_by_id: Dict[str, PropertyRecord] = {item.id: item for item in self.properties}

    def canonical_city(self, value: str | None) -> Optional[str]:
        normalized = normalize_text(value)
        return self.CITY_ALIASES.get(normalized)

    def canonical_zone(self, value: str | None) -> Optional[str]:
        normalized = normalize_text(value)
        return self.ZONE_ALIASES.get(normalized)

    def infer_city_from_zone(self, zone: str | None) -> Optional[str]:
        if not zone:
            return None
        return self.ZONE_TO_CITY.get(zone)

    def find_by_id(self, property_id: str | None) -> Optional[PropertyRecord]:
        if not property_id:
            return None
        return self.properties_by_id.get(property_id.upper().strip())

    def search(self, city: str | None = None, zone: str | None = None) -> List[PropertyRecord]:
        results = self.properties
        if city:
            results = [item for item in results if item.ciudad == city]
        if zone:
            results = [item for item in results if item.zona == zone]
        return list(results)

    def zone_has_inventory(self, city: str, zone: str) -> bool:
        if zone in self.NO_INVENTORY_ZONES:
            return False
        return bool(self.search(city=city, zone=zone))

    def city_zones_with_inventory(self, city: str) -> List[str]:
        zones = sorted({item.zona for item in self.search(city=city)})
        return zones

    def alternatives_for(self, city: str | None, zone: str | None) -> List[str]:
        if city:
            zones = self.city_zones_with_inventory(city)
            return [item for item in zones if item != zone][:3]
        return ["Tijuana", "Ciudad de México"]

    def public_property_pitch(self, item: PropertyRecord, *, include_question: bool = True) -> str:
        message = (
            f"Tenemos un {item.tipo.lower()} disponible en {item.zona}, {item.ciudad}. "
            f"Cuenta con {item.recamaras} recámaras, {self._format_bathrooms(item.banos)} y {item.m2}m². "
            f"El valor comercial es de {item.valor_comercial}, pero lo ofrecemos en {item.precio_oportunidad}, "
            f"lo que representa un {item.descuento_estimado} de descuento."
        )
        if include_question:
            message += " ¿Te gustaría saber más sobre esta oportunidad?"
        return message

    def city_catalog_pitch(self, city: str) -> str:
        zones = self.city_zones_with_inventory(city)
        zones_text = self._human_join(zones[:4])
        return f"Claro, en {city} tenemos opciones en {zones_text}. ¿Hay alguna zona que te interese?"

    def no_inventory_pitch(self, city: str | None, zone: str | None) -> str:
        alternatives = self.alternatives_for(city, zone)
        alternatives_text = self._human_join(alternatives)
        if zone:
            return (
                f"Actualmente no tenemos propiedades disponibles en {zone}, "
                f"pero sí puedo mostrarte opciones en {alternatives_text}. "
                "¿Cuál te interesa?"
            )
        return f"Ahorita no tengo inventario exacto en esa búsqueda, pero sí en {alternatives_text}. ¿Cuál te interesa?"

    def summarize_property(self, item: PropertyRecord) -> str:
        return (
            f"{item.id}: {item.tipo} en {item.zona}, {item.recamaras} rec, "
            f"{item.banos} baños, {item.m2} m2. Valor comercial {item.valor_comercial}, "
            f"precio oportunidad {item.precio_oportunidad}, descuento estimado {item.descuento_estimado}."
        )

    def short_catalog_lines(self, items: Iterable[PropertyRecord]) -> List[str]:
        return [
            f"{item.id} | {item.zona} | {item.tipo} | {item.precio_oportunidad} | {item.descuento_estimado} desc."
            for item in items
        ]

    def public_snapshot(self, property_id: str | None) -> Optional[dict]:
        item = self.find_by_id(property_id)
        if not item:
            return None
        return asdict(item)

    def _format_bathrooms(self, banos: float) -> str:
        if float(banos).is_integer():
            return f"{int(banos)} baños"
        return f"{banos} baños"

    def _human_join(self, values: Iterable[str]) -> str:
        items = list(values)
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} y {items[1]}"
        return ", ".join(items[:-1]) + f" y {items[-1]}"
