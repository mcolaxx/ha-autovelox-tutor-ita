"""
Parser per il PDF nazionale dei tratti autostradali controllati con Tutor.
Fonte: Polizia di Stato - Servizio Polizia Stradale
Formato: PDF con colonne: PUNTO_A DIR_X    PUNTO_B DIR_Y  [Autostrada]
"""
from __future__ import annotations
 
import io
import logging
import re
from dataclasses import dataclass
from typing import Optional
 
import pdfplumber
 
_LOGGER = logging.getLogger(__name__)
 
# Direzioni valide nel documento
VALID_DIRECTIONS = frozenset([
    "DIR NORD", "DIR SUD", "DIR EST", "DIR OVEST",
    "DIR ITALIA", "DIR FRANCIA",
])
 
# Pattern per riconoscere il badge autostrada (es: "A1", "A14", "A4/A23")
_HIGHWAY_BADGE = re.compile(r"^(A\s*\d+[A-Z]?(?:/A\d+[A-Z]?)?)\s*$")
 
# Pattern riga tratto: "CASERTA NORD DIR NORD    SANTA MARIA CAPUAVETERE DIR NORD"
# I due campi sono separati da 2+ spazi oppure da una tabulazione
_ENTRY_PATTERN = re.compile(
    r"^(.+?)\s+(DIR\s+\w+)\s{2,}(.+?)\s+(DIR\s+\w+)"
    r"(?:\s+(.+?))?$",
    re.IGNORECASE,
)
 
# Linee da ignorare
_SKIP_PATTERNS = frozenset([
    "tratti autostradali", "controllati con il tutor",
    "polizia stradale", "aggiornato", "dir nord", "dir sud",
    "dir est", "dir ovest", "dir italia", "dir francia",
])
 
 
@dataclass
class TutorEntry:
    """Un singolo tratto autostradale controllato con sistema Tutor."""
    highway: str          # "A1", "A14", "A4"...
    point_a: str          # Casello/punto iniziale
    point_b: str          # Casello/punto finale
    direction: str        # "DIR NORD", "DIR SUD", ...
    note: str = ""        # Note aggiuntive (es: "A1 Variante di Valico")
    lat_a: Optional[float] = None
    lng_a: Optional[float] = None
    lat_b: Optional[float] = None
    lng_b: Optional[float] = None
 
    @property
    def unique_key(self) -> str:
        return f"{self.highway}_{self.point_a}_{self.point_b}_{self.direction}"
 
    @property
    def display_name(self) -> str:
        note_str = f" ({self.note})" if self.note else ""
        return (
            f"Tutor {self.highway}: {self.point_a} → {self.point_b} "
            f"[{self.direction}]{note_str}"
        )
 
    @property
    def maps_label(self) -> str:
        return f"📡 Tutor {self.highway} {self.point_a}→{self.point_b}"
 
    @property
    def maps_description(self) -> str:
        lines = [
            f"Autostrada: {self.highway}",
            f"Tratto: {self.point_a} → {self.point_b}",
            f"Direzione: {self.direction}",
        ]
        if self.note:
            lines.append(f"Nota: {self.note}")
        return "\n".join(lines)
 
    def to_dict(self) -> dict:
        return {
            "highway": self.highway,
            "point_a": self.point_a,
            "point_b": self.point_b,
            "direction": self.direction,
            "note": self.note,
            "lat_a": self.lat_a,
            "lng_a": self.lng_a,
            "lat_b": self.lat_b,
            "lng_b": self.lng_b,
        }
 
    @classmethod
    def from_dict(cls, data: dict) -> "TutorEntry":
        return cls(
            highway=data["highway"],
            point_a=data["point_a"],
            point_b=data["point_b"],
            direction=data["direction"],
            note=data.get("note", ""),
            lat_a=data.get("lat_a"),
            lng_a=data.get("lng_a"),
            lat_b=data.get("lat_b"),
            lng_b=data.get("lng_b"),
        )
 
 
class TutorPDFParser:
    """
    Parsa il PDF nazionale dei Tutor autostradali.
 
    Struttura PDF attesa (per pagina):
      [A1]  (badge autostrada - identificato visivamente nel PDF)
      CASERTA NORD DIR NORD    SANTA MARIA CAPUAVETERE DIR NORD
      SANTA MARIA CAPUAVETERE DIR NORD    CAPUA DIR NORD
      ...
      [A14]
      PESCARA DIR NORD    ORTONA DIR NORD
      ...
 
    Il badge autostrada viene dedotto dal contesto visivo/testuale.
    """
 
    def parse_bytes(self, pdf_bytes: bytes) -> list[TutorEntry]:
        """Entry point: parsa i byte del PDF e ritorna i tratti Tutor."""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                entries = self._parse_all_pages(pdf)
        except Exception as exc:
            _LOGGER.error("Errore apertura PDF Tutor: %s", exc)
            return []
 
        # Deduplica
        seen: set[str] = set()
        unique: list[TutorEntry] = []
        for e in entries:
            key = e.unique_key
            if key not in seen:
                seen.add(key)
                unique.append(e)
 
        _LOGGER.debug("Tutor: %d tratti unici trovati", len(unique))
        return unique
 
    def _parse_all_pages(self, pdf: pdfplumber.PDF) -> list[TutorEntry]:
        entries: list[TutorEntry] = []
 
        for page_num, page in enumerate(pdf.pages, 1):
            # Estrai sia il testo normale che le parole con posizione
            words = page.extract_words()
            text_lines = (page.extract_text() or "").splitlines()
 
            # Rileva autostrade dalla pagina (badge grafici)
            highway_map = self._detect_highways_from_words(words)
 
            # Parsa le righe di testo
            page_entries = self._parse_text_lines(
                text_lines, highway_map, page_num
            )
            entries.extend(page_entries)
 
        return entries
 
    def _detect_highways_from_words(
        self, words: list[dict]
    ) -> dict[int, str]:
        """
        Rileva i badge autostrada (A1, A14, ecc.) con la loro posizione
        verticale approssimativa per associarli alle righe successive.
        Returns: {y_position_approx: highway_code}
        """
        highway_positions: dict[int, str] = {}
        for word in words:
            text = word.get("text", "").strip()
            m = _HIGHWAY_BADGE.match(text)
            if m:
                y = int(word.get("top", 0))
                highway = m.group(1).replace(" ", "")
                highway_positions[y] = highway
        return highway_positions
 
    def _parse_text_lines(
        self,
        lines: list[str],
        highway_map: dict[int, str],
        page_num: int,
    ) -> list[TutorEntry]:
        entries: list[TutorEntry] = []
        current_highway = self._infer_highway_from_page(page_num)
 
        for line in lines:
            line = line.strip()
            if not line:
                continue
 
            line_lower = line.lower()
 
            # Salta intestazioni
            if any(skip in line_lower for skip in _SKIP_PATTERNS):
                continue
 
            # Riconosci badge autostrada inline
            badge_m = _HIGHWAY_BADGE.match(line)
            if badge_m:
                current_highway = badge_m.group(1).replace(" ", "")
                continue
 
            # Prova a parsare come tratto tutor
            entry = self._parse_tutor_line(line, current_highway)
            if entry:
                entries.append(entry)
 
        return entries
 
    def _infer_highway_from_page(self, page_num: int) -> str:
        """
        Fallback: stima l'autostrada in base alla pagina.
        Le prime pagine del PDF Tutor sono A1, poi A4, A7, A14, ecc.
        Viene aggiornato dinamicamente durante il parsing.
        """
        page_to_highway = {1: "A1", 2: "A4", 3: "A14", 4: "A16"}
        return page_to_highway.get(page_num, "A1")
 
    def _parse_tutor_line(
        self, line: str, highway: str
    ) -> Optional[TutorEntry]:
        """
        Parsa una riga come:
        "CASERTA NORD DIR NORD    SANTA MARIA CAPUAVETERE DIR NORD"
        oppure con nota:
        "FIRENZUOLA DIR NORD (A1 VAR) BADIA DIR NORD (A1 VAR) A1 Variante di Valico"
        """
        # Pattern principale: NOME_A DIR_X   NOME_B DIR_Y [note]
        m = re.match(
            r"^(.+?)\s+(DIR\s+(?:NORD|SUD|EST|OVEST|ITALIA|FRANCIA))"
            r"\s{2,}(.+?)\s+(DIR\s+(?:NORD|SUD|EST|OVEST|ITALIA|FRANCIA))"
            r"(?:\s+(.+))?$",
            line,
            re.IGNORECASE,
        )
        if not m:
            return None
 
        point_a = self._clean_point(m.group(1))
        direction_a = m.group(2).upper().strip()
        point_b = self._clean_point(m.group(3))
        note = (m.group(5) or "").strip()
 
        # Sanity check: i punti non devono essere vuoti o essere direttive
        if not point_a or not point_b:
            return None
        if len(point_a) < 3 or len(point_b) < 3:
            return None
 
        return TutorEntry(
            highway=highway,
            point_a=point_a,
            point_b=point_b,
            direction=direction_a,
            note=note,
        )
 
    @staticmethod
    def _clean_point(text: str) -> str:
        """Rimuove parentesi e testo tra parentesi dal nome del punto."""
        # Rimuove "(A1 VAR)", "(A1 D19)", ecc.
        cleaned = re.sub(r"\s*\([^)]*\)", "", text).strip()
        return cleaned