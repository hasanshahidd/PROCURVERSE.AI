"""
Translation Service - Handles multi-language translation workflow
User input (Arabic/Urdu) → English → Process → Translate back to user language
"""

import os
import logging
from openai import OpenAI
import httpx

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI client with timeout configuration
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    timeout=httpx.Timeout(
        connect=5.0,   # 5 seconds to establish connection
        read=20.0,     # 20 seconds to read response
        write=5.0,     # 5 seconds to send request
        pool=5.0       # 5 seconds for connection pooling
    ),
    max_retries=2      # Retry twice on timeout
)

LANGUAGE_NAMES = {
    "en": "English",
    "ur": "Urdu",
    "ar": "Arabic"
}

def translate_to_english(text: str, source_language: str) -> str:
    """
    Translate user input from Arabic/Urdu to English
    If already English, return as-is
    """
    if source_language == "en" or not text.strip():
        return text
    
    logger.info(f"=" * 80)
    logger.info(f"[INPUT TRANSLATION] {LANGUAGE_NAMES[source_language]} -> English")
    logger.info(f"Original text: {text[:200]}")
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": f"You are a professional translator. Translate the following {LANGUAGE_NAMES[source_language]} text to English. Preserve the meaning and intent. Keep any English words (like PR numbers, technical terms) unchanged. Return ONLY the English translation, no explanations."
                },
                {
                    "role": "user",
                    "content": text
                }
            ]
        )
        
        translated = response.choices[0].message.content.strip()
        logger.info(f"Translated text: {translated[:200]}")
        logger.info(f"=" * 80)
        return translated
        
    except Exception as e:
        logger.error(f"Translation to English failed: {e}")
        return text  # Return original if translation fails


def translate_from_english(text: str, target_language: str) -> str:
    """
    Translate AI response from English to Arabic/Urdu
    If target is English, return as-is
    """
    if target_language == "en" or not text.strip():
        return text
    
    logger.info(f"\n" + "=" * 80)
    logger.info(f"[OUTPUT TRANSLATION] English -> {LANGUAGE_NAMES[target_language]}")
    logger.info(f"Input text length: {len(text)} characters")
    logger.info(f"First 500 chars of English text:")
    logger.info(text[:500])
    logger.info(f"\nChecking for table markers:")
    logger.info(f"  - Contains '|': {('|' in text)}")
    logger.info(f"  - Contains '---': {('---' in text) or ('--' in text)}")
    logger.info(f"  - Contains numbers: {any(c.isdigit() for c in text)}")
    logger.info(f"  - Contains '**': {('**' in text)}")
    
    try:
        system_prompt = f"""You are a professional translator. Translate ONLY the natural language text from English to {LANGUAGE_NAMES[target_language]}.

CRITICAL RULES - DO NOT BREAK:
1. **PRESERVE ALL MARKDOWN TABLES EXACTLY** - Keep pipe characters |, dashes, and table structure identical
2. **NEVER translate numbers, amounts, or counts** - Keep ALL numbers in English (14, 3, 8, etc.)
3. **NEVER translate PR numbers** - Keep format PR-YYYY-NNNN unchanged
4. **NEVER translate dates** - Keep dates in original format
5. **Keep ALL markdown syntax** (**, ##, ###, -, |, `, etc.)
6. **Keep currency symbols and amounts** ($50,000 stays $50,000)
7. **Keep percentages** (20% stays 20%)
8. **Keep column names in tables if technical** (Department, Count, etc. can be translated, but structure must stay)
9. **Translate ONLY words and sentences** - Not structure, not numbers, not formatting

Example:
English: "Found **14 items** with budget $50,000"
{LANGUAGE_NAMES[target_language]}: "تم العثور على **14 عنصر** بميزانية $50,000"

English table:
| Department | Count |
|------------|-------|
| HR         | 14    |

{LANGUAGE_NAMES[target_language]} table (SAME STRUCTURE):
| القسم | العدد |
|-------|------|
| HR    | 14   |

Return ONLY the {LANGUAGE_NAMES[target_language]} translation with EXACT same structure."""

        logger.info(f"\nSending to OpenAI with system prompt ({len(system_prompt)} chars)...")
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": text
                }
            ]
        )
        
        translated = response.choices[0].message.content.strip()
        
        logger.info(f"\n[TRANSLATION RESULT]")
        logger.info(f"Output text length: {len(translated)} characters")
        logger.info(f"First 500 chars of {LANGUAGE_NAMES[target_language]} text:")
        logger.info(translated[:500])
        logger.info(f"\nChecking translated output:")
        logger.info(f"  - Contains '|': {('|' in translated)}")
        logger.info(f"  - Contains '---': {('---' in translated) or ('--' in translated)}")
        logger.info(f"  - Contains numbers: {any(c.isdigit() for c in translated)}")
        logger.info(f"  - Contains '**': {('**' in translated)}")
        logger.info(f"=" * 80 + "\n")
        
        return translated
        
    except Exception as e:
        logger.error(f"Translation from English failed: {e}")
        return text  # Return original if translation fails


def is_translation_needed(language: str) -> bool:
    """Check if translation is needed for this language"""
    return language in ["ur", "ar"]
