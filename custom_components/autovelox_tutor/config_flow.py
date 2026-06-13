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
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

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


# --------------------------------------------------------------------------- #
#  Helper: costruisce le opzioni regione per il SelectSelector                #
# --------------------------------------------------------------------------- #

def _region_select_options() -> list[SelectOptionDict]:
    """Lista di {value, label} per il selettore multi-regione, ordinata per nome."""
    return [
        SelectOptionDict(value=k, label=REGION_DISPLAY_NAMES[k])
        for k in sorted(REGION_PDF_MAP.keys(), key=lambda r: REGION_DISPLAY_NAMES[r])
    ]


def _weekday_select_options() -> list[SelectOptionDict]:
    """Lista di {value, label} per il selettore giorno settimana."""
    return [
        SelectOptionDict(value=k, label=WEEKDAY_DISPLAY[k])
        for k in WEEKDAY_OPTIONS
    ]


def _geocoding_provider_options() -> list[SelectOptionDict]:
    return [
        SelectOptionDict(
            value=GEO_PROVIDER_OSM,
            label="OpenStreetMap / Nominatim (gratuito, nessuna chiave)",
        ),
        SelectOptionDict(
            value=GEO_PROVIDER_GOOGLE,
            label="Google Maps Geocoding API (richiede chiave API)",
        ),
        SelectOptionDict(
            value=GEO_PROVIDER_BOTH,
            label="Entrambi: OSM prima, Google come fallback (consigliato)",
        ),
    ]


class AutoveloxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Flusso di configurazione a più step."""

    VERSION = 1

    def __init__(self) -> None:
        """Inizializza lo stato del flow (per-istanza, non di classe!)."""
        self._user_input: dict[str, Any] = {}

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

        data_schema = vol.Schema({
            vol.Required(CONF_REGIONS): SelectSelector(
                SelectSelectorConfig(
                    options=_region_select_options(),
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_UPDATE_DAY, default="lunedi"): SelectSelector(
                SelectSelectorConfig(
                    options=_weekday_select_options(),
                    multiple=False,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_UPDATE_HOUR, default=6): NumberSelector(
                NumberSelectorConfig(min=0, max=23, step=1, mode=NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
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

        data_schema = vol.Schema({
            vol.Required(CONF_GEOCODING_PROVIDER, default=GEO_PROVIDER_BOTH): SelectSelector(
                SelectSelectorConfig(
                    options=_geocoding_provider_options(),
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )
            ),
        })

        return self.async_show_form(
            step_id="geocoding",
            data_schema=data_schema,
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
            api_key = (user_input.get(CONF_GOOGLE_API_KEY) or "").strip()
            if api_key:
                valid = await self._test_google_api_key(api_key)
                if not valid:
                    errors[CONF_GOOGLE_API_KEY] = "invalid_google_api_key"
                else:
                    self._user_input[CONF_GOOGLE_API_KEY] = api_key
                    return await self.async_step_mymaps()
            else:
                # Chiave vuota: usa solo OSM
                self._user_input[CONF_GEOCODING_PROVIDER] = GEO_PROVIDER_OSM
                return await self.async_step_mymaps()

        data_schema = vol.Schema({
            vol.Optional(CONF_GOOGLE_API_KEY, default=""): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        })

        return self.async_show_form(
            step_id="google_api_key",
            data_schema=data_schema,
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
            return self._create_entry()

        data_schema = vol.Schema({
            vol.Required(CONF_EXPORT_MYMAPS, default=False): BooleanSelector(),
        })

        return self.async_show_form(
            step_id="mymaps",
            data_schema=data_schema,
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
        Step 5: Inserimento credenziali OAuth + avvio Device Authorization Flow.

        NOTA: Google richiede un Client ID / Client Secret OAuth2 (tipo
        "Applicazione desktop") creato su Google Cloud Console. Li chiediamo
        qui prima di avviare il device flow.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = (user_input.get("google_client_id") or "").strip()
            client_secret = (user_input.get("google_client_secret") or "").strip()

            if not client_id or not client_secret:
                errors["base"] = "missing_oauth_credentials"
            else:
                self._user_input["google_client_id"] = client_id
                self._user_input["google_client_secret"] = client_secret
                return await self.async_step_google_oauth_device()

        data_schema = vol.Schema({
            vol.Required("google_client_id"): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required("google_client_secret"): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        })

        return self.async_show_form(
            step_id="google_oauth",
            data_schema=data_schema,
            description_placeholders={
                "instructions": (
                    "Per esportare su Google My Maps è necessario un OAuth "
                    "Client ID di tipo 'Applicazione desktop':\n\n"
                    "1. Vai su https://console.cloud.google.com\n"
                    "2. Crea/seleziona un progetto\n"
                    "3. Abilita 'Google Drive API'\n"
                    "4. Credenziali → Crea credenziali → ID client OAuth 2.0\n"
                    "5. Tipo applicazione: 'Applicazione desktop'\n"
                    "6. Copia Client ID e Client Secret qui sotto"
                )
            },
            errors=errors,
        )

    async def async_step_google_oauth_device(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """
        Step 5b: Avvia il Device Authorization Flow e mostra il codice utente.
        """
        if user_input is not None:
            return await self.async_step_google_oauth_poll()

        from .google_maps import OAUTH_SCOPES
        import aiohttp

        client_id = self._user_input.get("google_client_id", "")
        client_secret = self._user_input.get("google_client_secret", "")

        device_info: dict[str, Any] = {}
        try:
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

        if device_info.get("error"):
            return self.async_show_form(
                step_id="google_oauth_device",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "instructions": (
                        f"Errore avvio autorizzazione Google: "
                        f"{device_info.get('error_description', device_info['error'])}\n\n"
                        "Verifica Client ID/Secret e riprova."
                    ),
                    "user_code": "—",
                    "verify_url": "—",
                },
                errors={"base": "oauth_device_error"},
            )

        user_code = device_info.get("user_code", "N/D")
        verify_url = device_info.get("verification_url", "https://www.google.com/device")
        if device_info.get("device_code"):
            self._user_input["_device_code"] = device_info["device_code"]

        return self.async_show_form(
            step_id="google_oauth_device",
            data_schema=vol.Schema({}),
            description_placeholders={
                "user_code": user_code,
                "verify_url": verify_url,
                "instructions": (
                    f"1. Apri {verify_url}\n"
                    f"2. Inserisci il codice: {user_code}\n"
                    "3. Accedi con il tuo account Google e clicca 'Consenti'\n"
                    "4. Torna qui e clicca 'Avanti' per completare"
                ),
            },
        )

    async def async_step_google_oauth_poll(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """
        Step 5c: Polling del token OAuth dopo che l'utente ha autorizzato.
        Tenta fino a 5 volte con 2 secondi di attesa tra i tentativi.
        """
        import asyncio
        import json
        import time

        import aiohttp

        device_code = self._user_input.get("_device_code", "")
        client_id = self._user_input.get("google_client_id", "")
        client_secret = self._user_input.get("google_client_secret", "")

        token_data: dict[str, Any] = {}
        if device_code and client_id and client_secret:
            params = {
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth2:grant-type:device_code",
            }
            for _ in range(5):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            "https://oauth2.googleapis.com/token", data=params
                        ) as resp:
                            token_data = await resp.json()

                    if token_data.get("access_token"):
                        break

                    error = token_data.get("error", "")
                    if error == "authorization_pending":
                        await asyncio.sleep(2)
                        continue

                    _LOGGER.warning("OAuth polling errore: %s", error)
                    break
                except Exception as exc:
                    _LOGGER.warning("OAuth polling exception: %s", exc)
                    await asyncio.sleep(2)

        if token_data.get("access_token"):
            token_data["obtained_at"] = time.time()
            self._user_input["_google_token"] = json.dumps(token_data)
            self._user_input.pop("_device_code", None)
            _LOGGER.info("Google OAuth completato con successo")
            return self._create_entry()

        # Token non ottenuto: mostra schermata con scelta retry/skip
        data_schema = vol.Schema({
            vol.Required("retry_choice", default="retry"): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="retry", label="Riprova (ho appena autorizzato)"),
                        SelectOptionDict(value="skip", label="Salta (configura My Maps in seguito)"),
                    ],
                    multiple=False,
                    mode=SelectSelectorMode.LIST,
                )
            ),
        })

        return self.async_show_form(
            step_id="google_oauth_poll",
            data_schema=data_schema,
            description_placeholders={
                "error": (
                    "Autorizzazione non ancora ricevuta o scaduta.\n"
                    "Assicurati di aver completato l'autorizzazione su Google, "
                    "poi seleziona 'Riprova'."
                )
            },
            errors={"base": "oauth_pending"},
        )

    async def async_step_google_oauth_poll_submit(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Gestisce la scelta retry/skip dal form di polling (vedi async_step_google_oauth_poll)."""
        # In HA il submit di una form richiama lo stesso step_id, quindi
        # questo metodo non viene normalmente raggiunto: la logica di
        # retry/skip è gestita direttamente in async_step_google_oauth_poll
        # quando user_input è presente. Lasciato per compatibilità.
        if user_input and user_input.get("retry_choice") == "skip":
            self._user_input[CONF_EXPORT_MYMAPS] = False
            self._user_input.pop("_device_code", None)
            return self._create_entry()
        return await self.async_step_google_oauth_poll()

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

        data_schema = vol.Schema({
            vol.Required(CONF_REGIONS, default=current_regions): SelectSelector(
                SelectSelectorConfig(
                    options=_region_select_options(),
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_UPDATE_DAY, default=current_day): SelectSelector(
                SelectSelectorConfig(
                    options=_weekday_select_options(),
                    multiple=False,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_UPDATE_HOUR, default=current_hour): NumberSelector(
                NumberSelectorConfig(min=0, max=23, step=1, mode=NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
        )
