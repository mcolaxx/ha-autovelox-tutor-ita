"""Parser per i PDF della Polizia di Stato (Autovelox e Tutor)."""
from .velox_parser import VeloxPDFParser, VeloxEntry
from .tutor_parser import TutorPDFParser, TutorEntry

__all__ = [
    "VeloxPDFParser",
    "VeloxEntry",
    "TutorPDFParser",
    "TutorEntry",
]