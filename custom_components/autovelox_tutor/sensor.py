"""
Sensori Home Assistant per Autovelox & Tutor.
Crea entità per:
- Conteggio velox per regione
- Conteggio tutor totale
- URL Google My Maps per regione
- Timestamp ultimo aggiornamento
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_CONTROL_TYPE,
    ATTR_DIRECTION,
    ATTR_HIGHWAY,
    ATTR_LAST_UPDATE,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_MYMAPS_URL,
    ATTR_POINT_A,
    ATTR_POINT_B,
    ATTR_PROVINCE,
    ATTR_REGION,
    ATTR_ROAD_NAME,
    ATTR_ROAD_TYPE,
    ATTR_TOTAL_TUTOR,
    ATTR_TOTAL_VELOX,
    ATTR_VALID_FROM,
    ATTR_VALID_TO,
    CONF_REGIONS,
    DOMAIN,
    INTEGRATION_VERSION,
    REGION_DISPLAY_NAMES,
)
from .coordinator import AutoveloxCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea le entità sensore per questa config entry."""
    coordinator: AutoveloxCoordinator = hass.data[DOMAIN][entry.entry_id]
    regions: list[str] = entry.data.get(CONF_REGIONS, [])

    entities: list[SensorEntity] = []

    # Sensore riepilogo globale
    entities.append(AutoveloxSummarysensor(coordinator, entry))

    # Sensori per regione
    for region in regions:
        entities.append(VeloxRegionSensor(coordinator, entry, region))
        entities.append(MyMapsSensor(coordinator, entry, region))

    # Sensore Tutor (nazionale)
    entities.append(TutorSensor(coordinator, entry))

    async_add_entities(entities, update_before_add=True)


# --------------------------------------------------------------------------- #
#  Device info condiviso                                                       #
# --------------------------------------------------------------------------- #

def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Autovelox & Tutor Italia",
        manufacturer="Polizia di Stato",
        model="Controllo Elettronico Velocità",
        sw_version=INTEGRATION_VERSION,
        configuration_url="https://www.poliziadistato.it/articolo/autovelox-e-tutor-dove-sono",
    )


# --------------------------------------------------------------------------- #
#  Sensore riepilogo globale                                                   #
# --------------------------------------------------------------------------- #

class AutoveloxSummaryensor(CoordinatorEntity, SensorEntity):
    """Sensore riepilogo: mostra conteggio totale velox + tutor."""

    _attr_icon = "mdi:car-speed-limiter"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "controlli"

    def __init__(
        self, coordinator: AutoveloxCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_summary"
        self._attr_name = "Autovelox & Tutor - Riepilogo"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int:
        return (
            self.coordinator.get_total_velox_count()
            + self.coordinator.get_total_tutor_count()
        )

    @property
    def extra_state_attributes(self) -> dict:
        last = self.coordinator.last_successful_update
        return {
            ATTR_TOTAL_VELOX: self.coordinator.get_total_velox_count(),
            ATTR_TOTAL_TUTOR: self.coordinator.get_total_tutor_count(),
            ATTR_LAST_UPDATE: last.isoformat() if last else None,
            "regioni_monitorate": len(
                self._entry.data.get(CONF_REGIONS, [])
            ),
        }


# --------------------------------------------------------------------------- #
#  Sensore velox per regione                                                   #
# --------------------------------------------------------------------------- #

class VeloxRegionSensor(CoordinatorEntity, SensorEntity):
    """Sensore con tutti i velox attivi per una regione."""

    _attr_icon = "mdi:radar"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "velox"

    def __init__(
        self,
        coordinator: AutoveloxCoordinator,
        entry: ConfigEntry,
        region: str,
    ) -> None:
        super().__init__(coordinator)
        self._region = region
        self._attr_unique_id = f"{entry.entry_id}_velox_{region}"
        region_name = REGION_DISPLAY_NAMES.get(region, region.title())
        self._attr_name = f"Velox {region_name}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.get_velox_for_region(self._region))

    @property
    def extra_state_attributes(self) -> dict:
        entries = self.coordinator.get_velox_for_region(self._region)
        punti = []
        for e in entries:
            punto = {
                ATTR_ROAD_TYPE: e.road_type,
                ATTR_ROAD_NAME: e.road_name,
                ATTR_PROVINCE: e.province,
                ATTR_CONTROL_TYPE: "velox",
            }
            if e.lat is not None:
                punto[ATTR_LATITUDE] = round(e.lat, 6)
                punto[ATTR_LONGITUDE] = round(e.lng, 6)
            if e.valid_from:
                punto[ATTR_VALID_FROM] = e.valid_from.isoformat()
            if e.valid_to:
                punto[ATTR_VALID_TO] = e.valid_to.isoformat()
            punti.append(punto)

        return {
            ATTR_REGION: REGION_DISPLAY_NAMES.get(self._region, self._region),
            "punti": punti,
            "aggiornato": (
                self.coordinator.last_successful_update.isoformat()
                if self.coordinator.last_successful_update else None
            ),
        }


# --------------------------------------------------------------------------- #
#  Sensore tutor nazionale                                                     #
# --------------------------------------------------------------------------- #

class TutorSensor(CoordinatorEntity, SensorEntity):
    """Sensore con tutti i tratti Tutor nazionali."""

    _attr_icon = "mdi:highway"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "tratti"

    def __init__(
        self,
        coordinator: AutoveloxCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_tutor"
        self._attr_name = "Tutor Autostrade Italia"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> int:
        return self.coordinator.get_total_tutor_count()

    @property
    def extra_state_attributes(self) -> dict:
        tratti = []
        for e in self.coordinator.tutor_entries:
            tratto = {
                ATTR_HIGHWAY: e.highway,
                ATTR_POINT_A: e.point_a,
                ATTR_POINT_B: e.point_b,
                ATTR_DIRECTION: e.direction,
                ATTR_CONTROL_TYPE: "tutor",
            }
            if e.lat_a is not None:
                tratto["lat_inizio"] = round(e.lat_a, 6)
                tratto["lng_inizio"] = round(e.lng_a, 6)
            if e.lat_b is not None:
                tratto["lat_fine"] = round(e.lat_b, 6)
                tratto["lng_fine"] = round(e.lng_b, 6)
            if e.note:
                tratto["nota"] = e.note
            tratti.append(tratto)

        # Raggruppa per autostrada per leggibilità
        per_autostrada: dict[str, list] = {}
        for t in tratti:
            hw = t[ATTR_HIGHWAY]
            per_autostrada.setdefault(hw, []).append(t)

        return {
            "tratti_per_autostrada": per_autostrada,
            "totale_tratti": len(tratti),
            "autostrade": sorted(per_autostrada.keys()),
        }


# --------------------------------------------------------------------------- #
#  Sensore URL Google My Maps                                                  #
# --------------------------------------------------------------------------- #

class MyMapsSensor(CoordinatorEntity, SensorEntity):
    """Sensore che espone l'URL della Google My Map per una regione."""

    _attr_icon = "mdi:map-marker-multiple"

    def __init__(
        self,
        coordinator: AutoveloxCoordinator,
        entry: ConfigEntry,
        region: str,
    ) -> None:
        super().__init__(coordinator)
        self._region = region
        self._attr_unique_id = f"{entry.entry_id}_mymaps_{region}"
        region_name = REGION_DISPLAY_NAMES.get(region, region.title())
        self._attr_name = f"My Maps {region_name}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> str:
        url = self.coordinator.mymaps_urls.get(self._region)
        return url if url else "Non configurato"

    @property
    def extra_state_attributes(self) -> dict:
        return {
            ATTR_REGION: REGION_DISPLAY_NAMES.get(self._region, self._region),
            ATTR_MYMAPS_URL: self.coordinator.mymaps_urls.get(self._region),
        }