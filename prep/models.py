"""Data model for CSE Prep Master.

Mirrors the spec's table list: users (Django's built-in User), profiles,
subjects, topics, questions, question_options, test_configurations, tests,
test_questions, attempts, attempt_answers, bookmarks, coding_problems,
coding_submissions, study_sessions.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    semester = models.PositiveIntegerField(null=True, blank=True)
    preferred_subjects = models.CharField(max_length=500, blank=True,
                                          help_text="Comma-separated subject ids")
    goals = models.TextField(blank=True)

    def __str__(self):
        return f"Profile({self.user.username})"


class Subject(models.Model):
    CATEGORIES = [
        ("Quantitative Aptitude", "Quantitative Aptitude"),
        ("Logical Reasoning", "Logical Reasoning"),
        ("Verbal Ability", "Verbal Ability"),
        ("Technical MCQs", "Technical MCQs"),
    ]
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=50, choices=CATEGORIES)
    code = models.CharField(max_length=50, blank=True)
    semester = models.PositiveIntegerField(null=True, blank=True)
    is_custom = models.BooleanField(default=False)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class Topic(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="topics")
    name = models.CharField(max_length=200)
    notes = models.TextField(blank=True, help_text="Formula revision notes / key rules")

    class Meta:
        unique_together = [("subject", "name")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.subject.name} / {self.name}"


DIFFICULTIES = [("easy", "Easy"), ("medium", "Medium"), ("hard", "Hard")]


class Question(models.Model):
    TYPES = [
        ("single", "Single-answer MCQ"),
        ("multi", "Multiple-select MCQ"),
        ("numerical", "Numerical MCQ"),
        ("truefalse", "True / False"),
    ]
    STATUS = [
        ("approved", "Approved"),
        ("pending", "Pending review"),
        ("rejected", "Rejected"),
    ]
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="questions")
    topic = models.CharField(max_length=200)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTIES, default="easy")
    type = models.CharField(max_length=20, choices=TYPES, default="single")
    question = models.TextField()
    explanation = models.TextField(blank=True)
    marks = models.PositiveIntegerField(default=1)
    time_sec = models.PositiveIntegerField(default=60)
    is_ai_generated = models.BooleanField(default=False)
    # user contributions: who submitted it and its moderation state.
    # Seed/bank questions are approved; only approved questions enter
    # practice and tests.
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="contributed_questions")
    status = models.CharField(max_length=20, choices=STATUS, default="approved")
    created_at = models.DateTimeField(auto_now_add=True)

    def correct_indices(self):
        return list(self.options.filter(is_correct=True)
                    .order_by("option_index").values_list("option_index", flat=True))

    def __str__(self):
        return self.question[:80]


class QuestionOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    option_index = models.PositiveIntegerField()
    option_text = models.CharField(max_length=1000)
    is_correct = models.BooleanField(default=False)

    class Meta:
        unique_together = [("question", "option_index")]
        ordering = ["option_index"]


class TestConfiguration(models.Model):
    MODES = [
        ("practice", "Practice"), ("objective", "Objective Test"),
        ("subject", "Subject-Wise"), ("topic", "Topic-Wise"),
        ("mixed", "Mixed"), ("mock", "Full-Length Mock"), ("custom", "Custom"),
    ]
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=200, default="Custom Test")
    mode = models.CharField(max_length=20, choices=MODES, default="objective")
    subject_ids = models.CharField(max_length=500, blank=True)
    topic_names = models.CharField(max_length=1000, blank=True)
    difficulties = models.CharField(max_length=100, blank=True)
    question_count = models.PositiveIntegerField(default=10)
    duration_min = models.PositiveIntegerField(default=30)
    marks_per_question = models.PositiveIntegerField(default=4)
    negative_marks = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)


class Test(models.Model):
    STATUS = [("in_progress", "In Progress"), ("submitted", "Submitted")]
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    config = models.ForeignKey(TestConfiguration, on_delete=models.SET_NULL, null=True, blank=True)
    mode = models.CharField(max_length=20, default="objective")
    status = models.CharField(max_length=20, choices=STATUS, default="in_progress")
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    total_marks = models.IntegerField(default=0)
    score = models.IntegerField(default=0)
    correct_count = models.IntegerField(default=0)
    incorrect_count = models.IntegerField(default=0)
    unattempted_count = models.IntegerField(default=0)

    def __str__(self):
        return f"Test #{self.id} ({self.mode}, {self.status})"


class TestQuestion(models.Model):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="items")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()
    selected_option = models.IntegerField(null=True, blank=True)
    marked_for_review = models.BooleanField(default=False)
    # permutation of the question's option indices as shown to the student
    option_order = models.JSONField(default=list)

    class Meta:
        unique_together = [("test", "position")]
        ordering = ["position"]


class Attempt(models.Model):
    """One practice-mode attempt at one question."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="attempts")
    selected_option = models.IntegerField(null=True, blank=True)
    is_correct = models.BooleanField()
    attempted_at = models.DateTimeField(auto_now_add=True)


class AttemptAnswer(models.Model):
    """Detail rows for attempts (kept for the spec's table list)."""
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_option = models.IntegerField(null=True, blank=True)
    is_correct = models.BooleanField()


class Bookmark(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookmarks")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="bookmarks")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "question")]


class CodingProblem(models.Model):
    title = models.CharField(max_length=300)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTIES, default="easy")
    topic = models.CharField(max_length=200)
    description = models.TextField()
    input_format = models.TextField(blank=True)
    output_format = models.TextField(blank=True)
    constraints = models.TextField(blank=True)
    examples_json = models.JSONField(default=list)
    tests_json = models.JSONField(default=list)  # includes hidden tests: NEVER sent to clients
    starter_code_json = models.JSONField(default=dict)
    reference_solution_json = models.JSONField(default=dict)
    time_complexity = models.CharField(max_length=100, blank=True)
    space_complexity = models.CharField(max_length=100, blank=True)
    hints_json = models.JSONField(default=list)

    def visible_tests(self):
        return [t for t in self.tests_json if not t.get("hidden")]

    def __str__(self):
        return self.title


class CodingSubmission(models.Model):
    STATUS = [("accepted", "Accepted"), ("partial", "Partial"), ("failed", "Failed"),
              ("error", "Error")]
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    problem = models.ForeignKey(CodingProblem, on_delete=models.CASCADE,
                                related_name="submissions")
    language = models.CharField(max_length=20)
    code = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS)
    passed_count = models.PositiveIntegerField(default=0)
    total_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class StudySession(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    # NOTE: plain default, NOT auto_now_add — the study timer posts the real
    # start time, and auto_now_add would silently overwrite it with receipt
    # time (making every saved session ~0 minutes long).
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    questions_attempted = models.PositiveIntegerField(default=0)
