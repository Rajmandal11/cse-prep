"""Automated tests for the core engines: scoring, practice answers,
test flow, and code execution. Run: python manage.py test prep
"""
import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from prep.models import (CodingProblem, Question, QuestionOption, Subject,
                         Test, TestConfiguration, TestQuestion)
from prep.runner import run_code
from prep.templatetags.explain_tags import format_explanation, format_question
from prep.views import score_test


def make_question(subject, text="What is 2 + 2?", options=("3", "4", "5", "6"),
                  answer=1, topic="Arithmetic"):
    q = Question.objects.create(subject=subject, topic=topic, difficulty="easy",
                                question=text, explanation="2 + 2 = 4.")
    for i, opt in enumerate(options):
        QuestionOption.objects.create(question=q, option_index=i,
                                      option_text=opt, is_correct=(i == answer))
    return q


class ScoringTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Test Subject",
                                              category="Technical MCQs")
        self.q1 = make_question(self.subject, "Q1")
        self.q2 = make_question(self.subject, "Q2", answer=0)

    def test_scoring_marks_and_negative(self):
        cfg = TestConfiguration.objects.create(marks_per_question=4, negative_marks=1)
        test = Test.objects.create(config=cfg, mode="objective", total_marks=8)
        TestQuestion.objects.create(test=test, question=self.q1, position=1,
                                    selected_option=1, option_order=[0, 1, 2, 3])
        TestQuestion.objects.create(test=test, question=self.q2, position=2,
                                    selected_option=1, option_order=[0, 1, 2, 3])
        TestQuestion.objects.create(test=test, question=self.q1, position=3,
                                    selected_option=None, option_order=[0, 1, 2, 3])
        score, correct, incorrect, unattempted = score_test(test)
        self.assertEqual((correct, incorrect, unattempted), (1, 1, 1))
        self.assertEqual(score, 4 - 1)  # +4 correct, -1 wrong, 0 unattempted

    def test_shuffled_option_order_scores_correctly(self):
        cfg = TestConfiguration.objects.create()
        test = Test.objects.create(config=cfg, mode="objective")
        # options shown shuffled: original answer (index 1) appears at shown position 0
        TestQuestion.objects.create(test=test, question=self.q1, position=1,
                                    selected_option=0, option_order=[1, 0, 2, 3])
        score, correct, incorrect, unattempted = score_test(test)
        self.assertEqual(correct, 1)
        self.assertEqual(score, 4)


class FlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="student@test.local",
                                             email="student@test.local",
                                             password="pass1234")
        self.subject = Subject.objects.create(name="Aptitude",
                                              category="Quantitative Aptitude")
        self.q = make_question(self.subject)

    def test_practice_answer_api(self):
        self.client.force_login(self.user)
        resp = self.client.post("/api/practice/answer/",
                                json.dumps({"question_id": self.q.id, "selected": 1}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["correct"])
        self.assertIn("2 + 2 = 4", data["explanation"])

    def test_test_flow_end_to_end(self):
        self.client.force_login(self.user)
        resp = self.client.post("/tests/new/", {
            "mode": "objective", "count": 1, "duration": 30,
            "marks": 4, "negative": 1, "name": "T1"})
        self.assertEqual(resp.status_code, 302)
        test = Test.objects.latest("id")
        item = test.items.first()
        # the correct original option index is 1; find where it sits in the
        # test's shuffled display order before answering
        shown_correct = item.option_order.index(1)
        resp = self.client.post(f"/api/tests/{test.id}/answer/",
                                json.dumps({"question_id": item.question_id,
                                            "selected": shown_correct, "marked": False}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(f"/api/tests/{test.id}/submit/",
                                content_type="application/json")
        self.assertEqual(resp.json()["score"], 4)
        resp = self.client.get(f"/tests/{test.id}/review/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("2 + 2 = 4", resp.content.decode())

    def test_review_blocked_before_submit(self):
        self.client.force_login(self.user)
        test = Test.objects.create(config=TestConfiguration.objects.create(), mode="objective")
        resp = self.client.get(f"/tests/{test.id}/review/")
        self.assertEqual(resp.status_code, 302)  # redirected back to player


class CodingRunnerTests(TestCase):
    def test_python_run_and_error(self):
        r = run_code("python", "print(2 + 3)", "")
        self.assertEqual(r["output"].strip(), "5")
        r = run_code("python", "print(1/0)", "")
        self.assertIn("ZeroDivisionError", r["error"])

    def test_coding_submit_hides_hidden_tests(self):
        problem = CodingProblem.objects.create(
            title="Add", difficulty="easy", topic="Math",
            description="Add two numbers.", tests_json=[
                {"input": "2 3", "output": "5", "hidden": False},
                {"input": "10 20", "output": "30", "hidden": True}])
        self.client.force_login(User.objects.create_user(username="coder@test.local",
                                                         password="pass1234"))
        code = "import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)"
        resp = self.client.post(f"/api/coding/{problem.id}/submit/",
                                json.dumps({"code": code, "language": "python"}),
                                content_type="application/json")
        data = resp.json()
        self.assertEqual(data["passed"], 2)
        self.assertEqual(data["status"], "accepted")
        hidden = [r for r in data["results"] if not r["visible"]][0]
        self.assertNotIn("output", hidden)
        self.assertNotIn("expected", hidden)


class ContributionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="contrib@test.local",
                                             password="pass1234")
        self.staff = User.objects.create_user(username="staff@test.local",
                                              password="pass1234", is_staff=True)
        self.subject = Subject.objects.create(name="Contrib Subject",
                                              category="Technical MCQs")

    def _post_question(self):
        return self.client.post("/contribute/", {
            "subject": self.subject.id, "topic": "Arrays", "difficulty": "easy",
            "question": "What is 1 + 1?", "opt0": "1", "opt1": "2",
            "opt2": "3", "opt3": "4", "correct": "1",
            "explanation": "1 + 1 = 2.", "marks": "1"})

    def test_contribution_starts_pending_and_stays_out_of_bank(self):
        self.client.force_login(self.user)
        resp = self._post_question()
        self.assertEqual(resp.status_code, 302)
        q = Question.objects.get(question="What is 1 + 1?")
        self.assertEqual(q.status, "pending")
        self.assertEqual(q.submitted_by, self.user)
        # pending questions must not appear in practice picks or public API
        from prep.views import pick_questions
        self.assertEqual(pick_questions(count=10), [])
        resp = self.client.get("/api/questions/?limit=10")
        self.assertEqual(resp.json()["questions"], [])

    def test_staff_approval_makes_it_live(self):
        self.client.force_login(self.user)
        self._post_question()
        q = Question.objects.get(question="What is 1 + 1?")
        self.client.force_login(self.staff)
        resp = self.client.post("/manage/", {"action": "approve", "question_id": q.id})
        self.assertEqual(resp.status_code, 302)
        q.refresh_from_db()
        self.assertEqual(q.status, "approved")
        from prep.views import pick_questions
        self.assertEqual(len(pick_questions(count=10)), 1)

    def test_contribution_requires_all_fields(self):
        self.client.force_login(self.user)
        resp = self.client.post("/contribute/", {
            "subject": self.subject.id, "topic": "Arrays",
            "question": "Incomplete?", "opt0": "a", "opt1": "",
            "opt2": "c", "opt3": "d", "correct": "0", "explanation": ""})
        self.assertEqual(resp.status_code, 200)  # re-rendered with error
        self.assertFalse(Question.objects.filter(question="Incomplete?").exists())


class NextApiTests(TestCase):
    """JSON API consumed by the React/Next.js frontend."""
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="next@test.local",
                                             email="next@test.local",
                                             password="pass1234", first_name="Next")
        self.subject = Subject.objects.create(name="Next Subject",
                                              category="Technical MCQs")
        self.q = make_question(self.subject)

    def test_auth_roundtrip(self):
        resp = self.client.post("/api/auth/register/",
                                json.dumps({"name": "New", "email": "new@test.local",
                                            "password": "pass1234"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user"]["email"], "new@test.local")
        resp = self.client.get("/api/auth/me/")
        self.assertTrue(resp.json()["authenticated"])
        resp = self.client.post("/api/auth/logout/", content_type="application/json")
        self.assertEqual(resp.json()["ok"], True)
        resp = self.client.get("/api/auth/me/")
        self.assertFalse(resp.json()["authenticated"])
        resp = self.client.post("/api/auth/login/",
                                json.dumps({"email": "next@test.local",
                                            "password": "pass1234"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_and_test_state_hide_answers(self):
        self.client.force_login(self.user)
        resp = self.client.get("/api/dashboard/")
        data = resp.json()
        for key in ("totals", "daily", "week", "subjectLabels", "tasks", "recent"):
            self.assertIn(key, data)
        resp = self.client.post("/api/tests/",
                                json.dumps({"mode": "objective", "count": 1,
                                            "durationMin": 30, "marksPerQuestion": 4,
                                            "negativeMarks": 1, "name": "API Test"}),
                                content_type="application/json")
        test_id = resp.json()["testId"]
        resp = self.client.get(f"/api/tests/{test_id}/state/")
        state = resp.json()
        self.assertFalse(state["submitted"])
        self.assertEqual(len(state["items"]), 1)
        self.assertNotIn("correct", state["items"][0])
        self.assertNotIn("explanation", state["items"][0])
        resp = self.client.get(f"/api/tests/{test_id}/review/")
        self.assertEqual(resp.status_code, 403)  # not submitted yet

    def test_coding_list_hides_hidden_tests(self):
        problem = CodingProblem.objects.create(
            title="Hidden Check", difficulty="easy", topic="Math",
            description="d", tests_json=[
                {"input": "1", "output": "1", "hidden": False},
                {"input": "2", "output": "2", "hidden": True}])
        resp = self.client.get("/api/coding/")
        item = [p for p in resp.json()["problems"] if p["id"] == problem.id][0]
        self.assertEqual(len(item["visibleTests"]), 1)
        self.assertNotIn("tests_json", item)


class StudySessionTests(TestCase):
    """Regression test: the timer posts real start/end times and they must
    be stored as posted (auto_now_add used to overwrite started_at)."""
    def test_posted_times_are_stored_and_counted(self):
        user = User.objects.create_user(username="timer@test.local", password="pass1234")
        self.client.force_login(user)
        resp = self.client.post("/api/study-sessions/",
                                json.dumps({"startedAt": "2026-10-26T10:00:00Z",
                                            "endedAt": "2026-10-26T11:30:00Z"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        from prep.models import StudySession
        s = StudySession.objects.get(user=user)
        self.assertEqual(s.started_at.hour, 10)
        self.assertEqual(s.ended_at.hour, 11)
        # dashboard counts the 90 minutes only if the session ends this week;
        # use a session ending now to check the aggregation path
        from django.utils import timezone
        now = timezone.now()
        StudySession.objects.create(user=user, started_at=now - timezone.timedelta(minutes=45),
                                    ended_at=now)
        resp = self.client.get("/api/dashboard/")
        self.assertGreaterEqual(resp.json()["studyMinutesWeek"], 45)


class DashboardV22FieldsTests(TestCase):
    def test_prev_week_and_monthly_present(self):
        user = User.objects.create_user(username="v22@test.local", password="pass1234")
        self.client.force_login(user)
        resp = self.client.get("/api/dashboard/")
        d = resp.json()
        self.assertIn("prevWeek", d)
        self.assertIn("monthly", d)
        self.assertIn("weekCorrect", d)
        self.assertEqual(len(d["monthly"]), 6)
        self.assertEqual(d["prevWeek"]["attempted"], 0)


class ExplainFormatterTests(TestCase):
    SAMPLE = ("Step 1: Let the numbers be 5x and 7x. "
              "Step 2: After increasing each by 12: (5x + 12)/(7x + 12) = 3/4. "
              "Step 3: Cross-multiply to get x = 12. "
              "Correct answer: Option B - 144.")

    def test_steps_become_rows_with_chips(self):
        out = str(format_explanation(self.SAMPLE))
        self.assertEqual(out.count('class="sol-step"'), 3)
        self.assertIn("Step 1", out)
        self.assertIn("Step 3", out)

    def test_answer_becomes_highlight_bar(self):
        out = str(format_explanation(self.SAMPLE))
        self.assertIn('class="sol-answer"', out)
        self.assertIn("Option B - 144", out)
        # the answer sentence is pulled out of the last step's body
        self.assertNotIn("Correct answer: Option B", out.split('sol-answer')[0])

    def test_fractions_render_stacked(self):
        out = str(format_explanation(self.SAMPLE))
        self.assertIn('class="frac-num">5x + 12<', out)
        self.assertIn('class="frac-den">7x + 12<', out)

    def test_html_is_escaped(self):
        out = str(format_explanation("<script>alert(1)</script>"))
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_empty_explanation_placeholder(self):
        self.assertIn("No explanation available", str(format_explanation("")))
        self.assertIn("No explanation available", str(format_explanation(None)))


class SeedPassageIntegrityTests(TestCase):
    def test_passage_questions_embed_their_passage(self):
        # Regression: cloze / reading-comprehension questions once said
        # "using the same passage" without showing it, which makes them
        # unanswerable when a practice set is shuffled.
        import os
        import re

        base = os.path.join(os.path.dirname(__file__), "..", "data")
        checked = 0
        for name in ("seed_apt.json", "seed_tech.json"):
            with open(os.path.join(base, name)) as f:
                data = json.load(f)
            for q in data["questions"]:
                text = q["question"]
                if "passage" not in text.lower():
                    continue
                checked += 1
                m = re.search(r"'(.{40,}?)'", text, re.DOTALL)
                self.assertIsNotNone(m, text[:80])
                self.assertGreaterEqual(len(m.group(1)), 80, text[:80])
        self.assertGreater(checked, 0)


class SeedSelfContainedTests(TestCase):
    # Questions must carry everything they need: a passage, a data table,
    # a code snippet, a route. Phrases that point at content outside the
    # question ("as shown", "in the figure", "the same passage") mean the
    # question is unanswerable on its own and must not enter the bank.
    DANGLING = (
        "as shown", "shown below", "shown above", "in the figure",
        "the figure below", "following figure", "following diagram",
        "following image", "figure below", "diagram below", "image below",
        "refer to the", "same passage", "same cloze", "above diagram",
        "above figure", "given figure", "given diagram", "this diagram",
        "the diagram shows", "figure shows", "see the image",
        "in the image", "in the picture",
    )

    def _texts(self):
        import os

        base = os.path.join(os.path.dirname(__file__), "..", "data")
        texts = []
        for name in ("seed_apt.json", "seed_tech.json"):
            with open(os.path.join(base, name)) as f:
                texts += [q["question"] for q in json.load(f)["questions"]]
        with open(os.path.join(base, "seed_coding.json")) as f:
            texts += [p.get("description", "")
                      for p in json.load(f)["problems"]]
        return texts

    def test_no_question_points_at_missing_content(self):
        texts = self._texts()
        self.assertEqual(len(texts), 172)  # 142 MCQs + 30 coding problems
        for text in texts:
            low = text.lower()
            for phrase in self.DANGLING:
                self.assertNotIn(phrase, low,
                                 "%r dangles in: %s" % (phrase, text[:80]))


class QuestionFormatterTests(TestCase):
    def test_code_goes_into_panel(self):
        out = str(format_question(
            "What is the output order of this code?\n"
            "console.log('A'); setTimeout(() => console.log('B'), 0);"))
        self.assertIn('<p class="q-text-p">What is the output order of this code?</p>', out)
        self.assertIn('<pre class="q-code">', out)
        self.assertIn("console.log(&#x27;A&#x27;)", out)

    def test_sql_label_and_trailing_question(self):
        out = str(format_question(
            "Employees table: (1, Anita, 40000).\n"
            "Query: SELECT name FROM Employees WHERE salary > 50000;\n"
            "What is the output?"))
        self.assertIn("Query:</p>", out)
        self.assertIn('<pre class="q-code">SELECT name FROM Employees', out)
        self.assertTrue(out.endswith('<p class="q-text-p">What is the output?</p>'))

    def test_indentation_preserved(self):
        out = str(format_question(
            "What is the output of this pseudocode?\n"
            "sum = 0\nfor i = 1 to 5:\n    sum = sum + i\nprint sum"))
        self.assertIn("for i = 1 to 5:\n    sum = sum + i", out)

    def test_trailing_prose_after_code(self):
        out = str(format_question(
            "This code is meant to compute the sum of 1..n:\n"
            "sum = 0\nfor i = 1; i < n; i++:\n    sum = sum + i\n"
            "What kind of bug is this?"))
        self.assertEqual(out.count('<pre class="q-code">'), 1)
        self.assertTrue(out.endswith("What kind of bug is this?</p>"))

    def test_html_is_escaped(self):
        out = str(format_question('What color is <p id="main">Hello</p>?'))
        self.assertNotIn('<p id="main">', out)
        self.assertIn("&lt;p id=&quot;main&quot;&gt;", out)

    def test_prose_mentioning_code_stays_prose(self):
        out = str(format_question(
            "What is the output of console.log(typeof null) in JavaScript?"))
        self.assertNotIn("<pre", out)
        out = str(format_question("What does document.querySelectorAll() return?"))
        self.assertNotIn("<pre", out)

    def test_plain_question_single_paragraph(self):
        out = str(format_question("A student scores 72 marks out of 90. "
                                  "What is the student's percentage?"))
        self.assertTrue(out.startswith('<p class="q-text-p">'))
        self.assertNotIn("<pre", out)
