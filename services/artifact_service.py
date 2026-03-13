# services/artifact_service.py
from models import db, ScriptModel, ChapterModel


def save_script_artifacts(
    project_id,
    *,
    character_bible=None,
    plot_outline=None,
    review_report=None,
    final_script=None,
    episode_plan=None,
):
    script = ScriptModel.query.get(int(project_id))
    if not script:
        raise ValueError(f"找不到项目：{project_id}")

    if character_bible is not None:
        script.characters = character_bible

    if plot_outline is not None:
        script.outline = plot_outline

    if review_report is not None:
        script.knowledge = review_report

    # 多集模式下不要每集都覆盖 content
    if final_script is not None:
        script.content = final_script

    db.session.add(script)
    db.session.commit()
    return script


def save_episode_artifact(
    project_id,
    episode_no,
    *,
    title=None,
    chapter_outline=None,
    chapter_script=None,
):
    chapter = ChapterModel.query.filter_by(script_id=int(project_id), number=int(episode_no)).first()

    if not chapter:
        chapter = ChapterModel(
            number=int(episode_no),
            title=title or f"第{episode_no}集",
            chapter_outline=chapter_outline or "待补充",
            chapter_script=chapter_script or "",
            script_id=int(project_id),
        )
        db.session.add(chapter)
    else:
        if title is not None:
            chapter.title = title
        if chapter_outline is not None:
            chapter.chapter_outline = chapter_outline
        if chapter_script is not None:
            chapter.chapter_script = chapter_script

    db.session.commit()
    return chapter