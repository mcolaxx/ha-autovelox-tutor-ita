"""
DataUpdateCoordinator per Autovelox & Tutor.
Gestisce download periodico dei PDF, parsing, geocoding e cache.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CACHE_FILE_TUTOR,
    CACHE_FILE_VELOX,
    CACHE_MAX_AGE_DAYS,
    DOMAIN,
    HTTP_HEADERS,
    TUTOR_PDF_URL,
    VELOX_BASE_URL,
    REGION_PDF_MAP,
    GEO_PROVIDER_OSM,
    GEO_PROVIDER_BOTH,
)
from .geocoder import RoadGeocoder
from .google_maps import GoogleMyMapsExporter, KMLGenerator
from .parsers.velox_parser import VeloxEntry, VeloxPDFParser
from .parsers.tutor_parser import TutorEntry, TutorPDFParser

_LOGGER = logging.getLogger(__name__)

# Intervallo aggiornamento: ogni 7 giorni
# (il coordinator viene triggerato anche manualmente via servizio HA)
UPDATE_INTERVAL = timedelta(days=7)

# Timeout download PDF
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60)


class AutoveloxCoordinator(DataUpdateCoordinator):
    """
    Coordina tutti i dati dell'integrazione:
    - Scarica PDF velox per le regioni selezionate
    - Scarica PDF tutor nazionale
    - Geocodifica tutti i punti
    - Gestisce cache su disco
    - Esporta su Google My Maps
    """

    def __init__(
        self,
        hass: HomeAssistant,
        regions: list[str],
        geocoder: RoadGeocoder,
        exporter: Optional[GoogleMyMapsExporter],
        export_enabled: bool,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.regions = regions
        self._geocoder = geocoder
        self._exporter = exporter
        self._export_enabled = export_enabled
        self._config_dir = hass.config.config_dir
        self._velox_parser_cache: dict[str, VeloxPDFParser] = {}
        self._tutor_parser = TutorPDFParser()
        self._kml_generator = KMLGenerator()

        # Dati esposti alle entità HA
        self.velox_by_region: dict[str, list[VeloxEntry]] = {}
        self.tutor_entries: list[TutorEntry] = []
        self.mymaps_urls: dict[str, str] = {}
        self.last_successful_update: Optional[datetime] = None

    # ------------------------------------------------------------------ #
    #  Metodo principale richiesto da DataUpdateCoordinator               #
    # ------------------------------------------------------------------ #

    async def _async_update_data(self) -> dict:
        """Scarica, parsa, geocodifica e restituisce tutti i dati."""
        try:
            async with aiohttp.ClientSession(
                headers=HTTP_HEADERS,
                timeout=DOWNLOAD_TIMEOUT,
            ) as session:
                # --- Velox: una regione alla volta ---
                for region in self.regions:
                    await self._update_region_velox(session, region)

                # --- Tutor nazionale ---
                await self._update_tutor(session)

            # --- Geocoding di tutto ciò che non ha ancora coordinate ---
            await self._geocode_all()

            # --- Salva geocoding cache su disco ---
            await self.hass.async_add_executor_job(self._geocoder.save_cache)

            # --- Esporta su Google My Maps ---
            if self._export_enabled and self._exporter:
                await self._export_all_regions()

            # --- Aggiorna timestamp ---
            self.last_successful_update = datetime.now()

            return {
                "velox": self.velox_by_region,
                "tutor": self.tutor_entries,
                "mymaps_urls": self.mymaps_urls,
                "last_update": self.last_successful_update,
            }

        except Exception as exc:
            raise UpdateFailed(f"Aggiornamento dati fallito: {exc}") from exc

    # ------------------------------------------------------------------ #
    #  Metodi pubblici                                                     #
    # ------------------------------------------------------------------ #

    async def async_force_refresh(self) -> None:
        """Forza un aggiornamento immediato (chiamato dal servizio HA)."""
        await self.async_refresh()

    def get_velox_for_region(self, region: str) -> list[VeloxEntry]:
        return self.velox_by_region.get(region, [])

    def get_all_velox(self) -> list[VeloxEntry]:
        all_entries = []
        for entries in self.velox_by_region.values():
            all_entries.extend(entries)
        return all_entries

    def get_total_velox_count(self) -> int:
        return sum(len(v) for v in self.velox_by_region.values())

    def get_total_tutor_count(self) -> int:
        return len(self.tutor_entries)

    def get_kml_for_region(self, region: str) -> str:
        """Genera KML per una regione specifica (per download)."""
        from .const import REGION_DISPLAY_NAMES
        velox = self.velox_by_region.get(region, [])
        region_name = REGION_DISPLAY_NAMES.get(region, region.title())
        return self._kml_generator.generate(velox, self.tutor_entries, region_name)

    # ------------------------------------------------------------------ #
    #  Metodi privati: download e parsing                                 #
    # ------------------------------------------------------------------ #

    async def _update_region_velox(
        self, session: aiohttp.ClientSession, region: str
    ) -> None:
        """Scarica e parsa il PDF velox per una regione."""
        # Controlla se la cache è ancora valida
        cached = await self._load_velox_cache(region)
        if cached is not None:
            self.velox_by_region[region] = cached
            _LOGGER.debug("Velox %s: caricati da cache (%d voci)", region, len(cached))
            return

        pdf_filename = REGION_PDF_MAP.get(region)
        if not pdf_filename:
            _LOGGER.warning("Regione sconosciuta: %s", region)
            return

        url = f"{VELOX_BASE_URL}{pdf_filename}"
        _LOGGER.info("Download PDF velox %s: %s", region, url)

        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    pdf_bytes = await resp.read()
                elif resp.status == 404:
                    _LOGGER.warning(
                        "PDF velox %s non trovato (404). "
                        "La Polizia di Stato potrebbe non aver pubblicato "
                        "ancora il calendario di questa settimana.",
                        region,
                    )
                    return
                else:
                    _LOGGER.warning(
                        "Download PDF velox %s fallito: HTTP %s", region, resp.status
                    )
                    return
        except aiohttp.ClientError as exc:
            _LOGGER.error("Errore download velox %s: %s", region, exc)
            return

        # Parsing in thread separato (operazione CPU-bound)
        if region not in self._velox_parser_cache:
            self._velox_parser_cache[region] = VeloxPDFParser(region)
        parser = self._velox_parser_cache[region]

        entries = await self.hass.async_add_executor_job(
            parser.parse_bytes, pdf_bytes
        )

        if entries:
            self.velox_by_region[region] = entries
            await self._save_velox_cache(region, entries)
            _LOGGER.info("Velox %s: %d voci caricate", region, len(entries))
        else:
            _LOGGER.warning("Velox %s: nessun dato estratto dal PDF", region)

    async def _update_tutor(self, session: aiohttp.ClientSession) -> None:
        """Scarica e parsa il PDF nazionale dei Tutor."""
        # Cache tutor
        cached = await self._load_tutor_cache()
        if cached is not None:
            self.tutor_entries = cached
            _LOGGER.debug("Tutor: caricati da cache (%d tratti)", len(cached))
            return

        # Cerca URL aggiornato dalla pagina articolo
        actual_url = await self._resolve_tutor_url(session)

        _LOGGER.info("Download PDF Tutor: %s", actual_url)
        try:
            async with session.get(actual_url) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Download PDF Tutor fallito: HTTP %s", resp.status)
                    return
                pdf_bytes = await resp.read()
        except aiohttp.ClientError as exc:
            _LOGGER.error("Errore download Tutor: %s", exc)
            return

        entries = await self.hass.async_add_executor_job(
            self._tutor_parser.parse_bytes, pdf_bytes
        )

        if entries:
            self.tutor_entries = entries
            await self._save_tutor_cache(entries)
            _LOGGER.info("Tutor: %d tratti caricati", len(entries))
        else:
            _LOGGER.warning("Tutor: nessun dato estratto dal PDF")

    async def _resolve_tutor_url(self, session: aiohttp.ClientSession) -> str:
        """
        Cerca l'URL aggiornato del PDF Tutor dalla pagina della Polizia di Stato.
        Se non riesce, usa l'URL fisso hardcoded.
        """
        import re
        try:
            async with session.get(
                "https://www.poliziadistato.it/articolo/51",
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # Cerca link PDF tutor nella pagina
                    match = re.search(
                        r'href="(/statics/\d+/elenco-tratti-controllati[^"]+\.pdf)"',
                        html,
                        re.IGNORECASE,
                    )
                    if match:
                        return f"https://www.poliziadistato.it{match.group(1)}"
        except Exception:
            pass
        # Fallback all'URL fisso
        return TUTOR_PDF_URL

    # ------------------------------------------------------------------ #
    #  Geocoding                                                          #
    # ------------------------------------------------------------------ #

    async def _geocode_all(self) -> None:
        """Aggiunge coordinate GPS a tutti i punti senza coordinate."""
        # Velox
        velox_to_geocode = [
            e for entries in self.velox_by_region.values()
            for e in entries if e.lat is None
        ]
        _LOGGER.debug("Geocoding velox: %d punti da elaborare", len(velox_to_geocode))

        for entry in velox_to_geocode:
            lat, lng = await self._geocoder.geocode_road(
                entry.road_name, entry.province, entry.region
            )
            entry.lat = lat
            entry.lng = lng
            # Piccola pausa per non saturare Nominatim
            await asyncio.sleep(0.1)

        # Tutor
        tutor_to_geocode = [e for e in self.tutor_entries if e.lat_a is None]
        _LOGGER.debug("Geocoding tutor: %d tratti da elaborare", len(tutor_to_geocode))

        for entry in tutor_to_geocode:
            lat_a, lng_a = await self._geocoder.geocode_highway_point(
                entry.highway, entry.point_a
            )
            lat_b, lng_b = await self._geocoder.geocode_highway_point(
                entry.highway, entry.point_b
            )
            entry.lat_a, entry.lng_a = lat_a, lng_a
            entry.lat_b, entry.lng_b = lat_b, lng_b
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------------ #
    #  Export Google My Maps                                              #
    # ------------------------------------------------------------------ #

    async def _export_all_regions(self) -> None:
        """Esporta i dati su Google My Maps per ogni regione."""
        from .const import REGION_DISPLAY_NAMES
        for region in self.regions:
            velox = self.velox_by_region.get(region, [])
            region_name = REGION_DISPLAY_NAMES.get(region, region.title())
            try:
                url = await self._exporter.export(
                    velox, self.tutor_entries, region_name
                )
                if url:
                    self.mymaps_urls[region] = url
            except Exception as exc:
                _LOGGER.error("Export MyMaps %s fallito: %s", region, exc)

    # ------------------------------------------------------------------ #
    #  Cache su disco                                                     #
    # ------------------------------------------------------------------ #

    def _velox_cache_path(self, region: str) -> str:
        return os.path.join(self._config_dir, f"autovelox_cache_{region}.json")

    def _tutor_cache_path(self) -> str:
        return os.path.join(self._config_dir, CACHE_FILE_TUTOR)

    async def _load_velox_cache(self, region: str) -> Optional[list[VeloxEntry]]:
        """Carica cache velox da disco. Ritorna None se cache mancante/scaduta."""
        path = self._velox_cache_path(region)
        return await self.hass.async_add_executor_job(
            self._read_velox_cache, path
        )

    def _read_velox_cache(self, path: str) -> Optional[list[VeloxEntry]]:
        if not os.path.exists(path):
            return None
        try:
            mtime = os.path.getmtime(path)
            age_days = (datetime.now().timestamp() - mtime) / 86400
            if age_days > CACHE_MAX_AGE_DAYS:
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [VeloxEntry.from_dict(d) for d in data]
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None

    async def _save_velox_cache(self, region: str, entries: list[VeloxEntry]) -> None:
        path = self._velox_cache_path(region)
        await self.hass.async_add_executor_job(
            self._write_cache, path, [e.to_dict() for e in entries]
        )

    async def _load_tutor_cache(self) -> Optional[list[TutorEntry]]:
        path = self._tutor_cache_path()
        return await self.hass.async_add_executor_job(
            self._read_tutor_cache, path
        )

    def _read_tutor_cache(self, path: str) -> Optional[list[TutorEntry]]:
        if not os.path.exists(path):
            return None
        try:
            mtime = os.path.getmtime(path)
            age_days = (datetime.now().timestamp() - mtime) / 86400
            if age_days > CACHE_MAX_AGE_DAYS:
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [TutorEntry.from_dict(d) for d in data]
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None

    async def _save_tutor_cache(self, entries: list[TutorEntry]) -> None:
        path = self._tutor_cache_path()
        await self.hass.async_add_executor_job(
            self._write_cache, path, [e.to_dict() for e in entries]
        )

    @staticmethod
    def _write_cache(path: str, data: list) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
        except OSError as exc:
            _LOGGER.warning("Impossibile scrivere cache %s: %s", path, exc)