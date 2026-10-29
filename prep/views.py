"""Views for CSE Prep Master: pages + JSON APIs.

Scoring and answer keys live ONLY here (server side). The timed-test player
never receives correct answers or explanations until the test is submitted.
"""
import json
import random
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import (Attempt, AttemptAnswer, Bookmark, CodingProblem,
                     CodingSubmission, Profile, Question, QuestionOption, Subject, Test,
                     TestConfiguration, TestQuestion, Topic, StudySession)
from .runner import available_languages, run_code

# ---------------------------------------------------------------- helpers


def get_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def options_of(q):
    return [o.option_text for o in q.options.order_by("option_index")]


def public_question(q):
    return {"id": q.id, "subject": q.subject.name, "subjectId": q.subject_id,
            "topic": q.topic, "difficulty": q.difficulty, "type": q.type,
            "question": q.question, "options": options_of(q),
            "marks": q.marks, "timeSec": q.time_sec}


def full_question(q):
    d = public_question(q)
    d["correct"] = q.correct_indices()
    d["explanation"] = q.explanation
    return d


def pick_questions(subject_ids=None, topics=None, difficulties=None, count=10):
    qs = Question.objects.filter(status="approved").prefetch_related("options")
    if subject_ids:
        qs = qs.filter(subject_id__in=subject_ids)
    if topics:
        qs = qs.filter(topic__in=topics)
    if difficulties:
        qs = qs.filter(difficulty__in=difficulties)
    ids = list(qs.values_list("id", flat=True))
    random.shuffle(ids)
    return list(Question.objects.filter(id__in=ids[:count]).prefetch_related("options"))


def score_test(test):
    """Backend-only scoring. Returns (score, correct, incorrect, unattempted)."""
    cfg = test.config
    marks = cfg.marks_per_question if cfg else 4
    neg = cfg.negative_marks if cfg else 1
    score = correct = incorrect = unattempted = 0
    for item in test.items.select_related("question").prefetch_related("question__options"):
        if item.selected_option is None:
            unattempted += 1
            continue
        order = item.option_order or list(range(item.question.options.count()))
        chosen_original = order[item.selected_option] if item.selected_option < len(order) else -1
        if chosen_original in item.question.correct_indices():
            score += marks
            correct += 1
        else:
            score -= neg
            incorrect += 1
    return score, correct, incorrect, unattempted


def analytics_for(user):
    attempts = Attempt.objects.filter(user=user).select_related("question__subject")
    total = attempts.count()
    correct = attempts.filter(is_correct=True).count()
    by_subject, by_topic, by_diff = {}, {}, {}
    for a in attempts:
        q = a.question
        for bucket, key in ((by_subject, q.subject.name), (by_topic, q.topic),
                            (by_diff, q.difficulty)):
            b = bucket.setdefault(key, {"attempted": 0, "correct": 0})
            b["attempted"] += 1
            b["correct"] += 1 if a.is_correct else 0
    for bucket in (by_subject, by_topic, by_diff):
        for b in bucket.values():
            b["accuracy"] = round(100 * b["correct"] / b["attempted"], 1) if b["attempted"] else 0
    tests = Test.objects.filter(user=user, status="submitted").order_by("-submitted_at")[:10]
    subs = CodingSubmission.objects.filter(user=user)
    coding = {"attempted": subs.count(),
              "accepted": subs.filter(status="accepted").count()}
    # recommendations: weakest topics (min 3 attempts) first
    recs = []
    for topic, b in sorted(by_topic.items(), key=lambda kv: kv[1]["accuracy"]):
        if b["attempted"] >= 3 and b["accuracy"] < 70:
            recs.append({"topic": topic, "accuracy": b["accuracy"],
                         "message": f"Revise {topic} ({b['accuracy']}% over "
                                    f"{b['attempted']} attempts), then attempt a new practice set."})
    return {
        "totals": {"attempted": total, "correct": correct,
                   "incorrect": total - correct,
                   "accuracy": round(100 * correct / total, 1) if total else 0},
        "by_subject": by_subject, "by_topic": by_topic, "by_diff": by_diff,
        "tests": tests, "coding": coding, "recommendations": recs[:5],
    }


def _parse_list(raw):
    return [x.strip() for x in raw.split(",") if x.strip()]


# ---------------------------------------------------------------- pages


def landing(request):
    subjects = Subject.objects.annotate(n=Count("questions")).order_by("category", "name")
    cats = defaultdict(list)
    for s in subjects:
        cats[s.category].append(s)
    return render(request, "landing.html", {
        "categories": dict(cats),
        "total_questions": Question.objects.count(),
        "total_problems": CodingProblem.objects.count(),
    })


def register_view(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        if not name or not email or len(password) < 6:
            messages.error(request, "Please fill all fields (password: min 6 characters).")
        elif User.objects.filter(username=email).exists():
            messages.error(request, "An account with this email already exists.")
        else:
            user = User.objects.create_user(username=email, email=email,
                                            password=password, first_name=name)
            get_profile(user)
            login(request, user)
            return redirect("dashboard")
    return render(request, "register.html")


def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            return redirect("dashboard")
        messages.error(request, "Invalid email or password.")
    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("landing")


def dashboard_payload(user):
    """Everything the dashboard needs, JSON-serializable. Shared by the
    Django dashboard page and the /api/dashboard/ endpoint (Next.js UI)."""
    from datetime import timedelta
    data = analytics_for(user)
    today = timezone.now().date()
    days = [(today - timedelta(days=i)) for i in range(13, -1, -1)]
    attempts = Attempt.objects.filter(user=user, attempted_at__date__gte=days[0])
    per_day = defaultdict(lambda: {"attempted": 0, "correct": 0})
    for a in attempts:
        d = a.attempted_at.date()
        per_day[d]["attempted"] += 1
        per_day[d]["correct"] += 1 if a.is_correct else 0
    daily = [{"label": d.strftime("%d %b"), "attempted": per_day[d]["attempted"],
              "accuracy": round(100 * per_day[d]["correct"] / per_day[d]["attempted"], 1)
              if per_day[d]["attempted"] else 0} for d in days]
    week = daily[-7:]
    week_correct = sum(per_day[d]["correct"] for d in days[-7:])
    subject_labels, subject_counts = [], []
    for name, b in data["by_subject"].items():
        subject_labels.append(name)
        subject_counts.append(b["attempted"])
    recent = [{"question": a.question.question, "subject": a.question.subject.name,
               "isCorrect": a.is_correct,
               "at": a.attempted_at.strftime("%d %b %H:%M")}
              for a in Attempt.objects.filter(user=user).select_related(
                  "question", "question__subject").order_by("-attempted_at")[:8]]
    mistake_count = Attempt.objects.filter(user=user, is_correct=False) \
        .values("question").distinct().count()
    bookmark_count = Bookmark.objects.filter(user=user).count()
    # ---- new widgets for the reference-style dashboard ----
    total_topics = Topic.objects.count()
    attempted_topics = Attempt.objects.filter(user=user) \
        .values("question__topic").distinct().count()
    coverage = {"percent": round(100 * attempted_topics / total_topics, 1) if total_topics else 0,
                "attemptedTopics": attempted_topics, "totalTopics": total_topics}
    # calendar: attempts per day in the current month
    month_start = today.replace(day=1)
    cal = defaultdict(int)
    for a in Attempt.objects.filter(user=user, attempted_at__date__gte=month_start):
        cal[a.attempted_at.date().isoformat()] += 1
    calendar = [{"date": d, "attempted": n} for d, n in sorted(cal.items())]
    # top community contributors (approved questions only)
    contributors = []
    for u in User.objects.annotate(
            approved=Count("contributed_questions",
                           filter=Q(contributed_questions__status="approved"))) \
            .filter(approved__gt=0).order_by("-approved")[:5]:
        contributors.append({"name": u.first_name or u.username.split("@")[0],
                             "approved": u.approved})
    # study time this week from recorded sessions
    week_start = today - timedelta(days=7)
    study_minutes = 0
    for s in StudySession.objects.filter(user=user, ended_at__isnull=False,
                                         ended_at__date__gte=week_start):
        if s.started_at and s.ended_at:
            study_minutes += int((s.ended_at - s.started_at).total_seconds() // 60)
    # previous week (the 7 days before the last 7) for honest % change cards
    prev_start = today - timedelta(days=14)
    prev_qs = Attempt.objects.filter(user=user, attempted_at__date__gte=prev_start,
                                     attempted_at__date__lt=today - timedelta(days=7))
    prev_week = {"attempted": prev_qs.count(),
                 "correct": prev_qs.filter(is_correct=True).count()}
    # monthly attempted/correct for the last 6 calendar months (Study Habits chart)
    first_month = today.replace(day=1)
    for _ in range(5):
        first_month = (first_month - timedelta(days=1)).replace(day=1)
    month_buckets = {}
    for a in Attempt.objects.filter(user=user, attempted_at__date__gte=first_month) \
            .values("attempted_at", "is_correct"):
        key = (a["attempted_at"].year, a["attempted_at"].month)
        b = month_buckets.setdefault(key, {"attempted": 0, "correct": 0})
        b["attempted"] += 1
        if a["is_correct"]:
            b["correct"] += 1
    months = []
    cursor = first_month
    while cursor <= today.replace(day=1):
        b = month_buckets.get((cursor.year, cursor.month), {"attempted": 0, "correct": 0})
        months.append({"label": cursor.strftime("%b"), "attempted": b["attempted"],
                       "correct": b["correct"]})
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    tasks = [
        {"label": f"Revise {mistake_count} mistake(s) in My Mistakes",
         "link": "mistakes", "done": mistake_count == 0},
        {"label": f"Review {bookmark_count} bookmarked question(s)",
         "link": "bookmarks", "done": bookmark_count == 0},
        {"label": "Take a timed mock test",
         "link": "test_new",
         "done": Test.objects.filter(user=user, status="submitted").exists()},
        {"label": "Solve a coding problem",
         "link": "coding_list",
         "done": CodingSubmission.objects.filter(user=user, status="accepted").exists()},
    ]
    return {
        "totals": data["totals"], "bySubject": data["by_subject"],
        "byTopic": data["by_topic"], "byDifficulty": data["by_diff"],
        "coding": data["coding"], "recommendations": data["recommendations"],
        "daily": daily, "week": week, "subjectLabels": subject_labels,
        "subjectCounts": subject_counts, "recent": recent, "tasks": tasks,
        "mistakeCount": mistake_count, "bookmarkCount": bookmark_count,
        "weekAttempted": sum(d["attempted"] for d in week),
        "weekCorrect": week_correct,
        "tasksDone": sum(1 for t in tasks if t["done"]),
        "codingTotal": CodingProblem.objects.count(),
        "coverage": coverage, "calendar": calendar,
        "contributors": contributors, "studyMinutesWeek": study_minutes,
        "prevWeek": prev_week, "monthly": months,
    }


def create_test_from_data(user, mode="objective", subject_ids=None, topics=None,
                          difficulties=None, count=10, duration=30, marks=4,
                          neg=1, name="Custom Test"):
    """Shared by the Django test form and the /api/tests/ endpoint.
    Returns the Test, or None when no questions match."""
    questions = pick_questions(subject_ids or None, topics or None,
                               difficulties or None, count)
    if not questions:
        return None
    cfg = TestConfiguration.objects.create(
        user=user, name=name or "Custom Test", mode=mode,
        subject_ids=",".join(subject_ids or []), topic_names=",".join(topics or []),
        difficulties=",".join(difficulties or []), question_count=len(questions),
        duration_min=duration, marks_per_question=marks, negative_marks=neg)
    test = Test.objects.create(user=user, config=cfg, mode=mode,
                               total_marks=len(questions) * marks)
    for pos, q in enumerate(questions, 1):
        order = list(range(q.options.count()))
        random.shuffle(order)
        TestQuestion.objects.create(test=test, question=q, position=pos,
                                    option_order=order)
    return test


@login_required
def dashboard(request):
    p = dashboard_payload(request.user)
    mistakes = Attempt.objects.filter(user=request.user, is_correct=False) \
        .select_related("question").order_by("-attempted_at")[:5]
    bookmarks = Bookmark.objects.filter(user=request.user).select_related("question")[:5]
    subjects = Subject.objects.annotate(
        n=Count("questions", filter=Q(questions__status="approved"))).order_by("category", "name")[:8]
    data = {"totals": p["totals"], "by_subject": p["bySubject"],
            "recommendations": p["recommendations"], "coding": p["coding"]}
    return render(request, "dashboard.html", {
        "data": data, "mistakes": mistakes, "bookmarks": bookmarks,
        "subjects": subjects, "coding_total": p["codingTotal"],
        "daily_json": json.dumps(p["daily"]), "week_json": json.dumps(p["week"]),
        "subject_labels_json": json.dumps(p["subjectLabels"]),
        "subject_counts_json": json.dumps(p["subjectCounts"]),
        "recent": Attempt.objects.filter(user=request.user).select_related(
            "question", "question__subject").order_by("-attempted_at")[:8],
        "tasks": p["tasks"], "mistake_count": p["mistakeCount"],
        "week_attempted": p["weekAttempted"], "tasks_done": p["tasksDone"],
    })


def subjects_view(request):
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    semester = request.GET.get("semester", "")
    subjects = Subject.objects.annotate(n=Count("questions"))
    if q:
        subjects = subjects.filter(Q(name__icontains=q) | Q(code__icontains=q))
    if category:
        subjects = subjects.filter(category=category)
    if semester:
        subjects = subjects.filter(semester=semester)
    if request.method == "POST" and request.user.is_authenticated:
        name = request.POST.get("name", "").strip()
        category_new = request.POST.get("category", "Technical MCQs")
        code = request.POST.get("code", "").strip()
        semester_new = request.POST.get("semester") or None
        if name:
            Subject.objects.create(name=name, category=category_new, code=code,
                                   semester=semester_new, is_custom=True)
            messages.success(request, f"Subject '{name}' added.")
            return redirect("subjects")
    return render(request, "subjects.html", {
        "subjects": subjects.order_by("category", "name"),
        "categories": [c[0] for c in Subject.CATEGORIES],
        "q": q, "category": category, "semester": semester,
    })


# ---------------------------------------------------------------- practice


def practice_view(request):
    subjects = Subject.objects.annotate(n=Count("questions")).order_by("category", "name")
    if request.method == "POST":
        subject_id = request.POST.get("subject") or None
        topic = request.POST.get("topic") or None
        difficulty = request.POST.get("difficulty") or None
        try:
            count = int(request.POST.get("count", 10))
        except ValueError:
            count = 10
        count = max(1, min(count, 50))
        questions = pick_questions(
            [subject_id] if subject_id else None,
            [topic] if topic else None,
            [difficulty] if difficulty else None, count)
        if not questions:
            messages.error(request, "No questions match that selection. Try a broader filter.")
            return redirect("practice")
        request.session["practice_ids"] = [q.id for q in questions]
        return redirect("practice_run")
    return render(request, "practice.html", {"subjects": subjects})


def practice_run(request):
    ids = request.session.get("practice_ids") or []
    questions = list(Question.objects.filter(id__in=ids).prefetch_related("options"))
    order = {qid: i for i, qid in enumerate(ids)}
    questions.sort(key=lambda q: order.get(q.id, 0))
    if not questions:
        return redirect("practice")
    bookmarked = set()
    if request.user.is_authenticated:
        bookmarked = set(Bookmark.objects.filter(user=request.user, question_id__in=ids)
                         .values_list("question_id", flat=True))
    return render(request, "practice_run.html", {
        "questions": questions, "bookmarked": bookmarked,
        "questions_json": json.dumps([public_question(q) for q in questions]),
    })


@require_POST
def api_practice_answer(request):
    try:
        data = json.loads(request.body)
        q = get_object_or_404(Question, id=data.get("question_id"))
        selected = data.get("selected")
        correct = selected is not None and selected in q.correct_indices()
        if request.user.is_authenticated:
            attempt = Attempt.objects.create(user=request.user, question=q,
                                             selected_option=selected, is_correct=correct)
            AttemptAnswer.objects.create(attempt=attempt, question=q,
                                         selected_option=selected, is_correct=correct)
        return JsonResponse({"correct": correct, "correctOption": q.correct_indices(),
                             "explanation": q.explanation})
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "Invalid request."}, status=400)


@require_POST
def api_bookmark_toggle(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login required."}, status=401)
    try:
        data = json.loads(request.body)
        q = get_object_or_404(Question, id=data.get("question_id"))
        bm, created = Bookmark.objects.get_or_create(user=request.user, question=q)
        if not created:
            bm.delete()
        return JsonResponse({"bookmarked": created})
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid request."}, status=400)

# ---------------------------------------------------------------- tests

def test_new(request):
    subjects = Subject.objects.annotate(n=Count("questions")).order_by("category", "name")
    if request.method == "POST":
        mode = request.POST.get("mode", "objective")
        subject_ids = [s for s in request.POST.getlist("subjects") if s]
        topics = _parse_list(request.POST.get("topics", ""))
        difficulties = [d for d in request.POST.getlist("difficulties") if d]
        try:
            count = max(1, min(int(request.POST.get("count", 10)), 100))
            duration = max(1, int(request.POST.get("duration", 30)))
            marks = max(1, int(request.POST.get("marks", 4)))
            neg = max(0, int(request.POST.get("negative", 1)))
        except ValueError:
            count, duration, marks, neg = 10, 30, 4, 1
        test = create_test_from_data(
            request.user if request.user.is_authenticated else None,
            mode=mode, subject_ids=subject_ids, topics=topics,
            difficulties=difficulties, count=count, duration=duration,
            marks=marks, neg=neg,
            name=request.POST.get("name", "Custom Test"))
        if not test:
            messages.error(request, "No questions match that configuration.")
            return redirect("test_new")
        return redirect("test_player", test_id=test.id)
    return render(request, "test_new.html", {"subjects": subjects})


def _visible_test(test):
    """Test + items with options in the student's shuffled order (no answers)."""
    items = []
    for item in test.items.select_related("question").prefetch_related("question__options"):
        opts = options_of(item.question)
        order = item.option_order or list(range(len(opts)))
        items.append({"item": item, "question": item.question,
                      "options": [opts[i] for i in order]})
    return items


def test_player(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    if test.status == "submitted":
        return redirect("test_result", test_id=test.id)
    if test.user and request.user.is_authenticated and test.user != request.user \
            and not request.user.is_staff:
        messages.error(request, "This test belongs to another student.")
        return redirect("dashboard")
    items = _visible_test(test)
    items_json = json.dumps([{
        "qid": it["question"].id, "subject": it["question"].subject.name,
        "topic": it["question"].topic, "difficulty": it["question"].difficulty,
        "question": it["question"].question, "options": it["options"],
        "selected": it["item"].selected_option,
        "marked": it["item"].marked_for_review,
    } for it in items])
    return render(request, "test_player.html", {
        "test": test, "items": items, "items_json": items_json,
        "duration_sec": (test.config.duration_min if test.config else 30) * 60,
    })


@require_POST
def api_test_answer(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    if test.status == "submitted":
        return JsonResponse({"error": "Test already submitted."}, status=400)
    try:
        data = json.loads(request.body)
        item = get_object_or_404(TestQuestion, test=test, question_id=data.get("question_id"))
        selected = data.get("selected")
        item.selected_option = selected if selected in (None, 0, 1, 2, 3) else None
        item.marked_for_review = bool(data.get("marked"))
        item.save()
        return JsonResponse({"ok": True})
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid request."}, status=400)


@require_POST
def api_test_submit(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    if test.status == "submitted":
        return JsonResponse({"error": "Test already submitted."}, status=400)
    score, correct, incorrect, unattempted = score_test(test)
    test.score, test.correct_count, test.incorrect_count = score, correct, incorrect
    test.unattempted_count = unattempted
    test.status = "submitted"
    test.submitted_at = timezone.now()
    test.save()
    return JsonResponse({"score": score, "totalMarks": test.total_marks,
                         "correct": correct, "incorrect": incorrect,
                         "unattempted": unattempted})


def test_result(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    if test.status != "submitted":
        return redirect("test_player", test_id=test.id)
    return render(request, "test_result.html", {"test": test})


def test_review(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    if test.status != "submitted":
        messages.error(request, "Answers and explanations are revealed only after submission.")
        return redirect("test_player", test_id=test.id)
    rows = []
    for item in test.items.select_related("question").prefetch_related("question__options"):
        opts = options_of(item.question)
        order = item.option_order or list(range(len(opts)))
        shown = [opts[i] for i in order]
        correct_shown = [order.index(c) for c in item.question.correct_indices()
                         if c < len(order)]
        chosen_ok = (item.selected_option is not None
                     and order[item.selected_option] in item.question.correct_indices())
        opts = [{"letter": chr(65 + i), "text": text,
                 "is_correct": i in correct_shown,
                 "is_selected": i == item.selected_option}
                for i, text in enumerate(shown)]
        rows.append({"question": item.question, "opts": opts,
                     "selected": item.selected_option, "correct": correct_shown,
                     "is_correct": chosen_ok, "marked": item.marked_for_review,
                     "explanation": item.question.explanation})
    return render(request, "test_review.html", {"test": test, "rows": rows})


# ---------------------------------------------------------------- coding

def coding_list(request):
    difficulty = request.GET.get("difficulty", "")
    topic = request.GET.get("topic", "")
    problems = CodingProblem.objects.all()
    if difficulty:
        problems = problems.filter(difficulty=difficulty)
    if topic:
        problems = problems.filter(topic__icontains=topic)
    solved = set()
    if request.user.is_authenticated:
        solved = set(CodingSubmission.objects.filter(user=request.user, status="accepted")
                     .values_list("problem_id", flat=True))
    return render(request, "coding_list.html", {
        "problems": problems.order_by("difficulty", "title"),
        "difficulty": difficulty, "topic": topic, "solved": solved,
    })


def coding_workspace(request, problem_id):
    problem = get_object_or_404(CodingProblem, id=problem_id)
    return render(request, "coding_workspace.html", {
        "problem": problem, "languages": available_languages(),
        "starter": json.dumps(problem.starter_code_json or {}),
        "visible_tests": problem.visible_tests(),
    })


def _check_output(actual, expected):
    return actual.strip() == expected.strip()


@require_POST
def api_coding_run(request, problem_id):
    try:
        data = json.loads(request.body)
        result = run_code(data.get("language", "python"), data.get("code", ""),
                          data.get("input", ""))
        return JsonResponse(result)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid request."}, status=400)


@require_POST
def api_coding_submit(request, problem_id):
    problem = get_object_or_404(CodingProblem, id=problem_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid request."}, status=400)
    language, code = data.get("language", "python"), data.get("code", "")
    results, passed = [], 0
    for t in problem.tests_json:
        r = run_code(language, code, t.get("input", ""))
        ok = (not r["error"]) and _check_output(r["output"], t.get("output", ""))
        passed += 1 if ok else 0
        entry = {"passed": ok, "visible": not t.get("hidden")}
        if not t.get("hidden"):
            entry["output"] = r["output"]
            entry["expected"] = t.get("output")
            entry["error"] = r["error"]
        elif r["error"]:
            entry["error"] = "Runtime error on a hidden test."
        results.append(entry)
    total = len(problem.tests_json)
    status = "accepted" if total and passed == total else ("partial" if passed else "failed")
    if request.user.is_authenticated:
        CodingSubmission.objects.create(user=request.user, problem=problem,
                                        language=language, code=code, status=status,
                                        passed_count=passed, total_count=total)
    return JsonResponse({"passed": passed, "total": total, "status": status,
                         "results": results})

# ---------------------------------------------------------------- mistakes / bookmarks / analytics

@login_required
def mistakes_view(request):
    subject = request.GET.get("subject", "")
    topic = request.GET.get("topic", "")
    difficulty = request.GET.get("difficulty", "")
    wrong = Attempt.objects.filter(user=request.user, is_correct=False) \
        .select_related("question", "question__subject").order_by("-attempted_at")
    if subject:
        wrong = wrong.filter(question__subject_id=subject)
    if topic:
        wrong = wrong.filter(question__topic__icontains=topic)
    if difficulty:
        wrong = wrong.filter(question__difficulty=difficulty)
    # one row per question: latest wrong attempt + mistake count
    seen, rows = {}, []
    for a in wrong:
        qid = a.question_id
        seen[qid] = seen.get(qid, 0) + 1
        if seen[qid] == 1:
            rows.append({"attempt": a, "question": a.question, "count": 1})
        else:
            for r in rows:
                if r["question"].id == qid:
                    r["count"] = seen[qid]
    if request.method == "POST":
        action = request.POST.get("action")
        qid = request.POST.get("question_id")
        if action == "remove" and qid:
            Attempt.objects.filter(user=request.user, question_id=qid,
                                   is_correct=False).delete()
            messages.success(request, "Removed from revision.")
            return redirect("mistakes")
        if action == "retry" and qid:
            request.session["practice_ids"] = [int(qid)]
            return redirect("practice_run")
        if action == "practice_all" and rows:
            request.session["practice_ids"] = [r["question"].id for r in rows]
            return redirect("practice_run")
    return render(request, "mistakes.html", {
        "rows": rows, "subjects": Subject.objects.all(),
        "subject": subject, "topic": topic, "difficulty": difficulty,
    })


@login_required
def bookmarks_view(request):
    bms = Bookmark.objects.filter(user=request.user).select_related("question", "question__subject")
    if request.method == "POST":
        qid = request.POST.get("question_id")
        Bookmark.objects.filter(user=request.user, question_id=qid).delete()
        messages.success(request, "Bookmark removed.")
        return redirect("bookmarks")
    return render(request, "bookmarks.html", {"bookmarks": bms})


@login_required
def analytics_view(request):
    return render(request, "analytics.html", {"data": analytics_for(request.user)})


@login_required
def profile_view(request):
    profile = get_profile(request.user)
    if request.method == "POST":
        profile.semester = request.POST.get("semester") or None
        profile.preferred_subjects = request.POST.get("preferred_subjects", "")
        profile.goals = request.POST.get("goals", "")
        profile.save()
        messages.success(request, "Profile saved.")
        return redirect("profile")
    return render(request, "profile.html", {
        "profile": profile, "subjects": Subject.objects.all(),
    })


def admin_panel(request):
    if not request.user.is_staff:
        return render(request, "admin_panel.html", {"denied": True})
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete":
            Question.objects.filter(id=request.POST.get("question_id")).delete()
            messages.success(request, "Question deleted.")
        elif action in ("approve", "reject"):
            Question.objects.filter(id=request.POST.get("question_id")).update(
                status="approved" if action == "approve" else "rejected")
            messages.success(request, f"Question {action}d.")
        elif action in ("add", "edit"):
            qid = request.POST.get("question_id")
            subject = get_object_or_404(Subject, id=request.POST.get("subject"))
            opts = [request.POST.get(f"opt{i}", "") for i in range(4)]
            try:
                correct = int(request.POST.get("correct", 0))
            except ValueError:
                correct = 0
            if not request.POST.get("question") or any(not o for o in opts):
                messages.error(request, "Question and all 4 options are required.")
            else:
                q = Question.objects.get(id=qid) if (action == "edit" and qid) else Question()
                q.subject, q.topic = subject, request.POST.get("topic", "").strip()
                q.difficulty = request.POST.get("difficulty", "easy")
                q.question = request.POST.get("question")
                q.explanation = request.POST.get("explanation", "")
                q.marks = int(request.POST.get("marks", 1) or 1)
                q.save()
                q.options.all().delete()
                for i, text in enumerate(opts):
                    QuestionOption.objects.create(question=q, option_index=i,
                                                  option_text=text, is_correct=(i == correct))
                messages.success(request, "Question saved.")
        return redirect("admin_panel")
    return render(request, "admin_panel.html", {
        "denied": False,
        "questions": Question.objects.select_related("subject").order_by("-id")[:100],
        "pending": Question.objects.filter(status="pending")
                    .select_related("subject", "submitted_by").order_by("-created_at"),
        "subjects": Subject.objects.all(),
        "stats": {"questions": Question.objects.count(),
                  "problems": CodingProblem.objects.count(),
                  "users": User.objects.count(),
                  "tests": Test.objects.count(),
                  "pending": Question.objects.filter(status="pending").count()},
    })


def assistant_view(request):
    query = request.GET.get("q", "").strip()
    notes = []
    if query:
        notes = Topic.objects.filter(
            Q(name__icontains=query) | Q(notes__icontains=query)
            | Q(subject__name__icontains=query)).select_related("subject")[:20]
    plan = []
    if request.user.is_authenticated:
        plan = analytics_for(request.user)["recommendations"]
    return render(request, "assistant.html", {"query": query, "notes": notes, "plan": plan})


# ---------------------------------------------------------------- contributions

@login_required
def contribute_view(request):
    """Any logged-in student can add a question + its answer. It enters the
    bank only after a staff member approves it (see admin_panel queue)."""
    subjects = Subject.objects.order_by("category", "name")
    if request.method == "POST":
        subject = get_object_or_404(Subject, id=request.POST.get("subject"))
        topic = request.POST.get("topic", "").strip()
        question_text = request.POST.get("question", "").strip()
        opts = [request.POST.get(f"opt{i}", "").strip() for i in range(4)]
        explanation = request.POST.get("explanation", "").strip()
        try:
            correct = int(request.POST.get("correct", -1))
        except ValueError:
            correct = -1
        if not topic or not question_text or any(not o for o in opts) \
                or correct not in (0, 1, 2, 3) or not explanation:
            messages.error(request, "All fields are required: topic, question, "
                                    "all 4 options, the correct answer and the explanation.")
        else:
            q = Question.objects.create(
                subject=subject, topic=topic, difficulty=request.POST.get("difficulty", "easy"),
                question=question_text, explanation=explanation,
                marks=int(request.POST.get("marks", 1) or 1),
                submitted_by=request.user, status="pending")
            for i, text in enumerate(opts):
                QuestionOption.objects.create(question=q, option_index=i,
                                              option_text=text, is_correct=(i == correct))
            messages.success(request, "Thank you! Your question was submitted and is "
                                      "waiting for review. It will appear in practice "
                                      "once approved.")
            return redirect("my_contributions")
    return render(request, "contribute.html", {"subjects": subjects})


@login_required
def my_contributions(request):
    qs = Question.objects.filter(submitted_by=request.user) \
        .select_related("subject").prefetch_related("options").order_by("-created_at")
    return render(request, "my_contributions.html", {"questions": qs})


# ---------------------------------------------------------------- public JSON API

def api_subjects(request):
    if request.method == "POST":
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Login required."}, status=401)
        data = _json_body(request)
        if not (data.get("name") or "").strip():
            return JsonResponse({"error": "Name is required."}, status=400)
        s = Subject.objects.create(
            name=data["name"].strip(),
            category=data.get("category", "Technical MCQs"),
            code=data.get("code", ""), semester=data.get("semester") or None,
            is_custom=True)
        return JsonResponse({"ok": True, "id": s.id})
    data = []
    for s in Subject.objects.prefetch_related("topics").order_by("category", "name"):
        data.append({"id": s.id, "name": s.name, "category": s.category,
                     "code": s.code, "semester": s.semester,
                     "topics": [{"id": t.id, "name": t.name, "notes": t.notes}
                                for t in s.topics.all()],
                     "questionCount": s.questions.count()})
    return JsonResponse({"subjects": data})


def api_questions(request):
    qs = Question.objects.filter(status="approved").prefetch_related("options")
    if request.GET.get("subject"):
        qs = qs.filter(subject_id=request.GET["subject"])
    if request.GET.get("topic"):
        qs = qs.filter(topic__icontains=request.GET["topic"])
    if request.GET.get("difficulty"):
        qs = qs.filter(difficulty=request.GET["difficulty"])
    if request.GET.get("search"):
        s = request.GET["search"]
        qs = qs.filter(Q(question__icontains=s) | Q(topic__icontains=s)
                       | Q(subject__name__icontains=s))
    try:
        limit = max(1, min(int(request.GET.get("limit", 20)), 100))
    except ValueError:
        limit = 20
    return JsonResponse({"questions": [public_question(q) for q in qs[:limit]]})

# ================================================================ Next.js API
# JSON endpoints consumed by the React/Next.js frontend (frontend/).
# The browser talks to Next.js, which proxies /api/* to Django, so these
# run on the same site: session + CSRF cookies work unchanged.

def _json_user(user):
    return {"id": user.id, "name": user.first_name or user.username,
            "email": user.email, "isStaff": user.is_staff}


@ensure_csrf_cookie
def api_csrf(request):
    return JsonResponse({"csrfToken": get_token(request)})


def api_me(request):
    if request.user.is_authenticated:
        return JsonResponse({"authenticated": True, "user": _json_user(request.user)})
    return JsonResponse({"authenticated": False, "user": None})


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


@require_POST
def api_auth_login(request):
    data = _json_body(request)
    user = authenticate(request, username=(data.get("email") or "").strip().lower(),
                        password=data.get("password", ""))
    if user is None:
        return JsonResponse({"error": "Invalid email or password."}, status=400)
    login(request, user)
    return JsonResponse({"ok": True, "user": _json_user(user)})


@require_POST
def api_auth_register(request):
    data = _json_body(request)
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")
    if not name or not email or len(password) < 6:
        return JsonResponse({"error": "Name, email and a 6+ character password are required."},
                            status=400)
    if User.objects.filter(username=email).exists():
        return JsonResponse({"error": "An account with this email already exists."}, status=400)
    user = User.objects.create_user(username=email, email=email, password=password,
                                    first_name=name)
    get_profile(user)
    login(request, user)
    return JsonResponse({"ok": True, "user": _json_user(user)})


@require_POST
def api_auth_logout(request):
    logout(request)
    return JsonResponse({"ok": True})


@login_required
def api_dashboard(request):
    return JsonResponse(dashboard_payload(request.user))


@login_required
@require_POST
def api_study_session(request):
    """Record one finished study-timer session (from the dashboard Time
    tracker widget). Body: {startedAt, endedAt} as ISO strings."""
    from datetime import datetime
    data = _json_body(request)
    try:
        started = datetime.fromisoformat((data.get("startedAt") or "").replace("Z", "+00:00"))
        ended = datetime.fromisoformat((data.get("endedAt") or "").replace("Z", "+00:00"))
    except ValueError:
        return JsonResponse({"error": "startedAt and endedAt must be ISO timestamps."},
                            status=400)
    if ended <= started:
        return JsonResponse({"error": "endedAt must be after startedAt."}, status=400)
    StudySession.objects.create(user=request.user, started_at=started, ended_at=ended,
                                questions_attempted=0)
    return JsonResponse({"ok": True})


@login_required
def api_analytics(request):
    data = analytics_for(request.user)
    return JsonResponse({
        "totals": data["totals"], "bySubject": data["by_subject"],
        "byTopic": data["by_topic"], "byDifficulty": data["by_diff"],
        "coding": data["coding"], "recommendations": data["recommendations"],
        "tests": [{"id": t.id, "name": t.config.name if t.config else "Test",
                   "score": t.score, "totalMarks": t.total_marks,
                   "correct": t.correct_count, "incorrect": t.incorrect_count,
                   "unattempted": t.unattempted_count,
                   "at": t.submitted_at.strftime("%d %b %Y") if t.submitted_at else ""}
                  for t in data["tests"]],
    })


@login_required
def api_mistakes(request):
    if request.method == "POST":
        data = _json_body(request)
        if data.get("action") == "remove" and data.get("questionId"):
            Attempt.objects.filter(user=request.user, question_id=data["questionId"],
                                   is_correct=False).delete()
            return JsonResponse({"ok": True})
        return JsonResponse({"error": "Unknown action."}, status=400)
    wrong = Attempt.objects.filter(user=request.user, is_correct=False) \
        .select_related("question", "question__subject").order_by("-attempted_at")
    seen, rows = {}, []
    for a in wrong:
        seen[a.question_id] = seen.get(a.question_id, 0) + 1
        if seen[a.question_id] == 1:
            q = a.question
            rows.append({"question": public_question(q), "correct": q.correct_indices(),
                         "explanation": q.explanation, "lastSelected": a.selected_option,
                         "count": 1})
        else:
            for r in rows:
                if r["question"]["id"] == a.question_id:
                    r["count"] = seen[a.question_id]
    return JsonResponse({"mistakes": rows})


@login_required
def api_bookmarks_list(request):
    bms = Bookmark.objects.filter(user=request.user) \
        .select_related("question", "question__subject").order_by("-created_at")
    out = []
    for b in bms:
        d = public_question(b.question)
        d["correct"] = b.question.correct_indices()
        d["explanation"] = b.question.explanation
        out.append(d)
    return JsonResponse({"bookmarks": out})


def _coding_public(p):
    return {"id": p.id, "title": p.title, "difficulty": p.difficulty, "topic": p.topic,
            "description": p.description, "inputFormat": p.input_format,
            "outputFormat": p.output_format, "constraints": p.constraints,
            "examples": p.examples_json, "visibleTests": p.visible_tests(),
            "starterCode": p.starter_code_json, "timeComplexity": p.time_complexity,
            "spaceComplexity": p.space_complexity, "hints": p.hints_json}


def api_coding_list(request):
    problems = CodingProblem.objects.all()
    if request.GET.get("difficulty"):
        problems = problems.filter(difficulty=request.GET["difficulty"])
    if request.GET.get("topic"):
        problems = problems.filter(topic__icontains=request.GET["topic"])
    solved = set()
    if request.user.is_authenticated:
        solved = set(CodingSubmission.objects.filter(user=request.user, status="accepted")
                     .values_list("problem_id", flat=True))
    out = []
    for p in problems.order_by("difficulty", "title"):
        d = _coding_public(p)
        d["solved"] = p.id in solved
        out.append(d)
    return JsonResponse({"problems": out})


def api_coding_detail(request, problem_id):
    p = get_object_or_404(CodingProblem, id=problem_id)
    d = _coding_public(p)
    d["languages"] = available_languages()
    return JsonResponse({"problem": d})


@require_POST
def api_tests_create(request):
    data = _json_body(request)
    try:
        count = max(1, min(int(data.get("count", 10)), 100))
        duration = max(1, int(data.get("durationMin", 30)))
        marks = max(1, int(data.get("marksPerQuestion", 4)))
        neg = max(0, int(data.get("negativeMarks", 1)))
    except (ValueError, TypeError):
        count, duration, marks, neg = 10, 30, 4, 1
    test = create_test_from_data(
        request.user if request.user.is_authenticated else None,
        mode=data.get("mode", "objective"),
        subject_ids=[str(s) for s in data.get("subjectIds", [])],
        topics=data.get("topics", []), difficulties=data.get("difficulties", []),
        count=count, duration=duration, marks=marks, neg=neg,
        name=data.get("name", "Custom Test"))
    if not test:
        return JsonResponse({"error": "No questions match that configuration."}, status=400)
    return JsonResponse({"testId": test.id})


def api_test_state(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    if test.status == "submitted":
        return JsonResponse({"submitted": True, "testId": test.id})
    items = []
    for it in _visible_test(test):
        items.append({"questionId": it["question"].id,
                      "subject": it["question"].subject.name,
                      "topic": it["question"].topic,
                      "difficulty": it["question"].difficulty,
                      "question": it["question"].question,
                      "options": it["options"],
                      "selected": it["item"].selected_option,
                      "marked": it["item"].marked_for_review})
    return JsonResponse({"submitted": False, "testId": test.id,
                         "name": test.config.name if test.config else "Test",
                         "mode": test.mode,
                         "durationSec": (test.config.duration_min if test.config else 30) * 60,
                         "startedAt": test.started_at.isoformat(),
                         "items": items})


def api_test_result(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    if test.status != "submitted":
        return JsonResponse({"error": "Test not submitted yet."}, status=400)
    return JsonResponse({"score": test.score, "totalMarks": test.total_marks,
                         "correct": test.correct_count, "incorrect": test.incorrect_count,
                         "unattempted": test.unattempted_count,
                         "marksPerQuestion": test.config.marks_per_question if test.config else 4,
                         "negativeMarks": test.config.negative_marks if test.config else 1,
                         "name": test.config.name if test.config else "Test"})


def api_test_review(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    if test.status != "submitted":
        return JsonResponse({"error": "Answers are revealed only after submission."},
                            status=403)
    rows = []
    for item in test.items.select_related("question").prefetch_related("question__options"):
        opts = options_of(item.question)
        order = item.option_order or list(range(len(opts)))
        shown = [opts[i] for i in order]
        correct_shown = [order.index(c) for c in item.question.correct_indices()
                         if c < len(order)]
        rows.append({"question": item.question.question,
                     "subject": item.question.subject.name,
                     "topic": item.question.topic,
                     "options": shown, "selected": item.selected_option,
                     "correct": correct_shown,
                     "isCorrect": (item.selected_option is not None
                                   and order[item.selected_option]
                                   in item.question.correct_indices()),
                     "marked": item.marked_for_review,
                     "explanation": item.question.explanation})
    return JsonResponse({"rows": rows})


@login_required
def api_profile(request):
    profile = get_profile(request.user)
    if request.method == "POST":
        data = _json_body(request)
        profile.semester = data.get("semester") or None
        profile.preferred_subjects = data.get("preferredSubjects", "")
        profile.goals = data.get("goals", "")
        profile.save()
        return JsonResponse({"ok": True})
    return JsonResponse({"user": _json_user(request.user),
                         "semester": profile.semester,
                         "preferredSubjects": profile.preferred_subjects,
                         "goals": profile.goals})


@login_required
def api_contributions(request):
    if request.method == "POST":
        data = _json_body(request)
        subject = get_object_or_404(Subject, id=data.get("subjectId"))
        opts = data.get("options", [])
        try:
            correct = int(data.get("correct", -1))
        except (ValueError, TypeError):
            correct = -1
        if not (data.get("topic") or "").strip() or not (data.get("question") or "").strip() \
                or len(opts) != 4 or any(not (o or "").strip() for o in opts) \
                or correct not in (0, 1, 2, 3) or not (data.get("explanation") or "").strip():
            return JsonResponse({"error": "Topic, question, all 4 options, the correct "
                                            "answer and the explanation are required."},
                                status=400)
        q = Question.objects.create(
            subject=subject, topic=data["topic"].strip(),
            difficulty=data.get("difficulty", "easy"), question=data["question"].strip(),
            explanation=data["explanation"].strip(),
            marks=int(data.get("marks", 1) or 1),
            submitted_by=request.user, status="pending")
        for i, text in enumerate(opts):
            QuestionOption.objects.create(question=q, option_index=i,
                                          option_text=text, is_correct=(i == correct))
        return JsonResponse({"ok": True, "id": q.id})
    qs = Question.objects.filter(submitted_by=request.user) \
        .select_related("subject").prefetch_related("options").order_by("-created_at")
    out = []
    for q in qs:
        d = public_question(q)
        d["correct"] = q.correct_indices()
        d["explanation"] = q.explanation
        d["status"] = q.status
        out.append(d)
    return JsonResponse({"contributions": out})


def api_admin_pending(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "Staff only."}, status=403)
    out = []
    for q in Question.objects.filter(status="pending") \
            .select_related("subject", "submitted_by").prefetch_related("options") \
            .order_by("-created_at"):
        d = public_question(q)
        d["correct"] = q.correct_indices()
        d["explanation"] = q.explanation
        d["submittedBy"] = q.submitted_by.username if q.submitted_by else None
        out.append(d)
    return JsonResponse({"pending": out})


@require_POST
def api_admin_moderate(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "Staff only."}, status=403)
    data = _json_body(request)
    action = data.get("action")
    if action not in ("approve", "reject"):
        return JsonResponse({"error": "action must be approve or reject."}, status=400)
    Question.objects.filter(id=data.get("questionId")).update(
        status="approved" if action == "approve" else "rejected")
    return JsonResponse({"ok": True})
