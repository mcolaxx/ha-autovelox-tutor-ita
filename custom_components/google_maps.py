"""
Integrazione con Google Maps per il salvataggio dei luoghi.
Usa Google My Maps API per creare/aggiornare mappe personalizzate.
"""
import logging
import asyncio
from typing import Optional
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import aiohttp

_LOGGER = logging.getLogger(__name__)

# Scopes OAuth necessari
SCOPES = [
    "https://www.googleapis.com/auth/drive",         # Per My Maps
    "https://www.googleapis.com/auth/drive.file",
]

class GoogleMapsExporter:
    """
    Esporta i punti di controllo su Google My Maps.
    
    Strategia:
    1. Crea un file KML con tutti i punti
    2. Carica su Google Drive come My Map
    3. Condivide il link con l'utente
    
    Alternativa: genera file KML scaricabile
    che l'utente importa manualmente.
    """

    def __init__(self, credentials: Credentials):
        self._creds = credentials

    def generate_kml(
        self,
        velox_entries: list,
        tutor_entries: list,
        region: str
    ) -> str:
        """Genera un file KML con tutti i punti."""
        kml_header = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Autovelox e Tutor - {region}</name>
    <description>Aggiornato automaticamente da HA</description>
    
    <!-- Stile Velox: icona rossa -->
    <Style id="velox_style">
      <IconStyle>
        <color>ff0000ff</color>
        <scale>1.2</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/pal3/icon21.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle><scale>0.8</scale></LabelStyle>
    </Style>
    
    <!-- Stile Tutor: icona blu -->
    <Style id="tutor_style">
      <IconStyle>
        <color>ffff8800</color>
        <scale>1.2</scale>
        <Icon>
          <href>http://maps.google.com/mapfiles/kml/pal3/icon56.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle><scale>0.8</scale></LabelStyle>
    </Style>
    
    <Folder><name>🚔 Autovelox</name>
'''.format(region=region)

        velox_placemarks = ""
        for entry in velox_entries:
            if entry.lat and entry.lng:
                velox_placemarks += f'''
      <Placemark>
        <name>{entry.maps_label}</name>
        <description>
          Tipo: {entry.road_type}
          Provincia: {entry.province}
          Valido: {entry.valid_from} - {entry.valid_to}
        </description>
        <styleUrl>#velox_style</styleUrl>
        <Point>
          <coordinates>{entry.lng},{entry.lat},0</coordinates>
        </Point>
      </Placemark>'''

        tutor_placemarks = ""
        for entry in tutor_entries:
            if entry.lat_a and entry.lng_a:
                tutor_placemarks += f'''
      <Placemark>
        <name>{entry.maps_label}</name>
        <description>
          Autostrada: {entry.highway}
          Tratto: {entry.point_a} → {entry.point_b}
          Direzione: {entry.direction}
        </description>
        <styleUrl>#tutor_style</styleUrl>
        <Point>
          <coordinates>{entry.lng_a},{entry.lat_a},0</coordinates>
        </Point>
      </Placemark>'''

        kml_footer = '''
    </Folder>
    <Folder><name>📡 Tutor</name>
{tutor}
    </Folder>
  </Document>
</kml>'''

        return (
            kml_header
            + velox_placemarks
            + kml_footer.format(tutor=tutor_placemarks)
        )

    async def upload_to_my_maps(
        self, kml_content: str, map_title: str
    ) -> Optional[str]:
        """
        Carica il KML su Google Drive come My Map.
        Ritorna l'URL della mappa.
        """
        try:
            drive_service = build('drive', 'v3', credentials=self._creds)
            
            # Cerca se esiste già una mappa con quel titolo
            results = drive_service.files().list(
                q=f"name='{map_title}' and mimeType='application/vnd.google-apps.map'",
                spaces='drive'
            ).execute()
            
            file_metadata = {
                'name': map_title,
                'mimeType': 'application/vnd.google-apps.map'
            }
            
            from googleapiclient.http import MediaInMemoryUpload
            media = MediaInMemoryUpload(
                kml_content.encode('utf-8'),
                mimetype='application/vnd.google-earth.kml+xml'
            )
            
            files = results.get('files', [])
            if files:
                # Aggiorna la mappa esistente
                file_id = files[0]['id']
                drive_service.files().update(
                    fileId=file_id,
                    media_body=media
                ).execute()
            else:
                # Crea nuova mappa
                file = drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()
                file_id = file.get('id')
            
            return f"https://www.google.com/maps/d/viewer?mid={file_id}"
            
        except Exception as e:
            _LOGGER.error("Errore upload Google My Maps: %s", e)
            return None