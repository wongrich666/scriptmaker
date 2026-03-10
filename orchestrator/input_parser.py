def detect_mode(message, meta):
    if meta.get("reference_text"):
        return "reskin"
    if meta.get("framework_text"):
        return "framework"
    return "free_generate"