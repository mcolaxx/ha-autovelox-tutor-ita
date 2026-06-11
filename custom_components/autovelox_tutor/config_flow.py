"""
Config Flow per Autovelox & Tutor Italia.
Guida l'utente attraverso:
  Step 1: Selezione regioni + giorno aggiornamento
  Step 2: Scelta provider geocoding
  Step 3 (opzionale): Chiave API Google Maps
  Step 4 (opzionale): Autenticazione Google OAuth2 per My Maps
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_EXPORT_MYMAPS,
    CONF_GEOCODING_PROVIDER,
    CONF_GOOGLE_API_KEY,
    CONF_REGIONS,
    CONF_UPDATE_DAY,
    CONF_UPDATE_HOUR,
    DOMAIN,
    GEO_PROVIDER_BOTH,
    GEO_PROVIDER_GOOGLE,
    GEO_PROVIDER_OSM,
    REGION_DISPLAY_NAMES,
    REGION_PDF_MAP,
    WEEKDAY_DISPLAY,
    WEEKDAY_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)


class AutoveloxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Flusso di configurazione a più step."""

    VERSION = 1
    _user_input: dict = {}

    async def async_step_user(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """
        Step 1: Selezione regioni e giorno di aggiornamento.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input.get(CONF_REGIONS, [])
            if not selected:
                errors[CONF_REGIONS] = "no_regions_selected"
            else:
                self._user_input.update(user_input)
                return await self.async_step_geocoding()

        # Opzioni regioni per la UI (multi-select)
        region_options = {
            k: REGION_DISPLAY_NAMES[k]
            for k in sorted(REGION_PDF_MAP.keys(), key=lambda r: REGION_DISPLAY_NAMES[r])
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_REGIONS): vol.All(
                    # In HA config flow i multi-select si fanno con cv.multi_select
                    # Qui usiamo una lista di stringhe
                    list,
                    vol.Length(min=1),
                    [vol.In(region_options)],
                ),
                vol.Required(CONF_UPDATE_DAY, default="lunedi"): vol.In(
                    {k: WEEKDAY_DISPLAY[k] for k in WEEKDAY_OPTIONS}
                ),
                vol.Required(CONF_UPDATE_HOUR, default=6): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=23)
                ),
            }),
            description_placeholders={
                "description": (
                    "Seleziona le regioni da monitorare. "
                    "I dati vengono aggiornati automaticamente ogni settimana."
                )
            },
            errors=errors,
        )

    async def async_step_geocoding(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """
        Step 2: Scelta provider geocoding.
        """
        if user_input is not None:
            self._user_input.update(user_input)
            provider = user_input.get(CONF_GEOCODING_PROVIDER, GEO_PROVIDER_OSM)
            if provider in (GEO_PROVIDER_GOOGLE, GEO_PROVIDER_BOTH):
                return await self.async_step_google_api_key()
            return await self.async_step_mymaps()

        return self.async_show_form(
            step_id="geocoding",
            data_schema=vol.Schema({
                vol.Required(CONF_GEOCODING_PROVIDER, default=GEO_PROVIDER_BOTH): vol.In({
                    GEO_PROVIDER_OSM: "OpenStreetMap / Nominatim (gratuito, nessuna chiave)",
                    GEO_PROVIDER_GOOGLE: "Google Maps Geocoding API (richiede chiave API)",
                    GEO_PROVIDER_BOTH: "Entrambi: OSM prima, Google come fallback (consigliato)",
                }),
            }),
            description_placeholders={
                "description": (
                    "Il geocoding converte i nomi delle strade in coordinate GPS. "
                    "OpenStreetMap è gratuito e non richiede registrazione. "
                    "Google Maps è più preciso ma richiede una chiave API gratuita."
                )
            },
        )

    async def async_step_google_api_key(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """
        Step 3 (opzionale): Chiave API Google Maps Geocoding.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input.get(CONF_GOOGLE_API_KEY, "").strip()
            if api_key:
                # Verifica rapidamente la chiave
                valid = await self._test_google_api_key(api_key)
                if not valid:
                    errors[CONF_GOOGLE_API_KEY] = "invalid_google_api_key"
                else:
                    self._user_input[CONF_GOOGLE_API_KEY] = api_key
                    return await self.async_step_mymaps()
            else:
                # Chiave vuota: torna a OSM only
                self._user_input[CONF_GEOCODING_PROVIDER] = GEO_PROVIDER_OSM
                return await self.async_step_mymaps()

        return self.async_show_form(
            step_id="google_api_key",
            data_schema=vol.Schema({
                vol.Optional(CONF_GOOGLE_API_KEY, default=""): str,
            }),
            description_placeholders={
                "instructions": (
                    "1. Vai su https://console.cloud.google.com\n"
                    "2. Crea un progetto\n"
                    "3. Abilita 'Geocoding API'\n"
                    "4. Crea una chiave API\n"
                    "5. Incolla la chiave qui sotto\n\n"
                    "Lascia vuoto per usare solo OpenStreetMap."
                )
            },
            errors=errors,
        )

    async def async_step_mymaps(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """
        Step 4: Abilita/disabilita export Google My Maps.
        """
        if user_input is not None:
            self._user_input.update(user_input)
            export = user_input.get(CONF_EXPORT_MYMAPS, False)
            if export:
                return await self.async_step_google_oauth()
            # Crea entry senza OAuth
            return self._create_entry()

        return self.async_show_form(
            step_id="mymaps",
            data_schema=vol.Schema({
                vol.Required(CONF_EXPORT_MYMAPS, default=False): bool,
            }),
            description_placeholders={
                "description": (
                    "Abilitando questa opzione, i punti velox e tutor "
                    "verranno salvati automaticamente su Google My Maps "
                    "nel tuo account Google.\n\n"
                    "Richiede autenticazione con il tuo account Google "
                    "(passo successivo)."
                )
            },
        )

    async def async_step_google_oauth(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """
        Step 5: Avvia Device Authorization Flow Google.
        Mostra il codice che l'utente deve inserire su google.com/device
        """
        if user_input is not None:
            # L'utente ha confermato di aver autorizzato
            # Il polling viene fatto dal coordinator al primo avvio
            return self._create_entry()

        # Avvia il device flow per ottenere user_code
        from .google_maps import GoogleOAuthManager, OAUTH_SCOPES
        import os

        # Usa client_id/secret di default (l'utente deve averli configurati
        # oppure usiamo quelli dell'integrazione)
        client_id = self._user_input.get("google_client_id", "")
        client_secret = self._user_input.get("google_client_secret", "")

        device_info = {}
        if client_id and client_secret:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    params = {
                        "client_id": client_id,
                        "scope": " ".join(OAUTH_SCOPES),
                    }
                    async with session.post(
                        "https://oauth2.googleapis.com/device/code",
                        data=params,
                    ) as resp:
                        device_info = await resp.json()
            except Exception as exc:
                _LOGGER.warning("Device flow fallito: %s", exc)

        user_code = device_info.get("user_code", "N/D")
        verify_url = device_info.get("verification_url", "https://google.com/device")
        # Salva device_code per il polling
        if device_info.get("device_code"):
            self._user_input["_device_code"] = device_info["device_code"]

        return self.async_show_form(
            step_id="google_oauth",
            data_schema=vol.Schema({}),
            description_placeholders={
                "user_code": user_code,
                "verify_url": verify_url,
                "instructions": (
                    f"1. Apri {verify_url}\n"
                    f"2. Inserisci il codice: {user_code}\n"
                    "3. Accedi con il tuo account Google\n"
                    "4. Clicca 'Consenti'\n"
                    "5. Torna qui e clicca 'Avanti'"
                ),
            },
        )

    # ------------------------------------------------------------------ #
    #  Options Flow (modifica configurazione esistente)                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "AutoveloxOptionsFlow":
        return AutoveloxOptionsFlow(config_entry)

    # ------------------------------------------------------------------ #
    #  Helpers privati                                                    #
    # ------------------------------------------------------------------ #

    def _create_entry(self) -> FlowResult:
        """Crea la config entry finale."""
        # Rimuovi dati temporanei
        self._user_input.pop("_device_code", None)

        return self.async_create_entry(
            title="Autovelox & Tutor Italia",
            data=self._user_input,
        )

    async def _test_google_api_key(self, api_key: str) -> bool:
        """Testa rapidamente la chiave API Google."""
        import aiohttp
        try:
            params = {
                "address": "Roma, Italia",
                "key": api_key,
                "language": "it",
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://maps.googleapis.com/maps/api/geocode/json",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("status") not in (
                            "REQUEST_DENIED", "INVALID_REQUEST"
                        )
        except Exception:
            pass
        return False


class AutoveloxOptionsFlow(config_entries.OptionsFlow):
    """Permette di modificare la configurazione senza rimuovere l'integrazione."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_regions = self.config_entry.data.get(CONF_REGIONS, [])
        current_day = self.config_entry.data.get(CONF_UPDATE_DAY, "lunedi")
        current_hour = self.config_entry.data.get(CONF_UPDATE_HOUR, 6)

        region_options = {
            k: REGION_DISPLAY_NAMES[k]
            for k in sorted(REGION_PDF_MAP.keys(), key=lambda r: REGION_DISPLAY_NAMES[r])
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_REGIONS, default=current_regions): vol.All(
                    list, [vol.In(region_options)]
                ),
                vol.Required(CONF_UPDATE_DAY, default=current_day): vol.In(
                    {k: WEEKDAY_DISPLAY[k] for k in WEEKDAY_OPTIONS}
                ),
                vol.Required(CONF_UPDATE_HOUR, default=current_hour): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=23)
                ),
            }),
        )