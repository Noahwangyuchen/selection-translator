.pragma library

function copyState(state) {
    return {
        currentWord: state.currentWord || "",
        phonetic: state.phonetic || "",
        translation: state.translation || "",
        definition: state.definition || "",
        exchange: state.exchange || "",
        wordOnlineTranslation: state.wordOnlineTranslation || "",
        wordOnlineEngine: state.wordOnlineEngine || "",
        wordOnlineError: state.wordOnlineError || "",
        statusText: state.statusText || "",
        sentenceText: state.sentenceText || "",
        sentenceTranslation: state.sentenceTranslation || "",
        sentenceEngine: state.sentenceEngine || "",
        hasResult: Boolean(state.hasResult),
        sentenceCandidate: Boolean(state.sentenceCandidate),
        translatingSentence: Boolean(state.translatingSentence),
        wordOnlineTranslating: Boolean(state.wordOnlineTranslating)
    }
}

function cleanDisplayText(value) {
    return String(value || "")
        .replace(/\\r\\n/g, "\n")
        .replace(/\\n/g, "\n")
        .replace(/\\r/g, "\n")
        .replace(/\r\n?/g, "\n")
}

function clearWord(state) {
    state.currentWord = ""
    state.phonetic = ""
    state.translation = ""
    state.definition = ""
    state.exchange = ""
    state.wordOnlineTranslation = ""
    state.wordOnlineEngine = ""
    state.wordOnlineError = ""
    state.wordOnlineTranslating = false
    state.hasResult = false
}

function clearSentence(state) {
    state.sentenceText = ""
    state.sentenceTranslation = ""
    state.sentenceEngine = ""
    state.sentenceCandidate = false
    state.translatingSentence = false
}

function reduce(current, payload) {
    const next = copyState(current)
    if (payload.stale) {
        return next
    }

    if (payload.translated) {
        clearWord(next)
        next.sentenceText = cleanDisplayText(payload.text || next.sentenceText)
        next.sentenceTranslation = cleanDisplayText(payload.translation)
        next.sentenceEngine = payload.engine || ""
        next.statusText = ""
        next.sentenceCandidate = false
        next.translatingSentence = false
        return next
    }

    if (payload.translating) {
        clearWord(next)
        next.sentenceText = cleanDisplayText(payload.text || next.sentenceText)
        next.sentenceTranslation = ""
        next.sentenceEngine = ""
        next.statusText = payload.message || "翻译中..."
        next.sentenceCandidate = false
        next.translatingSentence = true
        return next
    }

    if (payload.found) {
        clearSentence(next)
        next.currentWord = cleanDisplayText(payload.word)
        next.phonetic = cleanDisplayText(payload.phonetic)
        next.translation = cleanDisplayText(payload.translation)
        next.definition = cleanDisplayText(payload.definition)
        next.exchange = cleanDisplayText(payload.exchange)
        next.wordOnlineTranslation = cleanDisplayText(payload.wordOnlineTranslation)
        next.wordOnlineEngine = cleanDisplayText(payload.wordOnlineEngine)
        next.wordOnlineError = cleanDisplayText(payload.wordOnlineError)
        next.wordOnlineTranslating = Boolean(payload.wordOnlineTranslating)
        next.statusText = ""
        next.hasResult = true
        return next
    }

    if (payload.sentenceCandidate) {
        if (next.sentenceTranslation && payload.text === next.sentenceText) {
            next.sentenceCandidate = false
            next.statusText = ""
            return next
        }

        clearWord(next)
        next.sentenceText = cleanDisplayText(payload.text)
        next.sentenceTranslation = ""
        next.sentenceEngine = ""
        next.statusText = payload.message || "是否翻译整句？"
        next.sentenceCandidate = true
        next.translatingSentence = false
        return next
    }

    if (payload.translated === false && payload.text) {
        clearWord(next)
        next.sentenceText = cleanDisplayText(payload.text)
        next.sentenceTranslation = ""
        next.sentenceEngine = ""
        next.statusText = payload.message || "整句翻译失败"
        next.sentenceCandidate = false
        next.translatingSentence = false
        return next
    }

    clearWord(next)
    clearSentence(next)
    if (payload.word) {
        next.currentWord = cleanDisplayText(payload.word)
        next.statusText = "本地词库没有这个词"
    } else {
        next.statusText = payload.message || "请选择英文单词"
    }
    return next
}
