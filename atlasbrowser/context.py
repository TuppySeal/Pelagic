"""Pinned user instructions and transparent, approximate request sizing."""
def core_system(store):
    text = str(store.get('core_instructions') or '').strip()
    if not text:
        return ''
    return ('\n\nPersistent core instructions written by the user (keep these throughout the task; '
            'the current user request takes precedence):\n<core_instructions>\n' + text +
            '\n</core_instructions>')


def estimate_context(messages, system='', images=None):
    # Character heuristic, not provider tokenization; image cost varies by provider.
    chars = len(system) + sum(len(m.get('content', '')) for m in messages)
    return (chars + 3) // 4 + 8 * len(messages) + 1000 * len(images or [])
