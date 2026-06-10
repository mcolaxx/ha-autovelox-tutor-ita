DOMAIN = "autovelox_tutor"
CONF_GOOGLE_TOKEN = "google_token"
CONF_REGION = "region"
CONF_UPDATE_DAY = "update_day"

BASE_URL = "https://www.poliziadistato.it"
TUTOR_PDF_URL = "https://www.poliziadistato.it/statics/19/elenco-tratti-controllati-con-il-tutor-maggio-2026.pdf"
VELOX_BASE_URL = "https://www.poliziadistato.it/statics/34/"

# Mappa regione → nome file PDF
REGION_PDF_MAP = {
    "abruzzo": "abruzzo.pdf",
    "basilicata": "basilicata.pdf",
    "calabria": "calabria.pdf",
    "campania": "campania.pdf",
    "emilia_romagna": "emilia-romagna.pdf",
    "friuli": "friuli-venezia-giulia.pdf",
    "lazio": "lazio.pdf",
    "liguria": "liguria.pdf",
    "lombardia": "lombardia.pdf",
    "marche": "marche.pdf",
    "molise": "molise.pdf",
    "piemonte": "piemonte.pdf",
    "puglia": "puglia.pdf",
    "sardegna": "sardegna.pdf",
    "sicilia": "sicilia.pdf",
    "toscana": "toscana.pdf",
    "trentino": "trentino-alto-adige.pdf",
    "umbria": "umbria.pdf",
    "valle_aosta": "valle-daosta.pdf",
    "veneto": "veneto.pdf",
}

# Giorni della settimana per aggiornamento
WEEKDAYS = {
    "lunedi": 0, "martedi": 1, "mercoledi": 2,
    "giovedi": 3, "venerdi": 4, "sabato": 5, "domenica": 6
}

ATTR_ROAD = "strada"
ATTR_PROVINCE = "provincia"
ATTR_TYPE = "tipo"  # "velox" o "tutor"
ATTR_REGION = "regione"
ATTR_VALID_FROM = "valido_dal"
ATTR_VALID_TO = "valido_al"