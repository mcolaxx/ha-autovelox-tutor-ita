"""
Parser per il PDF nazionale dei tratti autostradali controllati con Tutor.
Fonte: Polizia di Stato - Servizio Polizia Stradale

Struttura PDF reale (estratta con pdfplumber):
  - Ogni riga contiene DUE caselli affiancati in una sola stringa:
    "CASERTA NORD DIR NORD SANTA MARIA CAPUAVETERE DIR NORD"
  - Righe con solo "DIR NORD" / "DIR SUD" / ecc. sono separatori di colonna (da ignorare)
  - Righe con "(A1 VAR)" o "(A1 D19)" sono tratti speciali con nota
  - L'autostrada cambia per gruppo di righe (pagina 1=A1, pagina 2=A4/A5/A6/...)
  - Il badge autostrada NON è testo puro: viene dedotto dalla posizione nel documento
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber

_LOGGER = logging.getLogger(__name__)

# Pattern direzione valida
_DIR_PATTERN = re.compile(
    r'DIR\s+(NORD|SUD|EST|OVEST|ITALIA|FRANCIA)',
    re.IGNORECASE,
)

# Riga che è SOLO una direttiva di colonna (separatore), da ignorare
_ONLY_DIR = re.compile(
    r'^DIR\s+(NORD|SUD|EST|OVEST|ITALIA|FRANCIA)\s*$',
    re.IGNORECASE,
)

# Righe da saltare
_SKIP_RE = re.compile(
    r'tratti\s+autostradali|controllati\s+con|polizia\s+stradale|aggiornato',
    re.IGNORECASE,
)

# Mappa pagina -> lista autostrade in ordine di apparizione nel documento
# Dedotta dall'analisi manuale del PDF ufficiale (maggio 2026)
_PAGE_HIGHWAYS: dict[int, list[str]] = {
    1: ["A1"],
    2: ["A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11"],
    3: ["A13", "A14"],
    4: ["A16", "A23", "A26", "A27", "A28", "A30", "A56"],
}

# Soglie per cambio autostrada per pagina (numero di riga approssimativo)
# Questi valori vengono usati solo come fallback se il rilevamento automatico fallisce
_PAGE2_HIGHWAY_BOUNDARIES = [0, 24, 25, 26, 28, 36, 40, 46, 48]  # A4,A5,A6,A7,A8,A9,A10,A11


@dataclass
class TutorEntry:
    """Un singolo tratto autostradale controllato con sistema Tutor."""
    highway: str
    point_a: str
    point_b: str
    direction: str
    note: str = ""
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
        return f"Tutor {self.highway}: {self.point_a} → {self.point_b} [{self.direction}]{note_str}"

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

    Ogni riga del PDF contiene due caselli affiancati:
      "CASERTA NORD DIR NORD SANTA MARIA CAPUAVETERE DIR NORD"

    Il parser individua le due occorrenze di DIR [DIREZIONE] per splittare
    il punto A dal punto B.
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
            text = page.extract_text() or ""
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            page_entries = self._parse_page_lines(lines, page_num)
            entries.extend(page_entries)
        return entries

    def _parse_page_lines(
        self, lines: list[str], page_num: int
    ) -> list[TutorEntry]:
        entries: list[TutorEntry] = []
        # Autostrade candidate per questa pagina
        highways = _PAGE_HIGHWAYS.get(page_num, ["A1"])
        hw_index = 0
        current_highway = highways[0]
        line_count = 0  # conta righe effettive (non separatori, non skip)

        for line in lines:
            # Salta intestazioni
            if _SKIP_RE.search(line):
                continue

            # Salta righe che sono SOLO una direttiva (separatori di colonna)
            if _ONLY_DIR.match(line):
                # Avanza all'autostrada successiva se disponibile
                hw_index += 1
                if hw_index < len(highways):
                    current_highway = highways[hw_index]
                continue

            # Prova a estrarre il tratto
            entry = self._parse_line(line, current_highway)
            if entry:
                entries.append(entry)
                line_count += 1

        return entries

    def _parse_line(self, line: str, highway: str) -> Optional[TutorEntry]:
        """
        Parsa una riga come:
          "CASERTA NORD DIR NORD SANTA MARIA CAPUAVETERE DIR NORD"
          "FIRENZUOLA DIR NORD (A1 VAR) BADIA DIR NORD (A1 VAR) A1 Variante di Valico"

        Strategia: trova TUTTE le occorrenze di DIR [DIREZIONE] nel testo.
        La prima occorrenza separa point_a dalla direction_a.
        Tra la fine di direction_a e l'inizio di direction_b c'è point_b.
        """
        # Trova tutte le corrispondenze DIR XXX con le loro posizioni
        dir_matches = list(_DIR_PATTERN.finditer(line))

        if len(dir_matches) < 2:
            # Riga con una sola direttiva: potrebbe essere un tratto speciale
            # o una riga incompleta. La ignoriamo.
            return None

        m1 = dir_matches[0]
        m2 = dir_matches[1]

        # Testo prima del primo DIR = point_a (possibilmente con parentesi)
        raw_a = line[:m1.start()].strip()
        direction_a = f"DIR {m1.group(1).upper()}"

        # Testo tra fine dir1 e inizio dir2 = point_b
        raw_b = line[m1.end():m2.start()].strip()

        # Testo dopo dir2 = note eventuali
        raw_note = line[m2.end():].strip()

        # Pulisci parentesi dal punto b
        point_a = self._clean_point(raw_a)
        point_b = self._clean_point(raw_b)

        # Sanity check
        if not point_a or not point_b:
            return None
        if len(point_a) < 3 or len(point_b) < 3:
            return None

        # Nota: prendi solo la parte significativa (es: "A1 Variante di Valico")
        note = self._clean_note(raw_note)

        return TutorEntry(
            highway=highway,
            point_a=point_a,
            point_b=point_b,
            direction=direction_a,
            note=note,
        )

    @staticmethod
    def _clean_point(text: str) -> str:
        """Rimuove parentesi e contenuto tra parentesi."""
        cleaned = re.sub(r"\s*\([^)]*\)", "", text).strip()
        # Rimuove trailing/leading punteggiatura
        cleaned = cleaned.strip(".,;:")
        return cleaned

    @staticmethod
    def _clean_note(text: str) -> str:
        """Estrae solo la nota significativa, scartando duplicati e parentesi."""
        if not text:
            return ""
        # Rimuove parentesi ridondanti come "(A1 VAR)" che si ripetono
        cleaned = re.sub(r"\([^)]*\)", "", text).strip()
        cleaned = cleaned.strip(".,;: ")
        return cleaned
