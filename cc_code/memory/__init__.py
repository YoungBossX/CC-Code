"""Layered memory system for cross-session knowledge retention.

Public surface (everything callers were importing pre-split):

- Types: ``MemoryScope``, ``MemoryEntry``, ``MemoryFile``
- Manager: ``MemoryManager``, ``MemoryPaths``
- Prompt integration: ``inject_memory_into_prompt``, ``format_memory_list``
- Search utilities exposed for tests: ``_tokenize``, ``get_tfidf_keywords``,
  ``_CODE_TERM_EXPANSIONS``, ``_auto_classify_content``

Internal modules are prefixed with ``_`` (``_search``, ``_classify``,
``_validation``, ``_types``, ``_manager``, ``_commands``); reach for the
package import surface, not the submodules, unless you have a reason.
"""

from cc_code.memory._classify import (
    _CATEGORY_PRIORITY,
    _CLASSIFICATION_RULES,
    _auto_classify_content,
)
from cc_code.memory._commands import format_memory_list, inject_memory_into_prompt
from cc_code.memory._manager import MemoryManager, MemoryPaths
from cc_code.memory._search import (
    _CJK_BIGRAM_RE,
    _CODE_TERM_EXPANSIONS,
    _WORD_RE,
    _bm25_score,
    _compute_avgdl,
    _compute_idf,
    _compute_tf,
    _expand_query_terms,
    _tfidf_score,
    _tokenize,
    get_tfidf_keywords,
)
from cc_code.memory._types import (
    MemoryEntry,
    MemoryFile,
    MemoryScope,
    _VALID_SCOPES,
)
from cc_code.memory._validation import (
    _recover_entries,
    _validate_entry,
    _validate_memory_data,
)

__all__ = [
    # Types
    "MemoryScope",
    "MemoryEntry",
    "MemoryFile",
    # Manager
    "MemoryManager",
    "MemoryPaths",
    # Prompt integration / CLI
    "inject_memory_into_prompt",
    "format_memory_list",
    # Search / utility (exposed for tests and advanced callers)
    "get_tfidf_keywords",
    "_tokenize",
    "_CODE_TERM_EXPANSIONS",
    "_auto_classify_content",
]
