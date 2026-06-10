"""
Parser per i PDF dei calendari settimanali degli autovelox.
Fonte: Polizia di Stato - Servizio Polizia Stradale
Formato: PDF con tabella Giorno / Tratto stradale / Provincia
"""
from __future__ import annotations
 
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
 
import pdfplumber
 
_LOGGER = logging.getLogger(__name__)
 
# Mese italiano → numero
MONTHS_IT: dict[str, int] = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
 
# Prefissi che indicano il tipo di strada nel PDF
ROAD_TYPE_PREFIXES: list[tuple[str, str]] = [
    ("raccordo autostradale", "Raccordo Autostradale"),
    ("autostrada", "Autostrada"),
    ("strada statale", "Strada Statale"),
    ("strada provinciale", "Strada Provinciale"),
    ("strada regionale", "Strada Regionale"),
    ("strada comunale", "Strada Comunale"),
]
 
# Parole da ignorare nel parsing (intestazioni, footer, ecc.)
SKIP_KEYWORDS = frozenset([
    "fonte:", "polizia di stato", "servizio polizia stradale",
    "calendario", "validità", "valida", "giorno", "tratto stradale",
    "provincia", "abruzzo", "basilicata", "calabria", "campania",
    "emilia", "friuli", "lazio", "liguria", "lombardia", "marche",
    "molise", "piemonte", "puglia", "sardegna", "sicilia", "toscana",
    "trentino", "umbria", "valle", "veneto", "regione",
])
 
 
@dataclass
class VeloxEntry:
    """Un singolo punto/tratto di controllo autovelox."""
    road_type: str       # "Autostrada", "Strada Statale", ...
    road_name: str       # "A/14 Bologna-Taranto", "SS/16 Adriatica"
    province: str        # "AN", "PU", "AP", ...
    region: str
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    day: Optional[date] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
 
    @property
    def unique_key(self) -> str:
        """Chiave univoca per deduplicazione e cache geocoding."""
        return f"{self.road_name.strip()}_{self.province}"
 
    @property
    def display_name(self) -> str:
        return f"Velox {self.road_type} {self.road_name} ({self.province})"
 
    @property
    def maps_label(self) -> str:
        """Etichetta per Google My Maps."""
        return f"🚔 Velox {self.road_name} ({self.province})"
 
    @property
    def maps_description(self) -> str:
        return (
            f"Tipo: {self.road_type}\n"
            f"Regione: {self.region.replace('_', ' ').title()}\n"
            f"Provincia: {self.province}\n"
            f"Validità: {self.valid_from} → {self.valid_to}"
        )
 
    def to_dict(self) -> dict:
        return {
            "road_type": self.road_type,
            "road_name": self.road_name,
            "province": self.province,
            "region": self.region,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "day": self.day.isoformat() if self.day else None,
            "lat": self.lat,
            "lng": self.lng,
        }
 
    @classmethod
    def from_dict(cls, data: dict) -> "VeloxEntry":
        return cls(
            road_type=data["road_type"],
            road_name=data["road_name"],
            province=data["province"],
            region=data["region"],
            valid_from=date.fromisoformat(data["valid_from"]) if data.get("valid_from") else None,
            valid_to=date.fromisoformat(data["valid_to"]) if data.get("valid_to") else None,
            day=date.fromisoformat(data["day"]) if data.get("day") else None,
            lat=data.get("lat"),
            lng=data.get("lng"),
        )
 
 
class VeloxPDFParser:
    """
    Parsa i PDF settimanali degli autovelox regionali.
 
    Struttura PDF attesa:
      Validità da lunedì 8 giugno 2026 a domenica 14 giugno 2026
      Giorno | Tratto stradale | Provincia
 
      08/06/2026
        Autostrada          A/14 Bologna-Taranto    PU
        Raccordo Autostr.   RA/11 Ascoli-...        AP
        Strada Statale      SS/16 Adriatica         AN
        ...
      09/06/2026
        ...
    """
 
    # Pattern data giornaliera: "08/06/2026"
    _DATE_PATTERN = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\s*$")
 
    # Pattern 2 lettere maiuscole a fine riga = codice provincia
    _PROVINCE_PATTERN = re.compile(r"^(.+?)\s+([A-Z]{2})\s*$")
 
    def __init__(self, region: str) -> None:
        self.region = region
 
    def parse_bytes(self, pdf_bytes: bytes) -> list[VeloxEntry]:
        """Entry point: accetta i byte del PDF e ritorna la lista dei controlli."""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                lines: list[str] = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        lines.extend(text.splitlines())
        except Exception as exc:
            _LOGGER.error("Errore apertura PDF velox %s: %s", self.region, exc)
            return []
 
        valid_from, valid_to = self._extract_validity(lines)
        entries = self._parse_lines(lines, valid_from, valid_to)
 
        # Deduplica: stesso tratto/provincia nello stesso periodo
        seen: set[str] = set()
        unique: list[VeloxEntry] = []
        for e in entries:
            key = e.unique_key
            if key not in seen:
                seen.add(key)
                unique.append(e)
 
        _LOGGER.debug(
            "Velox %s: %d voci uniche trovate (su %d totali)",
            self.region, len(unique), len(entries),
        )
        return unique
 
    # ------------------------------------------------------------------ #
    #  Metodi privati                                                      #
    # ------------------------------------------------------------------ #
 
    def _extract_validity(
        self, lines: list[str]
    ) -> tuple[Optional[date], Optional[date]]:
        """Estrae le date di validità del calendario dalla prima pagina."""
        full_text = " ".join(lines[:30])  # Cerca solo nelle prime righe
        pattern = re.compile(
            r"validit[àa]\s+da\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})"
            r"\s+a\s+\w+\s+(\d+)\s+(\w+)\s+(\d{4})",
            re.IGNORECASE,
        )
        m = pattern.search(full_text)
        if m:
            try:
                d_from = date(
                    int(m.group(3)),
                    MONTHS_IT.get(m.group(2).lower(), 1),
                    int(m.group(1)),
                )
                d_to = date(
                    int(m.group(6)),
                    MONTHS_IT.get(m.group(5).lower(), 1),
                    int(m.group(4)),
                )
                return d_from, d_to
            except ValueError as exc:
                _LOGGER.warning("Parsing date validità fallito: %s", exc)
        return None, None
 
    def _parse_lines(
        self,
        lines: list[str],
        valid_from: Optional[date],
        valid_to: Optional[date],
    ) -> list[VeloxEntry]:
        entries: list[VeloxEntry] = []
        current_road_type: Optional[str] = None
        current_day: Optional[date] = None
 
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
 
            # Salta intestazioni e footer
            line_lower = line.lower()
            if any(kw in line_lower for kw in SKIP_KEYWORDS):
                continue
 
            # --- Data giornaliera ---
            date_m = self._DATE_PATTERN.match(line)
            if date_m:
                try:
                    current_day = date(
                        int(date_m.group(3)),
                        int(date_m.group(2)),
                        int(date_m.group(1)),
                    )
                except ValueError:
                    pass
                continue
 
            # --- Tipo di strada ---
            matched_type: Optional[str] = None
            remainder = line
            for prefix, canonical in ROAD_TYPE_PREFIXES:
                if line_lower.startswith(prefix):
                    matched_type = canonical
                    current_road_type = canonical
                    remainder = line[len(prefix):].strip()
                    break
 
            # Se la riga era SOLO il tipo di strada, vai avanti
            if matched_type and not remainder:
                continue
 
            # Lavora sul testo rimanente (o su tutta la riga se no match tipo)
            if not current_road_type:
                continue
 
            entry = self._extract_entry(
                remainder if matched_type else line,
                current_road_type,
                current_day,
                valid_from,
                valid_to,
            )
            if entry:
                entries.append(entry)
 
        return entries
 
    def _extract_entry(
        self,
        text: str,
        road_type: str,
        day: Optional[date],
        valid_from: Optional[date],
        valid_to: Optional[date],
    ) -> Optional[VeloxEntry]:
        """
        Estrae nome strada + provincia da una riga.
        Formato atteso: "A /14 Bologna-Taranto PU"
                    o:  "SS /16 Adriatica AN"
        """
        m = self._PROVINCE_PATTERN.match(text.strip())
        if not m:
            return None
 
        road_name = m.group(1).strip()
        province = m.group(2).strip()
 
        # Filtra codici che non sono province reali
        # (es. "DI", "SS" come abbreviazione strada, ecc.)
        from .const import PROVINCE_CODES
        if province not in PROVINCE_CODES:
            return None
 
        # Filtra nomi strade troppo corti o che sembrano direttive
        if len(road_name) < 3:
            return None
 
        return VeloxEntry(
            road_type=road_type,
            road_name=road_name,
            province=province,
            region=self.region,
            valid_from=valid_from,
            valid_to=valid_to,
            day=day,
        )