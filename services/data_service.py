from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.supabase_client import get_supabase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _letter_grade(avg: float | None) -> str:
    if avg is None:
        return "N/A"
    if avg >= 8.5:
        return "A"
    if avg >= 7.0:
        return "B"
    if avg >= 5.5:
        return "C"
    if avg >= 4.0:
        return "D"
    return "F"


def _weighted_average(
    grades_by_category: dict[str, dict],
    categories: list[dict],
    grading_scale: int,
    missing_grade_behavior: str,
) -> float | None:
    total_weight = 0.0
    weighted_sum = 0.0
    has_any = False

    for cat in categories:
        cid = str(cat["id"])
        cat_data = grades_by_category.get(cid, {})
        scores = cat_data.get("scores", [])
        max_score = float(cat["max_score"] or 1)
        weight = float(cat["weight"] or 0)

        if not scores:
            if missing_grade_behavior == "ignore":
                continue
            normalized = 0.0
        else:
            avg = sum(scores) / len(scores)
            normalized = (avg / max_score) * grading_scale

        weighted_sum += normalized * weight
        total_weight += weight
        has_any = True

    if not has_any or total_weight == 0:
        return None
    return round(weighted_sum / total_weight, 2)


def _attendance_stats(records: list[dict], total_sessions: int) -> dict:
    present = sum(1 for r in records if r["status"] == "present")
    late = sum(1 for r in records if r["status"] == "late")
    absent = sum(1 for r in records if r["status"] == "absent")
    excused = sum(1 for r in records if r["status"] == "excused")
    attended = present + late
    rate = round(attended / total_sessions, 4) if total_sessions > 0 else 0.0
    return {
        "present": present,
        "late": late,
        "absent": absent,
        "excused": excused,
        "total": total_sessions,
        "rate": rate,
    }


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------

def validate_token(token: str, expected_scope: str) -> tuple[dict | None, str | None, int]:
    """Returns (token_row, error_template_name, status_code)."""
    sb = get_supabase()
    result = (
        sb.table("share_tokens")
        .select("*")
        .eq("token", token)
        .eq("scope", expected_scope)
        .maybe_single()
        .execute()
    )
    row = result.data
    if not row:
        return None, "error.html", 404

    expires_at_str = row.get("expires_at")
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        if expires_at < datetime.now(timezone.utc):
            return None, "error.html", 410

    return row, None, 200


# ---------------------------------------------------------------------------
# Class report
# ---------------------------------------------------------------------------

def fetch_class_report_data(token_row: dict) -> dict:
    sb = get_supabase()
    classroom_id = token_row["classroom_id"]

    classroom_row = (
        sb.table("classrooms")
        .select("id,name,subject,room,schedule,grading_scale,missing_grade_behavior,color")
        .eq("id", classroom_id)
        .single()
        .execute()
        .data
    )
    grading_scale = int(classroom_row.get("grading_scale") or 10)
    missing_behavior = classroom_row.get("missing_grade_behavior") or "ignore"

    categories: list[dict] = (
        sb.table("grade_categories")
        .select("id,name,weight,max_score,sort_order")
        .eq("classroom_id", classroom_id)
        .order("sort_order")
        .execute()
        .data
    ) or []

    students_raw: list[dict] = (
        sb.table("students")
        .select("id,full_name,student_code,gender,badge,is_active")
        .eq("classroom_id", classroom_id)
        .eq("is_active", True)
        .order("full_name")
        .execute()
        .data
    ) or []

    sessions: list[dict] = (
        sb.table("class_sessions")
        .select("id,session_date,topic")
        .eq("classroom_id", classroom_id)
        .execute()
        .data
    ) or []
    session_ids = [s["id"] for s in sessions]
    total_sessions = len(sessions)

    attendance_records: list[dict] = []
    if session_ids:
        attendance_records = (
            sb.table("attendance_records")
            .select("session_id,student_id,status")
            .in_("session_id", session_ids)
            .execute()
            .data
        ) or []

    category_ids = [c["id"] for c in categories]
    student_ids = [s["id"] for s in students_raw]
    all_grades: list[dict] = []
    if category_ids and student_ids:
        all_grades = (
            sb.table("grades")
            .select("student_id,category_id,score")
            .in_("category_id", category_ids)
            .in_("student_id", student_ids)
            .execute()
            .data
        ) or []

    att_by_student: dict[str, list[dict]] = {}
    for rec in attendance_records:
        sid = str(rec["student_id"])
        att_by_student.setdefault(sid, []).append(rec)

    grades_index: dict[str, dict[str, list[float]]] = {}
    for g in all_grades:
        sid = str(g["student_id"])
        cid = str(g["category_id"])
        if g["score"] is not None:
            grades_index.setdefault(sid, {}).setdefault(cid, []).append(float(g["score"]))

    student_list = []
    for s in students_raw:
        sid = str(s["id"])
        grades_by_cat: dict[str, dict] = {}
        for cat in categories:
            cid = str(cat["id"])
            scores = grades_index.get(sid, {}).get(cid, [])
            avg = round(sum(scores) / len(scores), 2) if scores else None
            grades_by_cat[cid] = {"scores": scores, "avg": avg}

        avg_grade = _weighted_average(grades_by_cat, categories, grading_scale, missing_behavior)
        att = _attendance_stats(att_by_student.get(sid, []), total_sessions)

        student_list.append({
            "id": sid,
            "full_name": s["full_name"],
            "student_code": s.get("student_code") or "",
            "gender": s.get("gender") or "",
            "badge": s.get("badge") or "none",
            "avg_grade": avg_grade,
            "letter_grade": _letter_grade(avg_grade),
            "rank": 0,
            "attendance": att,
            "grades_by_category": grades_by_cat,
        })

    student_list.sort(key=lambda x: (x["avg_grade"] is None, -(x["avg_grade"] or 0)))
    current_rank = 0
    prev_avg: Any = object()
    for i, stu in enumerate(student_list):
        if stu["avg_grade"] != prev_avg:
            current_rank = i + 1
        stu["rank"] = current_rank
        prev_avg = stu["avg_grade"]

    graded_avgs = [s["avg_grade"] for s in student_list if s["avg_grade"] is not None]
    class_avg = round(sum(graded_avgs) / len(graded_avgs), 2) if graded_avgs else None

    all_att_rates = [s["attendance"]["rate"] for s in student_list]
    class_attendance_rate = (
        round(sum(all_att_rates) / len(all_att_rates), 4) if all_att_rates else 0.0
    )

    return {
        "classroom": classroom_row,
        "categories": categories,
        "students": student_list,
        "class_avg": class_avg,
        "class_attendance_rate": class_attendance_rate,
        "total_sessions": total_sessions,
    }


# ---------------------------------------------------------------------------
# Student report
# ---------------------------------------------------------------------------

def fetch_student_report_data(token_row: dict) -> dict:
    sb = get_supabase()
    student_id = token_row["student_id"]
    classroom_id = token_row["classroom_id"]

    student_row = (
        sb.table("students")
        .select(
            "id,full_name,student_code,gender,badge,parent_name,parent_phone,"
            "parent_email,date_of_birth,classroom_id,is_active"
        )
        .eq("id", student_id)
        .single()
        .execute()
        .data
    )

    classroom_row = (
        sb.table("classrooms")
        .select("id,name,subject,room,grading_scale,missing_grade_behavior,color")
        .eq("id", classroom_id)
        .single()
        .execute()
        .data
    )
    grading_scale = int(classroom_row.get("grading_scale") or 10)
    missing_behavior = classroom_row.get("missing_grade_behavior") or "ignore"

    categories: list[dict] = (
        sb.table("grade_categories")
        .select("id,name,weight,max_score,sort_order")
        .eq("classroom_id", classroom_id)
        .order("sort_order")
        .execute()
        .data
    ) or []
    category_ids = [c["id"] for c in categories]

    student_grades: list[dict] = []
    if category_ids:
        student_grades = (
            sb.table("grades")
            .select("category_id,score,graded_date")
            .eq("student_id", student_id)
            .in_("category_id", category_ids)
            .execute()
            .data
        ) or []

    grades_by_category: dict[str, dict] = {}
    cat_lookup = {str(c["id"]): c for c in categories}
    for g in student_grades:
        cid = str(g["category_id"])
        if g["score"] is not None:
            if cid not in grades_by_category:
                grades_by_category[cid] = {
                    "name": cat_lookup[cid]["name"],
                    "weight": cat_lookup[cid]["weight"],
                    "max_score": cat_lookup[cid]["max_score"],
                    "scores": [],
                    "avg": None,
                }
            grades_by_category[cid]["scores"].append(float(g["score"]))

    for cat in categories:
        cid = str(cat["id"])
        if cid not in grades_by_category:
            grades_by_category[cid] = {
                "name": cat["name"],
                "weight": cat["weight"],
                "max_score": cat["max_score"],
                "scores": [],
                "avg": None,
            }
        else:
            scores = grades_by_category[cid]["scores"]
            grades_by_category[cid]["avg"] = round(sum(scores) / len(scores), 2) if scores else None

    avg_grade = _weighted_average(grades_by_category, categories, grading_scale, missing_behavior)

    sessions: list[dict] = (
        sb.table("class_sessions")
        .select("id")
        .eq("classroom_id", classroom_id)
        .execute()
        .data
    ) or []
    session_ids = [s["id"] for s in sessions]
    total_sessions = len(sessions)

    student_att: list[dict] = []
    if session_ids:
        student_att = (
            sb.table("attendance_records")
            .select("session_id,status")
            .eq("student_id", student_id)
            .in_("session_id", session_ids)
            .execute()
            .data
        ) or []
    attendance = _attendance_stats(student_att, total_sessions)

    all_students: list[dict] = (
        sb.table("students")
        .select("id")
        .eq("classroom_id", classroom_id)
        .eq("is_active", True)
        .execute()
        .data
    ) or []
    total_students = len(all_students)

    rank = None
    if category_ids and total_students > 1:
        all_student_ids = [s["id"] for s in all_students]
        all_grades_rows: list[dict] = (
            sb.table("grades")
            .select("student_id,category_id,score")
            .in_("category_id", category_ids)
            .in_("student_id", all_student_ids)
            .execute()
            .data
        ) or []

        grades_idx: dict[str, dict[str, list[float]]] = {}
        for g in all_grades_rows:
            sid = str(g["student_id"])
            cid = str(g["category_id"])
            if g["score"] is not None:
                grades_idx.setdefault(sid, {}).setdefault(cid, []).append(float(g["score"]))

        averages: list[float | None] = []
        for s in all_students:
            sid = str(s["id"])
            gbc: dict[str, dict] = {}
            for cat in categories:
                cid = str(cat["id"])
                scores = grades_idx.get(sid, {}).get(cid, [])
                gbc[cid] = {"scores": scores, "avg": None}
            averages.append(_weighted_average(gbc, categories, grading_scale, missing_behavior))

        sorted_avgs = sorted([a for a in averages if a is not None], reverse=True)
        if avg_grade is not None:
            rank = next(
                (i + 1 for i, a in enumerate(sorted_avgs) if a <= avg_grade),
                len(sorted_avgs),
            )

    return {
        "student": {
            "id": str(student_row["id"]),
            "full_name": student_row["full_name"],
            "student_code": student_row.get("student_code") or "",
            "gender": student_row.get("gender") or "",
            "badge": student_row.get("badge") or "none",
            "parent_name": student_row.get("parent_name") or "",
            "parent_phone": student_row.get("parent_phone") or "",
            "parent_email": student_row.get("parent_email") or "",
            "date_of_birth": student_row.get("date_of_birth") or "",
        },
        "classroom": classroom_row,
        "categories": categories,
        "grades_by_category": grades_by_category,
        "avg_grade": avg_grade,
        "letter_grade": _letter_grade(avg_grade),
        "rank": rank,
        "total_students": total_students,
        "attendance": attendance,
    }
