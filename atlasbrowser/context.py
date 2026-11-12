"""Pinned user instructions (always-on instruction sets) and transparent, approximate request sizing.

Settings (shared by every profile, like the other AI settings):
  "core_sets"     [{"name": "Homework", "text": "..."}, ...]: named sets of always-on instructions
  "core_active"   the name of the set in use
  "core_enabled"  False turns always-on instructions off without losing them
  "core_instructions"  the text of the set in use (kept for older versions and as the starting set)
"""


def instruction_sets(store) -> list[dict]:
    sets = [s for s in (store.get('core_sets') or []) if isinstance(s, dict) and s.get('name')]
    if not sets:
        text = str(store.get('core_instructions') or '').strip()
        if text:
            sets = [{'name': 'My instructions', 'text': text}]
    return sets


def active_set(store) -> dict | None:
    sets = instruction_sets(store)
    name = store.get('core_active')
    return next((s for s in sets if s['name'] == name), sets[0] if sets else None)


def core_enabled(store) -> bool:
    return store.get('core_enabled') is not False


def save_sets(store, sets: list[dict], active: str | None, enabled: bool | None = None):
    store.set('core_sets', [{'name': s['name'], 'text': s.get('text', '')} for s in sets])
    store.set('core_active', active or (sets[0]['name'] if sets else ''))
    if enabled is not None:
        store.set('core_enabled', bool(enabled))
    cur = active_set(store)
    store.set('core_instructions', (cur or {}).get('text', '').strip())


def core_system(store):
    cur = active_set(store) if core_enabled(store) else None
    text = str((cur or {}).get('text') or '').strip()
    if not text:
        return ''
    return ('\n\nPersistent core instructions written by the user (keep these throughout the task; '
            'the current user request takes precedence):\n<core_instructions>\n' + text +
            '\n</core_instructions>')


def estimate_context(messages, system='', images=None):
    # Character heuristic, not provider tokenization; image cost varies by provider.
    chars = len(system) + sum(len(m.get('content', '')) for m in messages)
    return (chars + 3) // 4 + 8 * len(messages) + 1000 * len(images or [])
