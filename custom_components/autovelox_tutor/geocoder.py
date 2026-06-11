"""
Geocoding di strade e caselli autostradali italiani.
Supporta OpenStreetMap/Nominatim (gratuito) e Google Maps Geocoding API.
Cache persistente su disco per minimizzare le chiamate API.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import aiohttp

from .const import (
    CACHE_FILE_GEOCODE,
    GEO_PROVIDER_GOOGLE,
    GEO_PROVIDER_OSM,
    GEO_PROVIDER_BOTH,
    GOOGLE_GEOCODE_URL,
    NOMINATIM_URL,
)

_LOGGER = logging.getLogger(__name__)

# Delay tra chiamate Nominatim (policy: max 1 req/sec)
NOMINATIM_DELAY = 1.1
# Timeout per le richieste HTTP
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Headers Nominatim (richiede User-Agent identificativo)
NOMINATIM_HEADERS = {
    "User-Agent": "ha-autovelox-tutor-ita/1.0 (Home Assistant Integration)",
    "Accept-Language": "it",
}


class RoadGeocoder:
    """
    Converte nomi di strade e caselli in coordinate GPS.

    Strategia a cascata:
      1. Cache su disco (JSON, persiste tra riavvii HA)
      2. Mapping manuale per strade note (zero chiamate API)
      3. OpenStreetMap Nominatim (gratuito, nessuna chiave)
      4. Google Maps Geocoding API (più preciso, richiede chiave)

    Se provider="both": prova OSM, se fallisce usa Google.
    """

    # Coordinate note per strade/caselli comuni (risparmia chiamate API)
    _KNOWN_COORDS: dict[str, tuple[float, float]] = {
        # Autostrada A14 per provincia
        "A/14 Bologna-Taranto_PU": (43.9100, 12.9200),
        "A/14 Bologna-Taranto_FM": (43.2900, 13.7400),
        "A/14 Bologna-Taranto_AN": (43.6100, 13.5000),
        "A/14 Bologna-Taranto_AP": (42.9200, 13.8800),
        # Raccordi
        "RA /11 Ascoli-Porto d'Ascoli_AP": (42.8600, 13.8600),
        # SS16 Adriatica
        "SS /16 Adriatica_AN": (43.6200, 13.5100),
        "SS /16 Adriatica_PU": (43.8900, 12.9100),
        "SS /16 Adriatica_FM": (43.2800, 13.7500),
        # Flaminia
        "SS /3 Flaminia_PU": (43.7300, 12.6300),
        # Salaria
        "SS /4 Salaria_AP": (42.7500, 13.5000),
        # Valli Marche
        "SS /76 della Valle d'Esino_AN": (43.5600, 13.1500),
        "SS /77 della Val di Chienti_MC": (43.2000, 13.4000),
        "SS /73 Bis di Bocca Trabaria_PU": (43.6000, 12.4000),
        "SS /81 Piceno Aprutina_AP": (42.8000, 13.6000),
        "SP /423 Urbinate_PU": (43.7200, 12.6400),
        # Tutor - Caselli A1
        "A1_CASERTA NORD": (41.1000, 14.2800),
        "A1_SANTA MARIA CAPUAVETERE": (41.0800, 14.2500),
        "A1_CAPUA": (41.1100, 14.2100),
        "A1_CAIANELLO": (41.3200, 14.0700),
        "A1_SAN VITTORE": (41.4400, 13.9700),
        "A1_CASSINO": (41.4900, 13.8300),
        "A1_PONTECORVO": (41.4600, 13.6600),
        "A1_CEPRANO": (41.5400, 13.5100),
        "A1_ANAGNI": (41.7400, 13.1600),
        "A1_COLLEFERRO": (41.7300, 13.0000),
        "A1_VALMONTONE": (41.7700, 12.9200),
        "A1_ORTE": (42.4600, 12.3800),
        "A1_PONZANO ROMANO": (42.2500, 12.5900),
        "A1_MAGLIANO SABINA": (42.3600, 12.4900),
        "A1_ORVIETO": (42.7200, 12.1100),
        "A1_CHIUSI": (43.0600, 11.9500),
        "A1_VALDICHIANA": (43.2200, 11.8500),
        "A1_MONTE SAN SAVINO": (43.3400, 11.7300),
        # Tutor A14
        "A14_PESARO": (43.9100, 12.9000),
        "A14_CATTOLICA": (43.9600, 12.7400),
        "A14_RICCIONE": (44.0000, 12.6600),
        "A14_RIMINI SUD": (44.0400, 12.5500),
        "A14_CESENA": (44.1400, 12.2400),
        "A14_FORLI": (44.2200, 12.0400),
        "A14_FAENZA": (44.2900, 11.8800),
        "A14_IMOLA": (44.3500, 11.7100),
        "A14_BOLOGNA FIERA": (44.5000, 11.3400),
        "A14_PESCARA": (42.4600, 14.2100),
        "A14_ORTONA": (42.3500, 14.4000),
        "A14_GIULIANOVA": (42.7500, 13.9600),
        "A14_VAL VIBRATA": (42.8600, 13.7600),
        "A14_FOGGIA": (41.4600, 15.5500),
        "A14_SAN SEVERO": (41.6900, 15.3800),
        "A14_POGGIO IMPERIALE": (41.7700, 15.3600),
        "A14_CERIGNOLA EST": (41.2600, 15.9100),
        "A14_CANOSA": (41.2200, 16.0600),
        "A14_ANDRIA BARLETTA": (41.2200, 16.2900),
        "A14_BARI NORD": (41.1300, 16.8500),
        "A14_BARI SUD": (41.0800, 16.8700),
        "A14_BITONTO": (41.1100, 16.7000),
        "A14_MOLFETTA": (41.2000, 16.5900),
        "A14_TRANI": (41.2800, 16.4200),
    }

    def __init__(
        self,
        hass_config_dir: str,
        provider: str = GEO_PROVIDER_BOTH,
        google_api_key: Optional[str] = None,
    ) -> None:
        self._provider = provider
        self._google_api_key = google_api_key
        self._cache_file = os.path.join(hass_config_dir, CACHE_FILE_GEOCODE)
        self._cache: dict[str, tuple[float, float]] = {}
        self._last_nominatim_call: float = 0.0
        self._load_cache()

    # ------------------------------------------------------------------ #
    #  API pubblica                                                        #
    # ------------------------------------------------------------------ #

    async def geocode_road(
        self,
        road_name: str,
        province: str,
        region: str,
    ) -> tuple[Optional[float], Optional[float]]:
        """Geocodifica una strada autovelox."""
        cache_key = f"{road_name.strip()}_{province}"
        return await self._resolve(cache_key, road_name, province, region)

    async def geocode_highway_point(
        self,
        highway: str,
        point_name: str,
    ) -> tuple[Optional[float], Optional[float]]:
        """Geocodifica un casello/punto autostradale per il Tutor."""
        cache_key = f"{highway}_{point_name}"
        return await self._resolve_highway(cache_key, highway, point_name)

    def save_cache(self) -> None:
        """Salva la cache geocoding su disco."""
        try:
            serializable = {k: list(v) for k, v in self._cache.items()}
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
            _LOGGER.debug("Cache geocoding salvata: %d voci", len(self._cache))
        except OSError as exc:
            _LOGGER.warning("Impossibile salvare cache geocoding: %s", exc)

    # ------------------------------------------------------------------ #
    #  Metodi privati                                                      #
    # ------------------------------------------------------------------ #

    def _load_cache(self) -> None:
        """Carica la cache geocoding da disco."""
        if not os.path.exists(self._cache_file):
            return
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._cache = {k: tuple(v) for k, v in raw.items()}
            _LOGGER.debug("Cache geocoding caricata: %d voci", len(self._cache))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _LOGGER.warning("Cache geocoding non valida, reset: %s", exc)
            self._cache = {}

    async def _resolve(
        self,
        cache_key: str,
        road_name: str,
        province: str,
        region: str,
    ) -> tuple[Optional[float], Optional[float]]:
        # 1. Cache su disco
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 2. Mapping manuale
        if cache_key in self._KNOWN_COORDS:
            coords = self._KNOWN_COORDS[cache_key]
            self._cache[cache_key] = coords
            return coords

        # 3. Geocoding API
        clean_name = road_name.replace("/", " ").replace("  ", " ").strip()
        region_name = region.replace("_", " ").title()
        query = f"{clean_name}, provincia di {province}, {region_name}, Italia"

        coords = await self._call_provider(query)
        if coords:
            self._cache[cache_key] = coords
        return coords

    async def _resolve_highway(
        self,
        cache_key: str,
        highway: str,
        point_name: str,
    ) -> tuple[Optional[float], Optional[float]]:
        # 1. Cache
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 2. Mapping manuale
        if cache_key in self._KNOWN_COORDS:
            coords = self._KNOWN_COORDS[cache_key]
            self._cache[cache_key] = coords
            return coords

        # 3. API
        query = f"{point_name}, autostrada {highway}, Italia"
        coords = await self._call_provider(query)
        if coords:
            self._cache[cache_key] = coords
        return coords

    async def _call_provider(
        self, query: str
    ) -> tuple[Optional[float], Optional[float]]:
        """Chiama il provider di geocoding scelto."""
        if self._provider in (GEO_PROVIDER_OSM, GEO_PROVIDER_BOTH):
            coords = await self._nominatim(query)
            if coords:
                return coords

        if self._provider in (GEO_PROVIDER_GOOGLE, GEO_PROVIDER_BOTH):
            if self._google_api_key:
                coords = await self._google_geocode(query)
                if coords:
                    return coords

        _LOGGER.debug("Geocoding fallito per: %s", query)
        return None, None

    async def _nominatim(
        self, query: str
    ) -> tuple[Optional[float], Optional[float]]:
        """Chiama Nominatim rispettando il rate limit di 1 req/sec."""
        now = time.monotonic()
        elapsed = now - self._last_nominatim_call
        if elapsed < NOMINATIM_DELAY:
            await asyncio.sleep(NOMINATIM_DELAY - elapsed)

        params = {
            "q": query,
            "format": "json",
            "limit": 1,
            "countrycodes": "it",
            "addressdetails": 0,
        }
        try:
            async with aiohttp.ClientSession(
                headers=NOMINATIM_HEADERS,
                timeout=HTTP_TIMEOUT,
            ) as session:
                async with session.get(NOMINATIM_URL, params=params) as resp:
                    self._last_nominatim_call = time.monotonic()
                    if resp.status == 200:
                        data = await resp.json()
                        if data:
                            return float(data[0]["lat"]), float(data[0]["lon"])
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError) as exc:
            _LOGGER.debug("Nominatim errore per '%s': %s", query, exc)
        return None, None

    async def _google_geocode(
        self, query: str
    ) -> tuple[Optional[float], Optional[float]]:
        """Chiama Google Maps Geocoding API."""
        params = {
            "address": query,
            "key": self._google_api_key,
            "language": "it",
            "region": "it",
        }
        try:
            async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
                async with session.get(GOOGLE_GEOCODE_URL, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "OK":
                            loc = data["results"][0]["geometry"]["location"]
                            return loc["lat"], loc["lng"]
                        _LOGGER.debug(
                            "Google Geocoding status '%s' per: %s",
                            data.get("status"), query,
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError) as exc:
            _LOGGER.debug("Google Geocoding errore per '%s': %s", query, exc)
        return None, None