"""Config flow per l'integrazione Autovelox & Tutor."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import config_entry_oauth2_flow
from .const import DOMAIN, REGION_PDF_MAP, WEEKDAYS

REGION_OPTIONS = {k: k.replace('_', ' ').title() 
                  for k in REGION_PDF_MAP.keys()}

class AutoveloxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gestisce la configurazione iniziale."""
    
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Step 1: Selezione regione e giorno aggiornamento."""
        if user_input is not None:
            return await self.async_step_google_auth(user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("region"): vol.In(REGION_OPTIONS),
                vol.Required("update_day", default="lunedi"): vol.In(WEEKDAYS),
                vol.Optional("google_maps_api_key", default=""): str,
            }),
            description_placeholders={
                "description": (
                    "Seleziona la regione per cui vuoi monitorare "
                    "autovelox e tutor. I dati vengono aggiornati "
                    "automaticamente ogni settimana."
                )
            }
        )

    async def async_step_google_auth(self, user_input):
        """Step 2: Autenticazione Google OAuth2."""
        # Salva config e avvia OAuth
        self._config = user_input
        # Reindirizza a OAuth Google
        return self.async_external_step(
            step_id="google_oauth",
            url=self._get_oauth_url()
        )

    def _get_oauth_url(self) -> str:
        """Genera URL OAuth Google."""
        # Implementazione OAuth2 flow
        return "https://accounts.google.com/o/oauth2/auth?..."