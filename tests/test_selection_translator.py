import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).parents[1] / "package/contents/tools/selection_translator.py"
SPEC = importlib.util.spec_from_file_location("selection_translator", SCRIPT_PATH)
translator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(translator)


class SharedSentenceStateTests(unittest.TestCase):
    def setUp(self):
        self.cache_home = tempfile.TemporaryDirectory()
        self.previous_cache_home = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = self.cache_home.name

    def tearDown(self):
        if self.previous_cache_home is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self.previous_cache_home
        self.cache_home.cleanup()

    def test_polling_preserves_active_translation(self):
        sentence = "This sentence is being translated."
        request_id, started = translator.begin_translation(sentence)
        polled = translator.sentence_selection_state(sentence)

        self.assertTrue(request_id)
        self.assertTrue(started["translating"])
        self.assertTrue(polled["translating"])
        self.assertEqual(polled["requestId"], request_id)

    def test_duplicate_confirmation_reuses_active_request(self):
        sentence = "Only one request should be sent."
        request_id, _ = translator.begin_translation(sentence)
        duplicate_id, duplicate_state = translator.begin_translation(sentence)

        self.assertTrue(request_id)
        self.assertEqual(duplicate_id, "")
        self.assertEqual(duplicate_state["requestId"], request_id)

    def test_new_sentence_rejects_old_result(self):
        first = "This is the first sentence."
        second = "This is the second sentence."
        first_request, _ = translator.begin_translation(first)
        second_state = translator.sentence_selection_state(second)

        accepted = translator.finish_translation(first_request, {
            "translated": True,
            "text": first,
            "translation": "第一句",
            "engine": "test",
        })

        self.assertTrue(second_state["sentenceCandidate"])
        self.assertFalse(accepted)
        self.assertEqual(translator.read_shared_state()["text"], second)

    def test_two_sentences_can_complete_consecutively(self):
        for source, translated in (
            ("Translate the first sentence.", "翻译第一句。"),
            ("Translate the second sentence.", "翻译第二句。"),
        ):
            translator.sentence_selection_state(source)
            request_id, _ = translator.begin_translation(source)
            translator.write_translation_cache(source, translated, "test")
            accepted = translator.finish_translation(request_id, {
                "translated": True,
                "translating": False,
                "text": source,
                "translation": translated,
                "engine": "test",
            })
            polled = translator.sentence_selection_state(source)

            self.assertTrue(accepted)
            self.assertTrue(polled["translated"])
            self.assertEqual(polled["translation"], translated)


if __name__ == "__main__":
    unittest.main()
