# orchestrator/pipeline.py
import re

from agents.chief_editor import (
    build_story_brief,
    choose_delivery_mode,
    build_rewrite_instruction,
)
from agents.character_writer import (
    generate_character_bible,
    rewrite_character_bible,
)
from agents.plot_writer import (
    generate_plot_outline,
    rewrite_plot_outline,
    generate_episode_plan,
    rewrite_episode_plan,
    generate_episode_script,
    rewrite_episode_script,
)
from agents.reviewer import (
    review_character_bible,
    review_plot_outline,
    review_episode_plan,
    review_episode_script,
    review_five_episode_consistency,
)

def _ctx_call(ctx, name, *args, **kwargs):
    fn = ctx.get(name)
    if callable(fn):
        return fn(*args, **kwargs)
    return None


def _trace(ctx, stage, message, preview="", status="running"):
    _ctx_call(ctx, "append_trace", stage, message, status=status, preview=preview)


def _extract_episode_block(episode_plan: str, episode_no: int) -> str:
    text = (episode_plan or "").strip()
    if not text:
        return ""
    pattern = rf"(?ms)^第\s*{episode_no}\s*集.*?(?=^第\s*{episode_no + 1}\s*集|\Z)"
    m = re.search(pattern, text)
    return m.group(0).strip() if m else ""


def _summarize_episode(script_text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", (script_text or "").strip())
    return text[:limit] + ("..." if len(text) > limit else "")


def run_review_loop(ctx, stage_name, generate_fn, review_fn, rewrite_fn, max_rounds=3):
    draft = generate_fn()
    final_review = None

    for round_no in range(1, max_rounds + 1):
        final_review = review_fn(draft)

        _trace(
            ctx,
            stage_name,
            f"{stage_name} 第{round_no}轮审核完成",
            preview=(final_review.get("summary") or "")[:180],
            status="running",
        )

        if final_review.get("passed"):
            return draft, final_review

        final_review["rewrite_instruction"] = build_rewrite_instruction(stage_name, final_review)
        draft = rewrite_fn(draft, final_review)

    return draft, final_review


def run_character_stage(ctx, brief):
    _ctx_call(ctx, "update_task_stage", ctx["task_id"], "character_bible", status="running")
    chars, review = run_review_loop(
        ctx=ctx,
        stage_name="character_bible",
        generate_fn=lambda: generate_character_bible(brief, ctx["llm_call"], ctx["selected_model"]),
        review_fn=lambda draft: review_character_bible(brief, draft, ctx["llm_call"], ctx["selected_model"]),
        rewrite_fn=lambda draft, review_json: rewrite_character_bible(brief, draft, review_json, ctx["llm_call"], ctx["selected_model"]),
        max_rounds=3,
    )
    _ctx_call(ctx, "save_script_artifacts", ctx["project_id"], character_bible=chars)
    _ctx_call(ctx, "update_task_stage", ctx["task_id"], "character_bible", status="done")
    return chars, review


def run_outline_stage(ctx, brief, character_bible):
    _ctx_call(ctx, "update_task_stage", ctx["task_id"], "plot_outline", status="running")
    outline, review = run_review_loop(
        ctx=ctx,
        stage_name="plot_outline",
        generate_fn=lambda: generate_plot_outline(brief, character_bible, ctx["llm_call"], ctx["selected_model"]),
        review_fn=lambda draft: review_plot_outline(brief, character_bible, draft, ctx["llm_call"], ctx["selected_model"]),
        rewrite_fn=lambda draft, review_json: rewrite_plot_outline(brief, character_bible, draft, review_json, ctx["llm_call"], ctx["selected_model"]),
        max_rounds=3,
    )
    _ctx_call(ctx, "save_script_artifacts", ctx["project_id"], plot_outline=outline)
    _ctx_call(ctx, "update_task_stage", ctx["task_id"], "plot_outline", status="done")
    return outline, review


def run_episode_plan_stage(ctx, brief, character_bible, approved_outline):
    _ctx_call(ctx, "update_task_stage", ctx["task_id"], "plot_outline", status="running", message="正在生成分集计划")
    episode_plan, review = run_review_loop(
        ctx=ctx,
        stage_name="episode_plan",
        generate_fn=lambda: generate_episode_plan(brief, character_bible, approved_outline, ctx["llm_call"], ctx["selected_model"]),
        review_fn=lambda draft: review_episode_plan(brief, character_bible, approved_outline, draft, ctx["llm_call"], ctx["selected_model"]),
        rewrite_fn=lambda draft, review_json: rewrite_episode_plan(brief, character_bible, approved_outline, draft, review_json, ctx["llm_call"], ctx["selected_model"]),
        max_rounds=3,
    )
    _ctx_call(ctx, "save_script_artifacts", ctx["project_id"], episode_plan=None)
    return episode_plan, review


def run_single_episode_stage(ctx, brief, character_bible, approved_plan):
    episode_no = int(brief.get("current_episode_no") or 1)
    current_plan = _extract_episode_block(approved_plan, episode_no) or approved_plan

    _ctx_call(
        ctx,
        "update_task_record",
        ctx["task_id"],
        current_episode_no=episode_no,
        generated_episode_count=max(0, episode_no - 1),
    )

    script_text, review = run_review_loop(
        ctx=ctx,
        stage_name="final_script",
        generate_fn=lambda: generate_episode_script(
            brief, character_bible, approved_plan, episode_no, current_plan, "", ctx["llm_call"], ctx["selected_model"]
        ),
        review_fn=lambda draft: review_episode_script(
            brief, character_bible, approved_plan, episode_no, current_plan, draft, ctx["llm_call"], ctx["selected_model"]
        ),
        rewrite_fn=lambda draft, review_json: rewrite_episode_script(
            brief, character_bible, approved_plan, episode_no, current_plan, "", draft, review_json, ctx["llm_call"], ctx["selected_model"]
        ),
        max_rounds=2,
    )

    _ctx_call(
        ctx,
        "save_episode_artifact",
        ctx["project_id"],
        episode_no,
        title=f"第{episode_no}集",
        chapter_outline=current_plan,
        chapter_script=script_text,
    )
    _ctx_call(ctx, "update_task_record", ctx["task_id"], generated_episode_count=1)
    return script_text, review

def run_five_episode_consistency_stage(
    ctx,
    brief,
    character_bible,
    approved_outline,
    approved_plan,
    episodes,
    batch_start,
    batch_end,
    previous_batch_review=None,
):
    batch_episodes = [
        ep for ep in episodes
        if batch_start <= ep.get("episode_no", 0) <= batch_end
    ]

    _trace(
        ctx,
        "review_report",
        f"正在进行第{batch_start}-{batch_end}集连贯性总审",
        status="running",
    )

    review = review_five_episode_consistency(
        brief=brief,
        character_bible=character_bible,
        approved_outline=approved_outline,
        approved_plan=approved_plan,
        episode_batch=batch_episodes,
        batch_start=batch_start,
        batch_end=batch_end,
        llm_call=ctx["llm_call"],
        selected_model=ctx["selected_model"],
        previous_batch_review=previous_batch_review,
    )

    _ctx_call(
        ctx,
        "save_script_artifacts",
        ctx["project_id"],
        review_report=review.get("text_report", ""),
    )

    _trace(
        ctx,
        "review_report",
        f"第{batch_start}-{batch_end}集连贯性总审完成",
        preview=(review.get("summary") or "")[:180],
        status="done" if review.get("passed") else "failed",
    )

    return review


def run_multi_episode_stage(ctx, brief, character_bible, approved_outline, approved_plan):
    total = int(brief.get("episode_count") or 10)
    start_no = int(brief.get("current_episode_no") or 1)
    batch_size = int((ctx.get("meta") or {}).get("consistency_review_every") or 5)

    episodes = []
    previous_summary = ""
    previous_batch_review = None
    consistency_reviews = []

    for episode_no in range(start_no, total + 1):
        current_plan = _extract_episode_block(approved_plan, episode_no) or approved_plan

        _ctx_call(
            ctx,
            "update_task_record",
            ctx["task_id"],
            current_episode_no=episode_no,
            generated_episode_count=max(0, episode_no - start_no),
        )
        _ctx_call(
            ctx,
            "update_task_stage",
            ctx["task_id"],
            "final_script",
            status="running",
            message=f"正在生成第 {episode_no} 集剧本",
        )

        script_text, review = run_review_loop(
            ctx=ctx,
            stage_name=f"episode_{episode_no}_script",
            generate_fn=lambda ep_no=episode_no, cp=current_plan, prev=previous_summary: generate_episode_script(
                brief, character_bible, approved_plan, ep_no, cp, prev, ctx["llm_call"], ctx["selected_model"]
            ),
            review_fn=lambda draft, ep_no=episode_no, cp=current_plan: review_episode_script(
                brief, character_bible, approved_plan, ep_no, cp, draft, ctx["llm_call"], ctx["selected_model"]
            ),
            rewrite_fn=lambda draft, review_json, ep_no=episode_no, cp=current_plan, prev=previous_summary: rewrite_episode_script(
                brief, character_bible, approved_plan, ep_no, cp, prev, draft, review_json, ctx["llm_call"], ctx["selected_model"]
            ),
            max_rounds=2,
        )

        _ctx_call(
            ctx,
            "save_episode_artifact",
            ctx["project_id"],
            episode_no,
            title=f"第{episode_no}集",
            chapter_outline=current_plan,
            chapter_script=script_text,
        )

        episodes.append({
            "episode_no": episode_no,
            "chapter_outline": current_plan,
            "chapter_script": script_text,
            "review_report": review.get("text_report", ""),
        })
        previous_summary = _summarize_episode(script_text)

        _ctx_call(
            ctx,
            "update_task_record",
            ctx["task_id"],
            generated_episode_count=episode_no - start_no + 1,
        )

        generated_count = episode_no - start_no + 1
        is_batch_boundary = (generated_count % batch_size == 0)
        is_last_episode = (episode_no == total)

        if is_batch_boundary or is_last_episode:
            batch_end = episode_no
            batch_start = max(start_no, batch_end - batch_size + 1)

            consistency_review = run_five_episode_consistency_stage(
                ctx=ctx,
                brief=brief,
                character_bible=character_bible,
                approved_outline=approved_outline,
                approved_plan=approved_plan,
                episodes=episodes,
                batch_start=batch_start,
                batch_end=batch_end,
                previous_batch_review=previous_batch_review,
            )

            consistency_reviews.append(consistency_review)
            previous_batch_review = consistency_review.get("text_report", "")

            blocking = (ctx.get("meta") or {}).get("consistency_review_blocking", True)
            if blocking and not consistency_review.get("passed"):
                _ctx_call(
                    ctx,
                    "update_task_stage",
                    ctx["task_id"],
                    "review_report",
                    status="failed",
                    message=f"第{batch_start}-{batch_end}集连贯性审核未通过，已停止后续生成。",
                )
                return {
                    "episodes": episodes,
                    "consistency_reviews": consistency_reviews,
                    "stopped_early": True,
                    "stop_reason": f"第{batch_start}-{batch_end}集连贯性审核未通过",
                }

    _ctx_call(ctx, "update_task_stage", ctx["task_id"], "final_script", status="done")

    return {
        "episodes": episodes,
        "consistency_reviews": consistency_reviews,
        "stopped_early": False,
        "stop_reason": "",
    }


def run_workflow(ctx):
    payload = {
        "message": ctx["user_message"],
        "meta": ctx.get("meta") or {},
    }
    rough_mode = (ctx.get("meta") or {}).get("mode") or ""

    _ctx_call(ctx, "update_task_stage", ctx["task_id"], "queued", status="running")

    brief = build_story_brief(payload, rough_mode)
    brief["output_granularity"] = choose_delivery_mode(brief)

    chars, char_review = run_character_stage(ctx, brief)
    outline, outline_review = run_outline_stage(ctx, brief, chars)

    result = {
        "workflow_mode": brief["output_granularity"],
        "story_brief": brief,
        "character_bible": chars,
        "plot_outline": outline,
        "review_report": outline_review.get("text_report", ""),
    }

    mode = brief["output_granularity"]

    if mode == "outline":
        return result

    episode_plan, plan_review = run_episode_plan_stage(ctx, brief, chars, outline)
    result["episode_plan"] = episode_plan
    result["review_report"] = plan_review.get("text_report", "")

    if mode == "episode_plan":
        return result

    if mode == "single_episode_script":
        episode_script, script_review = run_single_episode_stage(ctx, brief, chars, episode_plan)
        result["single_episode_script"] = episode_script
        result["review_report"] = script_review.get("text_report", "")
        result["final_script"] = episode_script
        return result

    if mode == "multi_episode_script":
        batch_result = run_multi_episode_stage(ctx, brief, chars, outline, episode_plan)
        episodes = batch_result.get("episodes", [])
        consistency_reviews = batch_result.get("consistency_reviews", [])

        final_script = "\n\n".join(
            [x["chapter_script"] for x in episodes if x.get("chapter_script")]
        )

        result["episodes"] = episodes
        result["consistency_reviews"] = consistency_reviews
        result["stopped_early"] = batch_result.get("stopped_early", False)
        result["stop_reason"] = batch_result.get("stop_reason", "")
        result["final_script"] = final_script

        if consistency_reviews:
            result["review_report"] = consistency_reviews[-1].get("text_report", "")
        else:
            result["review_report"] = "\n\n".join(
                [x["review_report"] for x in episodes if x.get("review_report")]
            )

        return result

    return result