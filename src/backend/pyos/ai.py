"""AI writing help for Notepad.

The actions, request shape and responses are all in place, but no AI model is connected
yet, so every request answers with a clear "not connected" message. To connect one later,
implement `_run_model()` and set `CONNECTED = True`; the Notepad UI needs no changes.
"""

CONNECTED = False
MAX_TEXT = 20_000

ACTIONS = {
    "summarize": ("Summarize", "Sums up the note in a few sentences."),
    "fix": ("Fix spelling and grammar", "Corrects mistakes without changing what you meant."),
    "shorten": ("Make it shorter", "Cuts it down while keeping the main points."),
    "continue": ("Keep writing", "Writes the next few sentences in the same style."),
    "tone_friendly": ("Make it friendlier", "Rewrites it in a warmer, more casual tone."),
    "tone_formal": ("Make it more formal", "Rewrites it for work or school."),
    "ask": ("Ask about this note", "Answers a question using what's in the note."),
}


class AIUnavailable(Exception):
    """AI help isn't connected on this PyOS server."""


def status():
    return {
        "connected": CONNECTED,
        "actions": [{"id": key, "label": label, "about": about} for key, (label, about) in ACTIONS.items()],
    }


def assist(action, text, question=""):
    if action not in ACTIONS:
        raise ValueError(f"{action} isn't an AI action. Pick one from the list.")
    if not text.strip():
        raise ValueError("Write or select some text first.")
    if len(text) > MAX_TEXT:
        raise ValueError(f"AI help works on up to {MAX_TEXT} characters at a time. Select a part of the note.")
    if action == "ask" and not question.strip():
        raise ValueError("Type a question to ask about the note.")
    if not CONNECTED:
        label = ACTIONS[action][0]
        raise AIUnavailable(f"AI isn't connected yet, so \"{label}\" can't run. Your note hasn't been changed.")
    return {"action": action, "text": _run_model(action, text, question)}


def _run_model(action, text, question):
    raise AIUnavailable("No AI model is set up on this server.")
