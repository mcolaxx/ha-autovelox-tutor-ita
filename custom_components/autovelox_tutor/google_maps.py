"""
Integrazione Google Maps:
- OAuth2 per autenticazione account Google
- Generazione file KML con punti velox/tutor
- Upload su Google My Maps via Drive API
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional
from urllib.parse import urlencode

import aiohttp

from .const import (
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    HTTP_HEADERS,
)
from .parsers.velox_parser import VeloxEntry
from .parsers.tutor_parser import TutorEntry

_LOGGER = logging.getLogger(__name__)

# Scope OAuth2 necessari
OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/mymaps",
]

# Google Drive API
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

# MIME type My Maps
MYMAPS_MIME = "application/vnd.google-apps.map"
KML_MIME = "application/vnd.google-earth.kml+xml"


class GoogleOAuthManager:
    """
    Gestisce il flusso OAuth2 per Google.
    Usa il Device Authorization Flow (no redirect URI necessario)
    oppure il flusso standard con redirect su HA.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_file: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_file = token_file
        self._token_data: dict = {}
        self._load_token()

    @property
    def is_authorized(self) -> bool:
        return bool(self._token_data.get("access_token"))

    @property
    def access_token(self) -> Optional[str]:
        return self._token_data.get("access_token")

    async def start_device_flow(self) -> dict:
        """
        Avvia il Device Authorization Flow.
        Ritorna {"user_code": ..., "verification_url": ..., "device_code": ...}
        L'utente deve visitare l'URL e inserire il codice.
        """
        params = {
            "client_id": self._client_id,
            "scope": " ".join(OAUTH_SCOPES),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://oauth2.googleapis.com/device/code",
                data=params,
            ) as resp:
                data = await resp.json()
                # Salva device_code per il polling
                self._device_code = data.get("device_code")
                self._poll_interval = data.get("interval", 5)
                return {
                    "user_code": data.get("user_code"),
                    "verification_url": data.get("verification_url"),
                    "expires_in": data.get("expires_in", 300),
                }

    async def poll_device_flow(self) -> bool:
        """
        Fa il polling per ottenere il token dopo che l'utente
        ha completato l'autorizzazione sul browser.
        Ritorna True se autorizzato, False se ancora in attesa.
        """
        if not hasattr(self, "_device_code"):
            return False

        params = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "device_code": self._device_code,
            "grant_type": "urn:ietf:params:oauth2:grant-type:device_code",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(GOOGLE_TOKEN_URL, data=params) as resp:
                data = await resp.json()

        error = data.get("error")
        if error == "authorization_pending":
            return False
        if error:
            _LOGGER.warning("OAuth2 device flow error: %s", error)
            return False

        if data.get("access_token"):
            data["obtained_at"] = time.time()
            self._token_data = data
            self._save_token()
            _LOGGER.info("Google OAuth2: autorizzazione completata")
            return True

        return False

    async def ensure_valid_token(self) -> bool:
        """Rinnova il token se scaduto."""
        if not self._token_data:
            return False

        obtained_at = self._token_data.get("obtained_at", 0)
        expires_in = self._token_data.get("expires_in", 3600)
        # Rinnova 5 minuti prima della scadenza
        if time.time() < obtained_at + expires_in - 300:
            return True

        refresh_token = self._token_data.get("refresh_token")
        if not refresh_token:
            return False

        params = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(GOOGLE_TOKEN_URL, data=params) as resp:
                data = await resp.json()

        if data.get("access_token"):
            data["refresh_token"] = refresh_token  # Preserve refresh token
            data["obtained_at"] = time.time()
            self._token_data.update(data)
            self._save_token()
            return True

        _LOGGER.warning("Refresh token Google fallito: %s", data.get("error"))
        return False

    def revoke(self) -> None:
        """Revoca l'autorizzazione e cancella il token salvato."""
        self._token_data = {}
        if os.path.exists(self._token_file):
            os.remove(self._token_file)

    def _load_token(self) -> None:
        if os.path.exists(self._token_file):
            try:
                with open(self._token_file, "r") as f:
                    self._token_data = json.load(f)
            except (OSError, json.JSONDecodeError):
                self._token_data = {}

    def _save_token(self) -> None:
        try:
            with open(self._token_file, "w") as f:
                json.dump(self._token_data, f)
        except OSError as exc:
            _LOGGER.warning("Impossibile salvare token Google: %s", exc)


class KMLGenerator:
    """Genera file KML per Google My Maps / Google Earth."""

    # Icone KML
    VELOX_ICON = "http://maps.google.com/mapfiles/kml/pal4/icon49.png"
    TUTOR_ICON = "http://maps.google.com/mapfiles/kml/pal4/icon57.png"

    def generate(
        self,
        velox_entries: list[VeloxEntry],
        tutor_entries: list[TutorEntry],
        region_name: str,
    ) -> str:
        """Genera KML completo con tutti i punti."""
        velox_kml = self._build_velox_placemarks(velox_entries)
        tutor_kml = self._build_tutor_placemarks(tutor_entries)

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
  <Document>
    <name>Autovelox e Tutor - {region_name}</name>
    <description>Aggiornato automaticamente da Home Assistant - Integrazione Autovelox &amp; Tutor Italia</description>
    <open>1</open>

    <Style id="velox_style">
      <IconStyle>
        <scale>1.1</scale>
        <Icon><href>{self.VELOX_ICON}</href></Icon>
        <hotSpot x="0.5" y="0" xunits="fraction" yunits="fraction"/>
      </IconStyle>
      <LabelStyle><scale>0.8</scale></LabelStyle>
      <BalloonStyle>
        <text><![CDATA[<b>$[name]</b><br/>$[description]]]></text>
      </BalloonStyle>
    </Style>

    <Style id="tutor_style">
      <IconStyle>
        <scale>1.1</scale>
        <Icon><href>{self.TUTOR_ICON}</href></Icon>
        <hotSpot x="0.5" y="0" xunits="fraction" yunits="fraction"/>
      </IconStyle>
      <LabelStyle><scale>0.8</scale></LabelStyle>
      <BalloonStyle>
        <text><![CDATA[<b>$[name]</b><br/>$[description]]]></text>
      </BalloonStyle>
    </Style>

    <Folder>
      <name>🚔 Autovelox - {region_name}</name>
      <open>1</open>
{velox_kml}
    </Folder>

    <Folder>
      <name>📡 Tutor Autostrade</name>
      <open>1</open>
{tutor_kml}
    </Folder>

  </Document>
</kml>"""

    def _build_velox_placemarks(self, entries: list[VeloxEntry]) -> str:
        parts = []
        for e in entries:
            if e.lat is None or e.lng is None:
                continue
            valid_str = ""
            if e.valid_from and e.valid_to:
                valid_str = f"Validità: {e.valid_from.strftime('%d/%m/%Y')} → {e.valid_to.strftime('%d/%m/%Y')}"
            desc = (
                f"Tipo: {e.road_type}\n"
                f"Strada: {e.road_name}\n"
                f"Provincia: {e.province}\n"
                f"Regione: {e.region.replace('_', ' ').title()}\n"
                f"{valid_str}"
            ).strip()
            parts.append(self._placemark(
                name=e.maps_label,
                description=desc,
                lat=e.lat,
                lng=e.lng,
                style="#velox_style",
            ))
        return "\n".join(parts)

    def _build_tutor_placemarks(self, entries: list[TutorEntry]) -> str:
        parts = []
        for e in entries:
            # Usa lat_a/lng_a come posizione del placemark (punto inizio tratto)
            lat = e.lat_a
            lng = e.lng_a
            if lat is None or lng is None:
                # Fallback: punto finale
                lat = e.lat_b
                lng = e.lng_b
            if lat is None or lng is None:
                continue
            desc = e.maps_description
            parts.append(self._placemark(
                name=e.maps_label,
                description=desc,
                lat=lat,
                lng=lng,
                style="#tutor_style",
            ))
        return "\n".join(parts)

    @staticmethod
    def _placemark(
        name: str, description: str, lat: float, lng: float, style: str
    ) -> str:
        # Escape XML
        name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        description = description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"""      <Placemark>
        <name>{name}</name>
        <description>{description}</description>
        <styleUrl>{style}</styleUrl>
        <Point>
          <coordinates>{lng:.6f},{lat:.6f},0</coordinates>
        </Point>
      </Placemark>"""


class GoogleMyMapsExporter:
    """
    Carica il KML su Google Drive come Google My Map.
    Se la mappa esiste già (stesso titolo) la aggiorna.
    """

    def __init__(self, oauth_manager: GoogleOAuthManager) -> None:
        self._oauth = oauth_manager
        self._kml_gen = KMLGenerator()

    async def export(
        self,
        velox_entries: list[VeloxEntry],
        tutor_entries: list[TutorEntry],
        region_name: str,
    ) -> Optional[str]:
        """
        Crea/aggiorna la mappa su Google My Maps.
        Ritorna l'URL della mappa oppure None in caso di errore.
        """
        if not await self._oauth.ensure_valid_token():
            _LOGGER.warning("Token Google non valido, impossibile esportare")
            return None

        kml_content = self._kml_gen.generate(velox_entries, tutor_entries, region_name)
        map_title = f"Autovelox e Tutor - {region_name}"

        async with aiohttp.ClientSession() as session:
            # Cerca mappa esistente
            file_id = await self._find_existing_map(session, map_title)

            if file_id:
                success = await self._update_map(session, file_id, kml_content)
            else:
                file_id = await self._create_map(session, map_title, kml_content)
                success = file_id is not None

        if success and file_id:
            url = f"https://www.google.com/maps/d/viewer?mid={file_id}"
            _LOGGER.info("Google My Maps aggiornata: %s", url)
            return url

        return None

    def generate_kml_only(
        self,
        velox_entries: list[VeloxEntry],
        tutor_entries: list[TutorEntry],
        region_name: str,
    ) -> str:
        """Genera solo il KML (per download locale, senza upload)."""
        return self._kml_gen.generate(velox_entries, tutor_entries, region_name)

    async def _find_existing_map(
        self, session: aiohttp.ClientSession, title: str
    ) -> Optional[str]:
        """Cerca una mappa esistente con lo stesso titolo."""
        headers = {"Authorization": f"Bearer {self._oauth.access_token}"}
        params = {
            "q": f"name='{title}' and mimeType='{MYMAPS_MIME}' and trashed=false",
            "fields": "files(id,name)",
        }
        try:
            async with session.get(DRIVE_FILES_URL, headers=headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    files = data.get("files", [])
                    if files:
                        return files[0]["id"]
        except (aiohttp.ClientError, KeyError) as exc:
            _LOGGER.warning("Ricerca mappa Google Drive fallita: %s", exc)
        return None

    async def _create_map(
        self,
        session: aiohttp.ClientSession,
        title: str,
        kml_content: str,
    ) -> Optional[str]:
        """Crea una nuova My Map caricando il KML."""
        headers = {
            "Authorization": f"Bearer {self._oauth.access_token}",
            "Content-Type": "multipart/related; boundary=boundary_autovelox",
        }
        metadata = json.dumps({"name": title, "mimeType": MYMAPS_MIME})
        kml_bytes = kml_content.encode("utf-8")

        body = (
            b"--boundary_autovelox\r\n"
            b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            + metadata.encode() + b"\r\n"
            b"--boundary_autovelox\r\n"
            b"Content-Type: " + KML_MIME.encode() + b"\r\n\r\n"
            + kml_bytes + b"\r\n"
            b"--boundary_autovelox--"
        )
        try:
            async with session.post(
                DRIVE_UPLOAD_URL,
                headers=headers,
                params={"uploadType": "multipart"},
                data=body,
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    return data.get("id")
                _LOGGER.warning("Creazione mappa fallita: HTTP %s", resp.status)
        except aiohttp.ClientError as exc:
            _LOGGER.error("Errore creazione mappa Google: %s", exc)
        return None

    async def _update_map(
        self,
        session: aiohttp.ClientSession,
        file_id: str,
        kml_content: str,
    ) -> bool:
        """Aggiorna il contenuto di una mappa esistente."""
        headers = {
            "Authorization": f"Bearer {self._oauth.access_token}",
            "Content-Type": KML_MIME,
        }
        try:
            async with session.patch(
                f"{DRIVE_UPLOAD_URL}/{file_id}",
                headers=headers,
                params={"uploadType": "media"},
                data=kml_content.encode("utf-8"),
            ) as resp:
                if resp.status == 200:
                    return True
                _LOGGER.warning("Aggiornamento mappa fallito: HTTP %s", resp.status)
        except aiohttp.ClientError as exc:
            _LOGGER.error("Errore aggiornamento mappa Google: %s", exc)
        return False