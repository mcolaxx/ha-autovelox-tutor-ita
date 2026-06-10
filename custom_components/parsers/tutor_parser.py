"""Parser per il PDF dei tratti controllati con il Tutor."""
import re
import logging
from dataclasses import dataclass
from typing import Optional
import pdfplumber
import io

_LOGGER = logging.getLogger(__name__)

@dataclass
class TutorEntry:
    """Rappresenta un tratto autostradale controllato con Tutor."""
    highway: str          # "A1", "A14", etc.
    point_a: str          # "CASERTA NORD"
    point_b: str          # "SANTA MARIA CAPUAVETERE"
    direction: str        # "DIR NORD" o "DIR SUD"
    lat_a: Optional[float] = None
    lng_a: Optional[float] = None
    lat_b: Optional[float] = None
    lng_b: Optional[float] = None

    @property
    def display_name(self) -> str:
        return (
            f"Tutor {self.highway}: "
            f"{self.point_a} → {self.point_b} ({self.direction})"
        )

    @property
    def maps_label(self) -> str:
        return f"📡 Tutor {self.highway} {self.point_a}→{self.point_b}"


class TutorPDFParser:
    """Parser per il documento nazionale dei Tutor."""

    HIGHWAY_PATTERN = re.compile(r'^(A\s*\d+[A-Z]?)\s*$')
    ENTRY_PATTERN = re.compile(
        r'^(.+?)\s+(DIR\s+(?:NORD|SUD|EST|OVEST|ITALIA|FRANCIA))\s+'
        r'(.+?)\s+(DIR\s+(?:NORD|SUD|EST|OVEST|ITALIA|FRANCIA))\s*'
        r'(?:\((.+?)\))?$',
        re.IGNORECASE
    )

    def parse_bytes(self, pdf_bytes: bytes) -> list[TutorEntry]:
        """Parsa il PDF Tutor e ritorna lista di TutorEntry."""
        entries = []
        
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                current_highway = "A1"
                
                for page in pdf.pages:
                    text = page.extract_text()
                    if not text:
                        continue
                    
                    for line in text.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Controlla se è un'intestazione autostrada
                        hw_match = self.HIGHWAY_PATTERN.match(line)
                        if hw_match:
                            current_highway = hw_match.group(1).replace(' ', '')
                            continue
                        
                        # Parsa tratto
                        entry = self._parse_tutor_line(
                            line, current_highway
                        )
                        if entry:
                            entries.append(entry)
                            
        except Exception as e:
            _LOGGER.error("Errore parsing PDF Tutor: %s", e)
        
        return entries

    def _parse_tutor_line(
        self, line: str, highway: str
    ) -> Optional[TutorEntry]:
        """
        Parsa una riga del tipo:
        "CASERTA NORD DIR NORD    SANTA MARIA CAPUAVETERE DIR NORD"
        """
        # Pattern: NOME_A DIR_X    NOME_B DIR_Y
        pattern = re.compile(
            r'^(.+?)\s+(DIR\s+\w+)\s{2,}(.+?)\s+(DIR\s+\w+)\s*$',
            re.IGNORECASE
        )
        m = pattern.match(line)
        if m:
            point_a = m.group(1).strip()
            dir_a = m.group(2).strip()
            point_b = m.group(3).strip()
            # dir_b = m.group(4).strip()  # di solito uguale a dir_a
            
            # Salta righe di intestazione
            if any(skip in point_a.upper() for skip in [
                'TRATTI', 'AUTOSTRADALI', 'CONTROLLATI', 'TUTOR',
                'DIR NORD', 'DIR SUD'
            ]):
                return None
            
            return TutorEntry(
                highway=highway,
                point_a=point_a,
                point_b=point_b,
                direction=dir_a.upper()
            )
        return None