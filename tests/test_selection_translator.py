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

        def schedule(delay, callback):
            scheduled[delay] = callback
            return delay

        debouncer = translator.SelectionEventDebouncer(
            processed.append,
            schedule,
            cancelled.append,
        )
        debouncer.handle("")
        self.assertEqual(processed, [])

        debouncer.handle("hello")
        self.assertEqual(cancelled, [translator.EMPTY_SELECTION_DELAY_MS])
        self.assertEqual(processed, [])
        scheduled[translator.STABLE_SELECTION_DELAY_MS]()
        self.assertEqual(processed, ["hello"])

    def test_changing_selection_only_processes_final_stable_text(self):
        processed = []
        scheduled = {}
        cancelled = []
        next_source_id = 0

        def schedule(_delay, callback):
            nonlocal next_source_id
            next_source_id += 1
            scheduled[next_source_id] = callback
            return next_source_id

        debouncer = translator.SelectionEventDebouncer(
            processed.append,
            schedule,
            cancelled.append,
        )
        debouncer.handle("rat")
        debouncer.handle("ratna")
        debouncer.handle("ratnatrayāya")

        self.assertEqual(processed, [])
        self.assertEqual(cancelled, [1, 2])
        scheduled[3]()
        self.assertEqual(processed, ["ratnatrayāya"])

    def test_cleared_selection_cancels_pending_nonempty_text(self):
        processed = []
        scheduled = {}
        cancelled = []
        next_source_id = 0

        def schedule(_delay, callback):
            nonlocal next_source_id
            next_source_id += 1
            scheduled[next_source_id] = callback
            return next_source_id

        debouncer = translator.SelectionEventDebouncer(
            processed.append,
            schedule,
            cancelled.append,
        )
        debouncer.handle("temporary")
        debouncer.handle("")

        self.assertEqual(cancelled, [1])
        scheduled[2]()
        self.assertEqual(processed, [""])

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

    def test_x11_primary_source_uses_xclip(self):
        with (
            mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}),
            mock.patch.object(translator, "run_text_command", return_value="hello") as run,
        ):
            text = translator.read_selection_source("primary")

        self.assertEqual(text, "hello")
        run.assert_called_once_with(["xclip", "-selection", "primary", "-o"])

    def test_x11_clipboard_source_uses_xclip(self):
        with (
            mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}),
            mock.patch.object(translator, "run_text_command", return_value="copied") as run,
        ):
            text = translator.read_selection_source("clipboard")

        self.assertEqual(text, "copied")
        run.assert_called_once_with(["xclip", "-selection", "clipboard", "-o"])

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

        def google(_text, _language=None):
            calls.append("google")
            raise RuntimeError("unavailable")

        def openai(_text, _config, _language=None):
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

    def test_iast_is_detected_as_sanskrit(self):
        self.assertEqual(translator.source_language("śāntiḥ"), "sanskrit")
        self.assertEqual(translator.source_language("s\u0301a\u0304ntih\u0323"), "sanskrit")
        self.assertTrue(translator.looks_like_sentence("śāntiḥ"))

    def test_selection_containing_chinese_waits_for_panel_intent(self):
        state = translator.selection_state("中文 ratnatrayāya", "/missing.sqlite3")

        self.assertTrue(state["sentenceCandidate"])
        self.assertTrue(state["intentRequired"])
        self.assertEqual(state["sourceLanguage"], "chinese")
        self.assertNotIn("autoTranslate", state)

    def test_chinese_prompt_requests_english_and_pinyin(self):
        prompt = translator.translation_system_prompt("三宝", "chinese")

        self.assertIn("English", prompt)
        self.assertIn("Pinyin", prompt)

    def test_unknown_latin_word_waits_for_panel_intent(self):
        with mock.patch.object(translator, "lookup", return_value=None):
            state = translator.selection_state("dharma", "/missing.sqlite3")

        self.assertTrue(state["sentenceCandidate"])
        self.assertTrue(state["intentRequired"])
        self.assertEqual(state["sourceLanguage"], "latin")
        self.assertNotIn("autoTranslate", state)

    def test_iast_sanskrit_waits_for_panel_intent(self):
        state = translator.selection_state("ratnatrayāya", "/missing.sqlite3")

        self.assertTrue(state["sentenceCandidate"])
        self.assertTrue(state["intentRequired"])
        self.assertEqual(state["sourceLanguage"], "sanskrit")
        self.assertNotIn("autoTranslate", state)

    def test_plain_latin_sentence_uses_auto_language_prompt(self):
        state = translator.selection_state("tat tvam asi", "/missing.sqlite3")
        prompt = translator.translation_system_prompt(state["text"], state["sourceLanguage"])

        self.assertEqual(state["sourceLanguage"], "latin")
        self.assertIn("English or Sanskrit", prompt)

    def test_sanskrit_fallback_translates_without_confirmation(self):
        args = mock.Mock()
        with mock.patch.object(
            translator,
            "translate_sentence",
            return_value=("存在、意识与喜乐", "test"),
        ) as translate:
            result = translator.translate_text_sync("saccidananda", args, "sanskrit")

        self.assertTrue(result["translated"])
        self.assertEqual(result["translation"], "存在、意识与喜乐")
        translate.assert_called_once_with("saccidananda", args, "sanskrit")

    def test_known_english_word_stays_dictionary_result(self):
        entry = {
            "word": "example",
            "phonetic": "",
            "translation": "例子",
            "definition": "",
            "exchange": "",
        }
        with mock.patch.object(translator, "lookup", return_value=entry):
            state = translator.selection_state("example", "/dictionary.sqlite3")

        self.assertTrue(state["found"])
        self.assertEqual(state["translation"], "例子")
        self.assertNotIn("sentenceCandidate", state)

    def test_sanskrit_and_english_use_distinct_cache_keys(self):
        self.assertNotEqual(
            translator.cache_key("rama", "english"),
            translator.cache_key("rama", "sanskrit"),
        )

    def test_sanskrit_prompt_targets_chinese(self):
        prompt = translator.translation_system_prompt("dharma", "sanskrit")
        self.assertIn("Sanskrit", prompt)
        self.assertIn("Simplified Chinese", prompt)
        self.assertIn("inflection", prompt)

    def test_sanskrit_translation_uses_configured_ai_only(self):
        config = {
            "service_order": ["google", "deepseek", "openai"],
            "deepseek_api_key": "configured",
            "deepseek_model": "test",
            "deepseek_base_url": "https://example.invalid",
            "openai_api_key": "",
            "openai_model": "test",
            "openai_base_url": "https://example.invalid",
        }
        with (
            mock.patch.object(translator, "load_config", return_value=config),
            mock.patch.object(
                translator,
                "deepseek_translate",
                return_value=("向三宝", "DeepSeek test"),
            ) as deepseek,
            mock.patch.object(translator, "google_translate") as google,
            mock.patch.object(translator, "openai_translate") as openai,
        ):
            result = translator.translate_sentence("ratnatrayāya", language="sanskrit")

        self.assertEqual(result, ("向三宝", "DeepSeek test"))
        deepseek.assert_called_once()
        google.assert_not_called()
        openai.assert_not_called()

    def test_sanskrit_without_ai_key_fails_without_google_timeout(self):
        config = {
            "service_order": ["deepseek", "openai", "google"],
            "deepseek_api_key": "",
            "deepseek_model": "test",
            "deepseek_base_url": "https://example.invalid",
            "openai_api_key": "",
            "openai_model": "test",
            "openai_base_url": "https://example.invalid",
        }
        with (
            mock.patch.object(translator, "load_config", return_value=config),
            mock.patch.object(translator, "google_translate") as google,
        ):
            with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
                translator.translate_sentence("śāntiḥ", language="sanskrit")

        google.assert_not_called()

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

    def test_missing_dictionary_word_can_use_online_translation(self):
        translator.write_shared_state({
            "found": False,
            "word": "codexium",
            "message": "本地词库没有这个词",
        })

        request_id, started = translator.begin_word_translation()
        finished = translator.finish_word_translation(
            request_id,
            "代码元素",
            "test",
        )

        self.assertTrue(request_id)
        self.assertFalse(started["found"])
        self.assertTrue(started["wordOnlineTranslating"])
        self.assertEqual(finished["word"], "codexium")
        self.assertEqual(finished["wordOnlineTranslation"], "代码元素")
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
