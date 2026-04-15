"""Count the words in a given text."""

SKILL_META = {
    "name": "count_words",
    "description": "Count the number of words, characters, and sentences in a text.",
    "author": "system",
    "version": "1.0",
    "parameters": {
        "text": {"type": "string", "description": "The text to analyze"},
    },
    "returns": "dict with word_count, char_count, and sentence_count",
    "permissions": {
        "network": False,
        "subprocess": False,
        "file_write": False,
    },
}


async def run(text: str) -> dict:
    words = text.split()
    sentences = [s for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    return {
        "word_count": len(words),
        "char_count": len(text),
        "sentence_count": len(sentences),
    }