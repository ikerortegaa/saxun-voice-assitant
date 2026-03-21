"""
Tests de STT — STTResult (propiedad is_reliable) y LanguageDetector.
Ejecutar: pytest src/tests/test_stt.py -v
"""
import pytest
from src.voice.stt import STTResult, LanguageDetector


# ── STTResult ─────────────────────────────────────────────────────────────────

class TestSTTResult:

    def test_reliable_with_high_confidence(self):
        result = STTResult(text="Hola, quiero saber el horario", confidence=0.95, is_final=True)
        assert result.is_reliable is True

    def test_reliable_at_exact_threshold(self):
        """Exactamente 0.70 debe ser fiable."""
        result = STTResult(text="Quiero informacion", confidence=0.70, is_final=True)
        assert result.is_reliable is True

    def test_not_reliable_below_threshold(self):
        result = STTResult(text="algo de texto", confidence=0.69, is_final=True)
        assert result.is_reliable is False

    def test_not_reliable_low_confidence(self):
        result = STTResult(text="texto ilegible", confidence=0.30, is_final=True)
        assert result.is_reliable is False

    def test_not_reliable_empty_text(self):
        result = STTResult(text="", confidence=0.95, is_final=True)
        assert result.is_reliable is False

    def test_not_reliable_whitespace_only(self):
        result = STTResult(text="   ", confidence=0.95, is_final=True)
        assert result.is_reliable is False

    def test_not_reliable_zero_confidence(self):
        result = STTResult(text="texto con confianza cero", confidence=0.0, is_final=True)
        assert result.is_reliable is False

    def test_reliable_with_words(self):
        words = [{"word": "hola", "confidence": 0.98}]
        result = STTResult(text="hola", confidence=0.90, is_final=True, words=words)
        assert result.is_reliable is True

    def test_default_language_is_es(self):
        result = STTResult(text="hola", confidence=0.9, is_final=True)
        assert result.language == "es"

    def test_is_final_attribute(self):
        final = STTResult(text="texto", confidence=0.9, is_final=True)
        interim = STTResult(text="texto", confidence=0.9, is_final=False)
        assert final.is_final is True
        assert interim.is_final is False


# ── LanguageDetector ──────────────────────────────────────────────────────────

class TestCatalanMarkers:
    """Tests para _has_catalan_markers (metodo estatico, no requiere langdetect)."""

    def test_detects_catalan_markers_bon_dia(self):
        assert LanguageDetector._has_catalan_markers("bon dia, com estas") is True

    def test_detects_catalan_markers_gracies(self):
        assert LanguageDetector._has_catalan_markers("gracies per la informacio") is True

    def test_detects_catalan_vull_tinc(self):
        assert LanguageDetector._has_catalan_markers("tinc un problema amb el meu dispositiu") is True

    def test_not_enough_markers_returns_false(self):
        # Solo una palabra catalan no es suficiente (necesita >= 2)
        assert LanguageDetector._has_catalan_markers("bon") is False

    def test_empty_text_returns_false(self):
        assert LanguageDetector._has_catalan_markers("") is False

    def test_spanish_text_returns_false(self):
        assert LanguageDetector._has_catalan_markers("buenos dias quiero informacion") is False

    def test_mixed_text_with_two_catalan_words(self):
        assert LanguageDetector._has_catalan_markers("hola bon dia") is True

    def test_case_insensitive_detection(self):
        assert LanguageDetector._has_catalan_markers("BON DIA") is True


class TestLanguageDetectorSupportedLangs:
    """Tests de constantes y configuracion del detector."""

    def test_supported_langs_contains_es(self):
        assert "es" in LanguageDetector.SUPPORTED_LANGS

    def test_supported_langs_contains_ca(self):
        assert "ca" in LanguageDetector.SUPPORTED_LANGS

    def test_supported_langs_contains_en(self):
        assert "en" in LanguageDetector.SUPPORTED_LANGS

    def test_supported_langs_count(self):
        assert len(LanguageDetector.SUPPORTED_LANGS) == 3
