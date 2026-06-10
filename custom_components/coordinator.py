"""DataUpdateCoordinator per aggiornamenti periodici."""
import logging
from datetime import timedelta
import aiohttp
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import (
    DOMAIN, VELOX_BASE_URL, TUTOR_PDF_URL, REGION_PDF_MAP
)
from .parsers.velox_parser import VeloxPDFParser
from .parsers.tutor_parser import TutorPDFParser
from .geocoder import RoadGeocoder

_LOGGER = logging.getLogger(__name__)
UPDATE_INTERVAL = timedelta(days=7)

class AutoveloxCoordinator(DataUpdateCoordinator):
    """Coordina il download e parsing dei dati."""

    def __init__(self, hass, region: str, geocoder: RoadGeocoder):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.region = region
        self.geocoder = geocoder
        self._velox_parser = VeloxPDFParser(region)
        self._tutor_parser = TutorPDFParser()

    async def _async_update_data(self):
        """Scarica e parsa i PDF aggiornati."""
        async with aiohttp.ClientSession() as session:
            # Download PDF velox regionale
            velox_url = VELOX_BASE_URL + REGION_PDF_MAP[self.region]
            velox_entries = await self._fetch_and_parse_velox(
                session, velox_url
            )
            
            # Download PDF tutor nazionale
            tutor_entries = await self._fetch_and_parse_tutor(
                session, TUTOR_PDF_URL
            )
            
            # Geocoding di tutti i punti
            await self._geocode_all(velox_entries, tutor_entries)
            
            return {
                "velox": velox_entries,
                "tutor": tutor_entries,
                "region": self.region
            }

    async def _fetch_and_parse_velox(self, session, url):
        """Scarica e parsa il PDF velox."""
        try:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    pdf_bytes = await resp.read()
                    return self._velox_parser.parse_bytes(pdf_bytes)
                else:
                    _LOGGER.warning(
                        "PDF velox non disponibile (HTTP %s): %s",
                        resp.status, url
                    )
        except Exception as e:
            _LOGGER.error("Errore download velox: %s", e)
        return []

    async def _fetch_and_parse_tutor(self, session, url):
        """Scarica e parsa il PDF tutor."""
        try:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    pdf_bytes = await resp.read()
                    return self._tutor_parser.parse_bytes(pdf_bytes)
        except Exception as e:
            _LOGGER.error("Errore download tutor: %s", e)
        return []

    async def _geocode_all(self, velox_entries, tutor_entries):
        """Aggiunge coordinate a tutti i punti."""
        for entry in velox_entries:
            lat, lng = await self.geocoder.geocode_road(
                entry.road_name, entry.province, self.region
            )
            entry.lat, entry.lng = lat, lng

        for entry in tutor_entries:
            lat_a, lng_a = await self.geocoder.geocode_highway_point(
                entry.highway, entry.point_a
            )
            entry.lat_a, entry.lng_a = lat_a, lng_a