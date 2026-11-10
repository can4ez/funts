import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from question_importer import (
    deduplicate, infer_rows, is_public_https, norm_text, parse_html,
    read_source, stable_id, to_card,
)


class TestImporter(unittest.TestCase):
    def test_normalize_russian_and_exact(self):
        self.assertEqual(norm_text("  Привет, ЁЖИК! "), norm_text("привет ежик"))
        cards = [
            {"type": "truth", "text": "Какой у тебя самый тайный секрет?"},
            {"type": "truth", "text": "КАКОЙ У ТЕБЯ САМЫЙ ТАЙНЫЙ СЕКРЕТ!"},
            {"type": "dare", "text": "Какой у тебя самый тайный секрет?"},
        ]
        result = deduplicate(cards)
        self.assertEqual(result["stats"]["accepted"], 2)
        self.assertEqual(result["stats"]["removed"], 1)
        self.assertEqual(result["duplicates"][0]["kind"], "exact")

    def test_high_similarity_removed(self):
        cards = [
            {"type": "truth", "text": "Какие три качества ты ценишь в друзьях?"},
            {"type": "truth", "text": "Какие три качества ты очень ценишь в друзьях?"},
        ]
        result = deduplicate(cards, hard=0.86, review=0.80)
        self.assertEqual(result["stats"]["removed"], 1)
        self.assertEqual(result["duplicates"][0]["kind"], "near")

    def test_existing_bank(self):
        first = {"type": "truth", "text": "Что заставляет тебя краснеть?"}
        result = deduplicate([first], existing=[first])
        self.assertEqual(result["stats"]["already_existing"], 1)
        self.assertEqual(result["stats"]["accepted"], 0)

    def test_prefix_and_records(self):
        src = {"id": "fixture", "type": "dare", "level": 2, "text_field": "content", "license": "owned"}
        card = to_card({"content": "Truth: Какой твой самый смелый поступок?"}, src, "file:///a.json")
        self.assertEqual(card["type"], "dare")  # explicitly configured type wins
        src.pop("type")
        card = to_card({"content": "Truth: Какой твой самый смелый поступок?"}, src, "file:///a.json")
        self.assertEqual(card["type"], "truth")
        self.assertEqual(card["text"], "Какой твой самый смелый поступок?")
        self.assertEqual(infer_rows({"messages": [{"content": "x"}]}, {}), [{"content": "x"}])
        self.assertEqual(stable_id("truth", "ЁЖ"), stable_id("truth", "еж"))

    def test_html_css(self):
        html = '<div class="truth"><p>Что делает тебя счастливым?</p></div>'
        src = {"id": "demo", "kind": "html", "license": "owned", "selectors": [{"selector": ".truth p", "type": "truth", "level": 2}]}
        result = parse_html(html, src, "file:///local.html")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "truth")

    def test_local_sample_sources(self):
        manifest = json.loads((ROOT / "examples/sources.example.json").read_text())
        out = []
        for spec in manifest["sources"]:
            out += read_source(spec, ROOT / "examples", {}, {}, 1)
        result = deduplicate(out)
        self.assertEqual(len(out), 11)
        self.assertGreaterEqual(result["stats"]["removed"], 3)
        self.assertGreaterEqual(result["stats"]["accepted"], 5)

    def test_remote_checks(self):
        for url in ["http://example.org", "https://localhost/", "https://127.0.0.1/a", "https://192.168.0.1/"]:
            self.assertFalse(is_public_https(url))
        self.assertTrue(is_public_https("https://example.org/file.json"))


if __name__ == "__main__":
    unittest.main()
