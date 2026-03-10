def build_story_brief(payload, mode):
    return {
        "mode": mode,
        "user_message": payload["message"],
        "genre": payload.get("meta", {}).get("genre", ""),
        "style": payload.get("meta", {}).get("style", ""),
        "reference_text": payload.get("meta", {}).get("reference_text", ""),
        "framework_text": payload.get("meta", {}).get("framework_text", ""),
        "banned": payload.get("meta", {}).get("banned", ""),
        "output_granularity": payload.get("meta", {}).get("output_granularity", "outline")
    }