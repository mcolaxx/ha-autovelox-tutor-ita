"""Costanti per l'integrazione Autovelox & Tutor Italia."""
 
DOMAIN = "autovelox_tutor"
INTEGRATION_VERSION = "1.0.0"
 
# --- Configurazione ---
CONF_REGIONS = "regions"
CONF_GEOCODING_PROVIDER = "geocoding_provider"
CONF_GOOGLE_API_KEY = "google_api_key"
CONF_GOOGLE_TOKEN = "google_token"
CONF_UPDATE_DAY = "update_day"
CONF_UPDATE_HOUR = "update_hour"
CONF_EXPORT_MYMAPS = "export_mymaps"
 
# --- Provider geocoding ---
GEO_PROVIDER_OSM = "openstreetmap"
GEO_PROVIDER_GOOGLE = "google"
GEO_PROVIDER_BOTH = "both"
 
# --- URL sorgenti ---
VELOX_BASE_URL = "https://www.poliziadistato.it/statics/34/"
TUTOR_PDF_URL = "https://www.poliziadistato.it/statics/19/elenco-tratti-controllati-con-il-tutor-maggio-2026.pdf"
TUTOR_ARTICLE_URL = "https://www.poliziadistato.it/articolo/51"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
 
# --- Google OAuth2 ---
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_MAPS_SCOPE = "https://www.googleapis.com/auth/mymaps"
 
# Headers per non essere bloccati dal sito Polizia di Stato
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
    "Accept-Language": "it-IT,it;q=0.9",
    "Referer": "https://www.poliziadistato.it/",
}
 
# --- Mappa regione → nome file PDF velox ---
REGION_PDF_MAP = {
    "abruzzo": "abruzzo.pdf",
    "basilicata": "basilicata.pdf",
    "calabria": "calabria.pdf",
    "campania": "campania.pdf",
    "emilia_romagna": "emilia-romagna.pdf",
    "friuli_venezia_giulia": "friuli-venezia-giulia.pdf",
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
    "trentino_alto_adige": "trentino-alto-adige.pdf",
    "umbria": "umbria.pdf",
    "valle_daosta": "valle-daosta.pdf",
    "veneto": "veneto.pdf",
}
 
# Nomi leggibili per la UI
REGION_DISPLAY_NAMES = {
    "abruzzo": "Abruzzo",
    "basilicata": "Basilicata",
    "calabria": "Calabria",
    "campania": "Campania",
    "emilia_romagna": "Emilia-Romagna",
    "friuli_venezia_giulia": "Friuli-Venezia Giulia",
    "lazio": "Lazio",
    "liguria": "Liguria",
    "lombardia": "Lombardia",
    "marche": "Marche",
    "molise": "Molise",
    "piemonte": "Piemonte",
    "puglia": "Puglia",
    "sardegna": "Sardegna",
    "sicilia": "Sicilia",
    "toscana": "Toscana",
    "trentino_alto_adige": "Trentino-Alto Adige",
    "umbria": "Umbria",
    "valle_daosta": "Valle d'Aosta",
    "veneto": "Veneto",
}
 
# --- Giorni settimana ---
WEEKDAY_OPTIONS = {
    "lunedi": 0,
    "martedi": 1,
    "mercoledi": 2,
    "giovedi": 3,
    "venerdi": 4,
    "sabato": 5,
    "domenica": 6,
}
 
WEEKDAY_DISPLAY = {
    "lunedi": "Lunedì",
    "martedi": "Martedì",
    "mercoledi": "Mercoledì",
    "giovedi": "Giovedì",
    "venerdi": "Venerdì",
    "sabato": "Sabato",
    "domenica": "Domenica",
}
 
# --- Codici provincia per validazione ---
PROVINCE_CODES = {
    # Abruzzo
    "AQ", "CH", "PE", "TE",
    # Basilicata
    "MT", "PZ",
    # Calabria
    "CZ", "CS", "KR", "RC", "VV",
    # Campania
    "AV", "BN", "CE", "NA", "SA",
    # Emilia-Romagna
    "BO", "FE", "FC", "MO", "PR", "PC", "RA", "RE", "RN",
    # Friuli
    "GO", "PN", "TS", "UD",
    # Lazio
    "FR", "LT", "RI", "RM", "VT",
    # Liguria
    "GE", "IM", "SP", "SV",
    # Lombardia
    "BG", "BS", "CO", "CR", "LC", "LO", "MB", "MI", "MN", "PV", "SO", "VA",
    # Marche
    "AN", "AP", "FM", "MC", "PU",
    # Molise
    "CB", "IS",
    # Piemonte
    "AL", "AT", "BI", "CN", "NO", "TO", "VB", "VC",
    # Puglia
    "BA", "BT", "BR", "FG", "LE", "TA",
    # Sardegna
    "CA", "CI", "MD", "NU", "OG", "OR", "OT", "SS", "VS",
    # Sicilia
    "AG", "CL", "CT", "EN", "ME", "PA", "RG", "SR", "TP",
    # Toscana
    "AR", "FI", "GR", "LI", "LU", "MS", "PI", "PT", "PO", "SI",
    # Trentino
    "BZ", "TN",
    # Umbria
    "PG", "TR",
    # Valle d'Aosta
    "AO",
    # Veneto
    "BL", "PD", "RO", "TV", "VE", "VR", "VI",
}
 
# --- Attributi entità HA ---
ATTR_ROAD_TYPE = "tipo_strada"
ATTR_ROAD_NAME = "nome_strada"
ATTR_PROVINCE = "provincia"
ATTR_REGION = "regione"
ATTR_CONTROL_TYPE = "tipo_controllo"  # "velox" o "tutor"
ATTR_VALID_FROM = "valido_dal"
ATTR_VALID_TO = "valido_al"
ATTR_HIGHWAY = "autostrada"
ATTR_POINT_A = "punto_inizio"
ATTR_POINT_B = "punto_fine"
ATTR_DIRECTION = "direzione"
ATTR_LATITUDE = "latitudine"
ATTR_LONGITUDE = "longitudine"
ATTR_LAST_UPDATE = "ultimo_aggiornamento"
ATTR_TOTAL_VELOX = "totale_velox"
ATTR_TOTAL_TUTOR = "totale_tutor"
ATTR_MYMAPS_URL = "url_mia_mappa"
 
# --- Nomi sensori ---
SENSOR_VELOX_COUNT = "velox_attivi"
SENSOR_TUTOR_COUNT = "tutor_attivi"
SENSOR_LAST_UPDATE = "ultimo_aggiornamento"
SENSOR_MYMAPS_URL = "url_google_mymaps"
 
# --- Cache ---
CACHE_FILE_VELOX = "autovelox_tutor_velox_cache.json"
CACHE_FILE_TUTOR = "autovelox_tutor_tutor_cache.json"
CACHE_FILE_GEOCODE = "autovelox_tutor_geocode_cache.json"
CACHE_MAX_AGE_DAYS = 8  # Invalida cache dopo 8 giorni (aggiornamento settimanale)