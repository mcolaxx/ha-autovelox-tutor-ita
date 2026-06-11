"""
Integrazione Autovelox & Tutor Italia per Home Assistant.
Fonte dati: Polizia di Stato - Servizio Polizia Stradale
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change

from .const import (
    CONF_EXPORT_MYMAPS,
    CONF_GEOCODING_PROVIDER,
    CONF_GOOGLE_API_KEY,
    CONF_REGIONS,
    CONF_UPDATE_DAY,
    CONF_UPDATE_HOUR,
    DOMAIN,
    GEO_PROVIDER_OSM,
    WEEKDAY_OPTIONS,
    REGION_DISPLAY_NAMES,
)
from .coordinator import AutoveloxCoordinator
from .geocoder import RoadGeocoder
from .google_maps import GoogleMyMapsExporter, GoogleOAuthManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Schema servizio aggiornamento manuale
SERVICE_UPDATE_SCHEMA = vol.Schema({
    vol.Optional("region"): cv.string,
})

# Schema servizio download KML
SERVICE_DOWNLOAD_KML_SCHEMA = vol.Schema({
    vol.Required("region"): cv.string,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Inizializza l'integrazione dal config entry."""
    hass.data.setdefault(DOMAIN, {})

    # --- Geocoder ---
    provider = entry.data.get(CONF_GEOCODING_PROVIDER, GEO_PROVIDER_OSM)
    google_api_key = entry.data.get(CONF_GOOGLE_API_KEY)
    geocoder = RoadGeocoder(
        hass_config_dir=hass.config.config_dir,
        provider=provider,
        google_api_key=google_api_key,
    )

    # --- Google OAuth (se abilitato) ---
    exporter = None
    export_enabled = entry.data.get(CONF_EXPORT_MYMAPS, False)
    if export_enabled:
        token_file = os.path.join(
            hass.config.config_dir,
            f"autovelox_google_token_{entry.entry_id}.json",
        )
        client_id = entry.data.get("google_client_id", "")
        client_secret = entry.data.get("google_client_secret", "")
        if client_id and client_secret:
            oauth_manager = GoogleOAuthManager(
                client_id=client_id,
                client_secret=client_secret,
                token_file=token_file,
            )
            if oauth_manager.is_authorized:
                exporter = GoogleMyMapsExporter(oauth_manager)
            else:
                _LOGGER.warning(
                    "Google OAuth non completato. "
                    "Export My Maps disabilitato fino all'autorizzazione."
                )

    # --- Coordinator ---
    regions = entry.data.get(CONF_REGIONS, [])
    coordinator = AutoveloxCoordinator(
        hass=hass,
        regions=regions,
        geocoder=geocoder,
        exporter=exporter,
        export_enabled=export_enabled and exporter is not None,
    )

    # Primo aggiornamento all'avvio
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # --- Setup piattaforme (sensori) ---
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- Automazione aggiornamento programmato ---
    _setup_scheduled_update(hass, entry, coordinator)

    # --- Registrazione servizi HA ---
    _register_services(hass, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Rimuove l'integrazione."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


# --------------------------------------------------------------------------- #
#  Aggiornamento programmato                                                   #
# --------------------------------------------------------------------------- #

def _setup_scheduled_update(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: AutoveloxCoordinator,
) -> None:
    """
    Registra un listener che aggiorna i dati nel giorno/ora configurati.
    Esempio: ogni lunedì alle 06:00.
    """
    update_day_name = entry.data.get(CONF_UPDATE_DAY, "lunedi")
    update_hour = entry.data.get(CONF_UPDATE_HOUR, 6)
    update_weekday = WEEKDAY_OPTIONS.get(update_day_name, 0)

    async def _scheduled_update(now):
        """Callback eseguito all'orario programmato."""
        # Controlla se è il giorno giusto
        if now.weekday() == update_weekday:
            _LOGGER.info(
                "Aggiornamento programmato autovelox/tutor: %s",
                now.strftime("%Y-%m-%d %H:%M"),
            )
            await coordinator.async_force_refresh()

    # Registra il trigger time: ogni giorno all'ora configurata
    # Il callback controlla internamente il giorno della settimana
    remove_listener = async_track_time_change(
        hass,
        _scheduled_update,
        hour=update_hour,
        minute=0,
        second=0,
    )

    # Salva la funzione di rimozione per il cleanup
    entry.async_on_unload(remove_listener)

    _LOGGER.info(
        "Aggiornamento programmato: ogni %s alle %02d:00",
        update_day_name.capitalize(),
        update_hour,
    )


# --------------------------------------------------------------------------- #
#  Servizi HA                                                                  #
# --------------------------------------------------------------------------- #

def _register_services(
    hass: HomeAssistant,
    coordinator: AutoveloxCoordinator,
) -> None:
    """Registra i servizi chiamabili da HA (automazioni, script, UI)."""

    async def handle_update(call: ServiceCall) -> None:
        """
        Servizio: autovelox_tutor.aggiorna
        Forza un aggiornamento immediato dei dati.
        Parametro opzionale: region (es. "marche")
        """
        region = call.data.get("region")
        if region:
            _LOGGER.info("Aggiornamento forzato regione: %s", region)
        else:
            _LOGGER.info("Aggiornamento forzato: tutte le regioni")
        await coordinator.async_force_refresh()

    async def handle_download_kml(call: ServiceCall) -> None:
        """
        Servizio: autovelox_tutor.scarica_kml
        Genera e salva un file KML nella cartella /config/www/
        Parametro: region (es. "marche")
        """
        region = call.data.get("region", "")
        if not region:
            _LOGGER.warning("Servizio scarica_kml: regione non specificata")
            return

        kml_content = coordinator.get_kml_for_region(region)
        region_name = REGION_DISPLAY_NAMES.get(region, region)
        filename = f"autovelox_{region}.kml"

        # Salva in /config/www/ (accessibile via http://ha/local/)
        www_dir = os.path.join(hass.config.config_dir, "www")
        os.makedirs(www_dir, exist_ok=True)
        filepath = os.path.join(www_dir, filename)

        def _write():
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(kml_content)

        await hass.async_add_executor_job(_write)

        velox_count = len(coordinator.get_velox_for_region(region))
        tutor_count = coordinator.get_total_tutor_count()

        _LOGGER.info(
            "KML salvato: %s (%d velox + %d tutor)",
            filepath, velox_count, tutor_count,
        )

        # Notifica persistente in HA
        hass.components.persistent_notification.create(
            message=(
                f"File KML generato per **{region_name}**:\n\n"
                f"- 🚔 Velox: {velox_count} punti\n"
                f"- 📡 Tutor: {tutor_count} tratti\n\n"
                f"Scarica da: `http://TUO-HA/local/{filename}`\n\n"
                "Importa su Google My Maps:\n"
                "1. Apri [maps.google.com](https://maps.google.com)\n"
                "2. Menu → I tuoi luoghi → Mappe → Crea mappa\n"
                "3. Importa → carica il file KML"
            ),
            title=f"KML Autovelox {region_name} pronto",
            notification_id=f"autovelox_kml_{region}",
        )

    async def handle_export_mymaps(call: ServiceCall) -> None:
        """
        Servizio: autovelox_tutor.esporta_mymaps
        Forza l'export su Google My Maps per tutte le regioni.
        """
        if not coordinator._export_enabled:
            hass.components.persistent_notification.create(
                message=(
                    "Export Google My Maps non configurato.\n"
                    "Vai in Impostazioni → Integrazioni → "
                    "Autovelox & Tutor → Configura."
                ),
                title="Export My Maps non disponibile",
                notification_id="autovelox_mymaps_error",
            )
            return

        _LOGGER.info("Export forzato su Google My Maps")
        await coordinator._export_all_regions()

    # Registra i servizi
    if not hass.services.has_service(DOMAIN, "aggiorna"):
        hass.services.async_register(
            DOMAIN, "aggiorna", handle_update, schema=SERVICE_UPDATE_SCHEMA
        )

    if not hass.services.has_service(DOMAIN, "scarica_kml"):
        hass.services.async_register(
            DOMAIN, "scarica_kml", handle_download_kml,
            schema=SERVICE_DOWNLOAD_KML_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, "esporta_mymaps"):
        hass.services.async_register(
            DOMAIN, "esporta_mymaps", handle_export_mymaps,
        )