import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


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

    def test_service_order_is_normalized(self):
        self.assertEqual(
            translator.normalize_service_order("google,deepseek,google,invalid"),
            ["google", "deepseek", "openai"],
        )

    def test_boolean_config_accepts_plasma_values(self):
        self.assertFalse(translator.parse_bool("false"))
        self.assertFalse(translator.parse_bool("0"))
        self.assertTrue(translator.parse_bool("true"))

    def test_clipboard_setting_is_loaded_from_plasma(self):
        with (
            mock.patch.object(
                translator,
                "load_plasma_applet_config",
                return_value={"clipboard_auto_translate": "false"},
            ),
            mock.patch("builtins.open", side_effect=FileNotFoundError),
        ):
            config = translator.load_config()

        self.assertFalse(config["clipboard_auto_translate"])

    def test_empty_selection_is_debounced(self):
        processed = []
        scheduled = {}
        cancelled = []

        def schedule(_delay, callback):
            scheduled[1] = callback
            return 1

        debouncer = translator.SelectionEventDebouncer(
            processed.append,
            schedule,
            cancelled.append,
        )
        debouncer.handle("")
        self.assertEqual(processed, [])

        debouncer.handle("hello")
        self.assertEqual(cancelled, [1])
        self.assertEqual(processed, ["hello"])

    def test_empty_selection_clears_after_delay(self):
        processed = []
        scheduled = {}

        def schedule(_delay, callback):
            scheduled[1] = callback
            return 1

        debouncer = translator.SelectionEventDebouncer(
            processed.append,
            schedule,
            lambda _source_id: None,
        )
        debouncer.handle("")
        scheduled[1]()

        self.assertEqual(processed, [""])

    def test_translation_uses_configured_service_order(self):
        calls = []
        config = {
            "service_order": ["google", "openai", "deepseek"],
            "deepseek_api_key": "",
            "deepseek_model": "test",
            "deepseek_base_url": "https://example.invalid",
            "openai_api_key": "",
            "openai_model": "test",
            "openai_base_url": "https://example.invalid",
        }

        def google(_text):
            calls.append("google")
            raise RuntimeError("unavailable")

        def openai(_text, _config):
            calls.append("openai")
            return "译文", "OpenAI test"

        with (
            mock.patch.object(translator, "load_config", return_value=config),
            mock.patch.object(translator, "google_translate", side_effect=google),
            mock.patch.object(translator, "openai_translate", side_effect=openai),
            mock.patch.object(translator, "deepseek_translate") as deepseek,
        ):
            translated, engine = translator.translate_sentence("Service order test")

        self.assertEqual(calls, ["google", "openai"])
        self.assertEqual((translated, engine), ("译文", "OpenAI test"))
        deepseek.assert_not_called()

    def test_word_online_translation_preserves_dictionary_state(self):
        translator.write_shared_state({
            "found": True,
            "word": "example",
            "translation": "n. 例子",
            "definition": "n. a representative form",
        })

        request_id, started = translator.begin_word_translation()
        finished = translator.finish_word_translation(
            request_id,
            "示例",
            "DeepSeek test",
        )

        self.assertTrue(started["found"])
        self.assertTrue(started["wordOnlineTranslating"])
        self.assertEqual(finished["translation"], "n. 例子")
        self.assertEqual(finished["wordOnlineTranslation"], "示例")
        self.assertFalse(finished["wordOnlineTranslating"])

    def test_new_word_rejects_old_online_translation(self):
        translator.write_shared_state({
            "found": True,
            "word": "first",
            "translation": "第一",
        })
        request_id, _ = translator.begin_word_translation()

        translator.write_shared_state({
            "found": True,
            "word": "second",
            "translation": "第二",
        })
        finished = translator.finish_word_translation(
            request_id,
            "第一个",
            "test",
        )

        self.assertIsNone(finished)
        self.assertEqual(translator.read_shared_state()["word"], "second")


if __name__ == "__main__":
    unittest.main()
