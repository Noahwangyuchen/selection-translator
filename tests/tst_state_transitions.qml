import QtQuick
import QtTest
import "../package/contents/ui/StateTransitions.js" as StateTransitions

TestCase {
    name: "SelectionTranslatorStateTransitions"

    function initialState() {
        return {
            currentWord: "",
            phonetic: "",
            translation: "",
            definition: "",
            exchange: "",
            wordOnlineTranslation: "",
            wordOnlineEngine: "",
            wordOnlineError: "",
            statusText: "请选择英文单词",
            sentenceText: "",
            sentenceTranslation: "",
            sentenceEngine: "",
            hasResult: false,
            sentenceCandidate: false,
            translatingSentence: false,
            wordOnlineTranslating: false
        }
    }

    function compactText(state) {
        if (state.translatingSentence) return "翻译中..."
        if (state.sentenceTranslation) return state.sentenceTranslation
        if (state.sentenceCandidate) return "待翻译"
        if (state.hasResult) return state.translation.split(/[;\n]/)[0]
        return state.currentWord
    }

    function apply(state, payload) {
        return StateTransitions.reduce(state, payload)
    }

    function test_sentenceToWord() {
        let state = apply(initialState(), {translated: true, text: "A complete sentence", translation: "一个完整的句子", engine: "test"})
        state = apply(state, {found: true, word: "word", translation: "单词"})

        compare(state.currentWord, "word")
        compare(compactText(state), "单词")
        compare(state.sentenceText, "")
        compare(state.sentenceTranslation, "")
        compare(state.sentenceEngine, "")
    }

    function test_sentenceToMissingWord() {
        let state = apply(initialState(), {translated: true, text: "Another sentence", translation: "另一个句子", engine: "test"})
        state = apply(state, {found: false, word: "unknown"})

        compare(state.currentWord, "unknown")
        compare(compactText(state), "unknown")
        compare(state.sentenceTranslation, "")
        verify(!state.hasResult)
    }

    function test_sentenceToEmptySelection() {
        let state = apply(initialState(), {translated: true, text: "Selected sentence", translation: "选中的句子", engine: "test"})
        state = apply(state, {found: false, message: "请选择英文单词"})

        compare(compactText(state), "")
        compare(state.sentenceText, "")
        compare(state.sentenceTranslation, "")
        verify(!state.sentenceCandidate)
    }

    function test_wordToSentenceCandidateAndTranslation() {
        let state = apply(initialState(), {found: true, word: "hello", translation: "你好"})
        state = apply(state, {sentenceCandidate: true, text: "Hello there", message: "是否翻译整句？"})

        compare(state.currentWord, "")
        compare(compactText(state), "翻译整句")
        verify(state.sentenceCandidate)

        state = apply(state, {translating: true, text: "Hello there", message: "翻译中..."})
        compare(compactText(state), "翻译中...")
        verify(state.translatingSentence)

        state = apply(state, {translated: true, text: "Hello there", translation: "你好", engine: "test"})
        compare(compactText(state), "你好")
        verify(!state.translatingSentence)
    }

    function test_newSentenceReplacesOldTranslation() {
        let state = apply(initialState(), {translated: true, text: "First sentence", translation: "第一句", engine: "test"})
        state = apply(state, {sentenceCandidate: true, text: "Second sentence", message: "是否翻译整句？"})

        compare(state.sentenceText, "Second sentence")
        compare(state.sentenceTranslation, "")
        compare(compactText(state), "翻译整句")
    }

    function test_staleResultDoesNotChangeCurrentState() {
        let state = apply(initialState(), {sentenceCandidate: true, text: "Current sentence", message: "是否翻译整句？"})
        state = apply(state, {stale: true, translated: true, text: "Old sentence", translation: "旧句子"})

        compare(state.sentenceText, "Current sentence")
        compare(state.sentenceTranslation, "")
        verify(state.sentenceCandidate)
    }

    function test_translationFailureClearsProgress() {
        let state = apply(initialState(), {translating: true, text: "Failed sentence"})
        state = apply(state, {translated: false, translating: false, text: "Failed sentence", message: "整句翻译失败"})

        compare(state.sentenceText, "Failed sentence")
        compare(state.sentenceTranslation, "")
        compare(state.statusText, "整句翻译失败")
        verify(!state.translatingSentence)
    }

    function test_dictionaryEscapedNewlinesAreCleaned() {
        const state = apply(initialState(), {
            found: true,
            word: "test",
            translation: "n. 测试\\nv. 检验\\r\\n[网络] 测验",
            definition: "first\\nsecond"
        })

        compare(state.translation, "n. 测试\nv. 检验\n[网络] 测验")
        compare(state.definition, "first\nsecond")
        verify(state.translation.indexOf("\\n") === -1)
    }

    function test_wordOnlineTranslationPreservesDictionaryResult() {
        let state = apply(initialState(), {
            found: true,
            word: "example",
            translation: "n. 例子",
            definition: "n. a representative form",
            wordOnlineTranslating: true
        })
        verify(state.hasResult)
        verify(state.wordOnlineTranslating)
        compare(state.translation, "n. 例子")

        state = apply(state, {
            found: true,
            word: "example",
            translation: "n. 例子",
            definition: "n. a representative form",
            wordOnlineTranslation: "示例",
            wordOnlineEngine: "DeepSeek test"
        })
        compare(state.translation, "n. 例子")
        compare(state.wordOnlineTranslation, "示例")
        compare(state.wordOnlineEngine, "DeepSeek test")
        verify(!state.wordOnlineTranslating)

        state = apply(state, {
            found: true,
            word: "different",
            translation: "adj. 不同的"
        })
        compare(state.wordOnlineTranslation, "")
        compare(state.wordOnlineEngine, "")
    }

    function test_missingWordOnlineTranslation() {
        let state = apply(initialState(), {
            found: false,
            word: "codexium",
            message: "本地词库没有这个词"
        })
        compare(state.currentWord, "codexium")
        verify(!state.hasResult)

        state = apply(state, {
            found: false,
            word: "codexium",
            message: "本地词库没有这个词",
            wordOnlineTranslating: true
        })
        verify(state.wordOnlineTranslating)

        state = apply(state, {
            found: false,
            word: "codexium",
            message: "本地词库没有这个词",
            wordOnlineTranslation: "代码元素",
            wordOnlineEngine: "test"
        })
        compare(state.wordOnlineTranslation, "代码元素")
        compare(state.wordOnlineEngine, "test")
        verify(!state.wordOnlineTranslating)
    }
}
