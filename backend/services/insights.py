from typing import Any
from models.schemas import Feedback


def calculate_productivity_insights(feedback_list: list[Feedback]) -> dict[str, Any]:
    total_outcomes = len(feedback_list)

    if total_outcomes == 0:
        return {
            "total_outcomes": 0,
            "completed_count": 0,
            "completion_rate": None,
            "on_time_recorded_count": 0,
            "on_time_count": 0,
            "on_time_rate": None,
            "rating_recorded_count": 0,
            "average_rating": None,
            "duration_metrics": {
                "sample_size": 0,
                "avg_planned_duration": None,
                "avg_actual_duration": None,
                "duration_diff_minutes": None,
            },
            "compatibility_comparison": {
                "matched": {"sample_size": 0, "completed_count": 0, "completion_rate": None},
                "mismatched": {"sample_size": 0, "completed_count": 0, "completion_rate": None},
            },
            "by_energy": [],
            "by_difficulty": [],
            "data_status": "no_data",
            "sample_size_adequate": False,
            "summary": "No task outcomes recorded yet. Complete check-ins to view productivity insights.",
            "cautionary_note": "Observational correlation does not establish causation. Task outcomes depend on interruptions, personal pacing, and estimation error as well as scheduling.",
        }

    completed_records = [
        f for f in feedback_list
        if f.completion_status == "completed" or (f.completion_status is None and f.completed)
    ]
    completed_count = len(completed_records)
    completion_rate = round((completed_count / total_outcomes) * 100, 1)

    on_time_records = [f for f in feedback_list if f.on_time is not None]
    on_time_recorded_count = len(on_time_records)
    on_time_count = sum(1 for f in on_time_records if f.on_time is True)
    on_time_rate = (
        round((on_time_count / on_time_recorded_count) * 100, 1)
        if on_time_recorded_count > 0
        else None
    )

    rated_records = [f for f in feedback_list if f.rating is not None]
    rating_recorded_count = len(rated_records)
    average_rating = (
        round(sum(f.rating for f in rated_records) / rating_recorded_count, 1)
        if rating_recorded_count > 0
        else None
    )

    # Planned vs Actual Duration (strictly where actual_duration was genuinely supplied)
    actual_dur_records = [
        f for f in feedback_list
        if f.actual_duration is not None and f.actual_duration > 0
    ]
    dur_sample = len(actual_dur_records)
    if dur_sample > 0:
        avg_planned = round(sum(f.duration for f in actual_dur_records) / dur_sample, 1)
        avg_actual = round(sum(f.actual_duration for f in actual_dur_records) / dur_sample, 1)
        diff_minutes = round(avg_actual - avg_planned, 1)
        duration_metrics = {
            "sample_size": dur_sample,
            "avg_planned_duration": avg_planned,
            "avg_actual_duration": avg_actual,
            "duration_diff_minutes": diff_minutes,
        }
    else:
        duration_metrics = {
            "sample_size": 0,
            "avg_planned_duration": None,
            "avg_actual_duration": None,
            "duration_diff_minutes": None,
        }

    def _calc_group(records: list[Feedback]) -> dict[str, Any]:
        count = len(records)
        if count == 0:
            return {"sample_size": 0, "completed_count": 0, "completion_rate": None}
        comp = sum(1 for f in records if f.completion_status == "completed" or (f.completion_status is None and f.completed))
        return {
            "sample_size": count,
            "completed_count": comp,
            "completion_rate": round((comp / count) * 100, 1),
        }

    # Energy-Aware Compatibility: matched (|diff - energy| <= 1) vs mismatched
    matched_records = [f for f in feedback_list if abs(f.difficulty - f.energy) <= 1]
    mismatched_records = [f for f in feedback_list if abs(f.difficulty - f.energy) > 1]

    compatibility_comparison = {
        "matched": _calc_group(matched_records),
        "mismatched": _calc_group(mismatched_records),
    }

    # Patterns by reported energy level (1-5)
    by_energy = []
    for level in range(1, 6):
        records = [f for f in feedback_list if f.energy == level]
        if records:
            res = _calc_group(records)
            res["energy"] = level
            by_energy.append(res)

    # Patterns by task difficulty (1-5)
    by_difficulty = []
    for diff in range(1, 6):
        records = [f for f in feedback_list if f.difficulty == diff]
        if records:
            res = _calc_group(records)
            res["difficulty"] = diff
            by_difficulty.append(res)

    sample_size_adequate = total_outcomes >= 5
    if total_outcomes < 5:
        data_status = "insufficient_sample"
        summary = (
            f"Preliminary data: {total_outcomes} task outcome(s) recorded. "
            f"A minimum sample size of 5 check-ins is recommended before assessing whether "
            f"energy-aware placement correlates with completion."
        )
    else:
        data_status = "sufficient_sample"
        matched_stat = compatibility_comparison["matched"]
        mismatched_stat = compatibility_comparison["mismatched"]
        if matched_stat["sample_size"] > 0 and mismatched_stat["sample_size"] > 0:
            summary = (
                f"Observed {total_outcomes} outcomes: "
                f"energy-matched tasks had a {matched_stat['completion_rate']}% completion rate (N={matched_stat['sample_size']}) "
                f"vs {mismatched_stat['completion_rate']}% for mismatched tasks (N={mismatched_stat['sample_size']})."
            )
        else:
            summary = f"Observed outcomes across {total_outcomes} task check-in(s)."

    return {
        "total_outcomes": total_outcomes,
        "completed_count": completed_count,
        "completion_rate": completion_rate,
        "on_time_recorded_count": on_time_recorded_count,
        "on_time_count": on_time_count,
        "on_time_rate": on_time_rate,
        "rating_recorded_count": rating_recorded_count,
        "average_rating": average_rating,
        "duration_metrics": duration_metrics,
        "compatibility_comparison": compatibility_comparison,
        "by_energy": by_energy,
        "by_difficulty": by_difficulty,
        "data_status": data_status,
        "sample_size_adequate": sample_size_adequate,
        "summary": summary,
        "cautionary_note": "Observational correlation does not establish causation. Task outcomes depend on interruptions, personal pacing, and estimation error as well as scheduling.",
    }
