"""Geocoding di strade italiane → coordinate GPS."""
import logging
import asyncio
from typing import Optional
import googlemaps
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Cache locale per non sprecare chiamate API
_GEOCODE_CACHE: dict[str, tuple[float, float]] = {}

# Mapping manuale per strade note (risparmia chiamate API)
KNOWN_ROADS: dict[str, tuple[float, float]] = {
    # Autostrada A14 per provincia
    "A/14 Bologna-Taranto PU": (43.9167, 12.9167),
    "A/14 Bologna-Taranto FM": (43.3000, 13.7500),
    # SS16 Adriatica
    "SS /16 Adriatica AN": (43.6167, 13.5167),
    "SS /16 Adriatica PU": (43.9000, 12.9000),
    # Raccordo Ascoli
    "RA /11 Ascoli-Porto d'Ascoli AP": (42.8500, 13.8500),
    # Aggiungi altri noti...
}

class RoadGeocoder:
    """Converte nomi di strade in coordinate GPS."""

    def __init__(self, api_key: str):
        self._client = googlemaps.Client(key=api_key)

    async def geocode_road(
        self,
        road_name: str,
        province: str,
        region: str
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Geocodifica una strada italiana.
        Prima controlla la cache, poi il mapping manuale,
        infine chiama l'API Google.
        """
        cache_key = f"{road_name}_{province}"
        
        # 1. Cache locale
        if cache_key in _GEOCODE_CACHE:
            return _GEOCODE_CACHE[cache_key]
        
        # 2. Mapping manuale
        if cache_key in KNOWN_ROADS:
            coords = KNOWN_ROADS[cache_key]
            _GEOCODE_CACHE[cache_key] = coords
            return coords
        
        # 3. Geocoding via Google Maps API
        try:
            # Costruisci query leggibile
            # "SS 16 Adriatica, provincia di Ancona, Marche, Italia"
            clean_name = road_name.replace('/', ' ').strip()
            query = (
                f"{clean_name}, provincia di {province}, "
                f"{region}, Italia"
            )
            
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.geocode(
                    query,
                    region="it",
                    language="it"
                )
            )
            
            if result:
                loc = result[0]['geometry']['location']
                coords = (loc['lat'], loc['lng'])
                _GEOCODE_CACHE[cache_key] = coords
                return coords
                
        except Exception as e:
            _LOGGER.warning(
                "Geocoding fallito per '%s': %s", road_name, e
            )
        
        return None, None

    async def geocode_highway_point(
        self, highway: str, point_name: str
    ) -> tuple[Optional[float], Optional[float]]:
        """Geocodifica un casello/punto autostradale per il Tutor."""
        cache_key = f"tutor_{highway}_{point_name}"
        
        if cache_key in _GEOCODE_CACHE:
            return _GEOCODE_CACHE[cache_key]
        
        try:
            # Es: "Caserta Nord, A1, Italia"
            query = f"{point_name}, autostrada {highway}, Italia"
            
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.geocode(
                    query, region="it", language="it"
                )
            )
            
            if result:
                loc = result[0]['geometry']['location']
                coords = (loc['lat'], loc['lng'])
                _GEOCODE_CACHE[cache_key] = coords
                return coords
                
        except Exception as e:
            _LOGGER.warning(
                "Geocoding Tutor fallito per '%s %s': %s",
                highway, point_name, e
            )
        
        return None, None