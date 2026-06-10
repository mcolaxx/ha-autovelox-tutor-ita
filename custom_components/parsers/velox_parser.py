"""Parser per i PDF dei velox regionali della Polizia di Stato."""
import re
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
import pdfplumber
import io

_LOGGER = logging.getLogger(__name__)

@dataclass
class VeloxEntry:
    """Rappresenta un singolo punto di controllo velocità."""
    road_type: str        # "Autostrada", "Strada Statale", "Strada Provinciale"
    road_name: str        # "A/14 Bologna-Taranto", "SS/16 Adriatica"
    province: str         # "AN", "PU", "AP", "MC", "FM"
    region: str
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    day: Optional[date] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

    @property
    def display_name(self) -> str:
        return f"Velox {self.road_type} {self.road_name} ({self.province})"

    @property
    def maps_label(self) -> str:
        return f"🚔 Velox {self.road_name}"


class VeloxPDFParser:
    """Parser per i calendari settimanali dei velox."""

    ROAD_TYPE_MAP = {
        "autostrada": "Autostrada",
        "raccordo autostradale": "Raccordo Autostradale",
        "strada statale": "Strada Statale",
        "strada provinciale": "Strada Provinciale",
        "strada regionale": "Strada Regionale",
        "strada comunale": "Strada Comunale",
    }

    DATE_PATTERN = re.compile(
        r'(\d{2}/\d{2}/\d{4})'
    )
    VALIDITY_PATTERN = re.compile(
        r'validit[àa]\s+da\s+\w+\s+(\d+)\s+\w+\s+(\d{4})\s+a\s+\w+\s+(\d+)\s+\w+\s+(\d{4})',
        re.IGNORECASE
    )
    PROVINCE_CODES = {
        "AN", "AP", "FM", "MC", "PU",  # Marche
        "RM", "VT", "LT", "FR", "RI",  # Lazio
        "MI", "BG", "BS", "CO", "CR",  # Lombardia
        # ... tutte le province italiane
    }

    def __init__(self, region: str):
        self.region = region

    def parse_bytes(self, pdf_bytes: bytes) -> list[VeloxEntry]:
        """Parsa il PDF da bytes e ritorna lista di VeloxEntry."""
        entries = []
        
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                full_text = ""
                all_lines = []
                
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
                        all_lines.extend(text.split('\n'))
                
                # Estrai date di validità
                valid_from, valid_to = self._extract_validity(full_text)
                
                # Parsa le righe per estrarre i controlli
                entries = self._parse_lines(
                    all_lines, valid_from, valid_to
                )
                
        except Exception as e:
            _LOGGER.error(
                "Errore parsing PDF velox %s: %s", self.region, e
            )
        
        return entries

    def _extract_validity(
        self, text: str
    ) -> tuple[Optional[date], Optional[date]]:
        """Estrae le date di validità del calendario."""
        # Pattern: "Validità da lunedì 8 giugno 2026 a domenica 14 giugno 2026"
        MONTHS_IT = {
            "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
            "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
            "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12
        }
        pattern = re.compile(
            r'validit[àa]\s+da\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})'
            r'\s+a\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})',
            re.IGNORECASE
        )
        m = pattern.search(text)
        if m:
            try:
                d1 = date(
                    int(m.group(3)),
                    MONTHS_IT.get(m.group(2).lower(), 1),
                    int(m.group(1))
                )
                d2 = date(
                    int(m.group(6)),
                    MONTHS_IT.get(m.group(5).lower(), 1),
                    int(m.group(4))
                )
                return d1, d2
            except ValueError:
                pass
        return None, None

    def _parse_lines(
        self,
        lines: list[str],
        valid_from: Optional[date],
        valid_to: Optional[date]
    ) -> list[VeloxEntry]:
        """Parsa le righe del testo estratto dal PDF."""
        entries = []
        current_road_type = None
        current_day = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Rileva data giornaliera (es: "08/06/2026")
            date_match = self.DATE_PATTERN.match(line)
            if date_match:
                try:
                    parts = date_match.group(1).split('/')
                    current_day = date(
                        int(parts[2]), int(parts[1]), int(parts[0])
                    )
                except ValueError:
                    pass
                continue

            # Salta righe di intestazione
            if any(skip in line.lower() for skip in [
                'fonte:', 'polizia di stato', 'servizio polizia',
                'calendario', 'validità', 'giorno', 'tratto stradale',
                'provincia', 'marche', 'abruzzo'  # nomi regione
            ]):
                continue

            # Rileva tipo di strada
            line_lower = line.lower()
            matched_type = None
            for key, value in self.ROAD_TYPE_MAP.items():
                if line_lower.startswith(key):
                    matched_type = value
                    current_road_type = value
                    # La riga potrebbe contenere anche il nome strada
                    remainder = line[len(key):].strip()
                    if remainder:
                        line = remainder
                    else:
                        continue
                    break

            # Prova a estrarre nome strada + provincia
            # Formato tipico: "SS /16 Adriatica AN" o "A /14 Bologna-Taranto PU"
            entry = self._extract_road_entry(
                line, current_road_type, current_day, valid_from, valid_to
            )
            if entry:
                entries.append(entry)

        return entries

    def _extract_road_entry(
        self,
        line: str,
        road_type: Optional[str],
        day: Optional[date],
        valid_from: Optional[date],
        valid_to: Optional[date]
    ) -> Optional[VeloxEntry]:
        """Estrae un VeloxEntry da una riga di testo."""
        if not road_type:
            return None

        # Pattern: nome strada seguito da codice provincia (2 lettere maiuscole)
        # Es: "A /14 Bologna-Taranto PU" → road="A /14 Bologna-Taranto", prov="PU"
        # Es: "SS /16 Adriatica AN" → road="SS /16 Adriatica", prov="AN"
        pattern = re.compile(
            r'^(.+?)\s+([A-Z]{2})\s*$'
        )
        m = pattern.match(line.strip())
        if m:
            road_name = m.group(1).strip()
            province = m.group(2).strip()
            
            # Filtra falsi positivi (es. "DIR NORD" non è una provincia)
            known_non_provinces = {
                "DI", "SS", "SP", "SR", "RA", "GR", "TO", "VE",
                "NO", "AL", "AT"  # Alcuni coincidono con province reali
            }
            
            if len(province) == 2 and province.isalpha():
                return VeloxEntry(
                    road_type=road_type,
                    road_name=road_name,
                    province=province,
                    region=self.region,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    day=day
                )
        return None