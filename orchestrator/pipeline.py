from orchestrator.input_parser import detect_mode
from agents.chief_editor import build_story_brief
from agents.character_writer import generate_character_bible
from agents.plot_writer import generate_plot_outline
from agents.reviewer import review_artifacts

def run(payload):
    mode = detect_mode(payload["message"], payload.get("meta", {}))
    brief = build_story_brief(payload, mode)
    chars = generate_character_bible(brief)
    plot = generate_plot_outline(brief, chars)
    review = review_artifacts(brief, chars, plot)
    return {
        "mode": brief["mode"],
        "story_brief": brief,
        "character_bible": chars,
        "plot_outline": plot,
        "review_report": review
    }