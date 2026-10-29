"""Import the question/coding banks from data/seed_*.json into the database.

Idempotent: subjects/topics/questions/problems are matched by natural keys
(name / question text / problem title) and skipped when already present.
Also creates the demo admin (admin@cseprep.local / admin123) on first run.

Usage: python manage.py seed_data
"""
import json
import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from prep.models import (CodingProblem, Question, QuestionOption, Subject, Topic)


def load(name):
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", name)
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)



# Repairs for questions that referenced a passage they did not include
# ("Using the same cloze passage..." with no passage shown). Applied in
# place at the start of seeding so existing databases are fixed without
# creating duplicates; options and attempts keep pointing at the row.
QUESTION_TEXT_FIXES = {
    'Using the same cloze passage, choose the correct word for blank (2).':
        "Cloze passage: 'Regular exercise (1) ___ essential for good health. It (2) ___ the heart, improves mood, and (3) ___ the risk of many diseases.' Choose the correct word for blank (2).",
    'Using the same cloze passage, choose the correct word for blank (3).':
        "Cloze passage: 'Regular exercise (1) ___ essential for good health. It (2) ___ the heart, improves mood, and (3) ___ the risk of many diseases.' Choose the correct word for blank (3).",
    'According to the same passage, what does Meera Joshi compare the library to?':
        "Read the passage: 'The city library on MG Road has quietly become the busiest public space in town. What began in 1985 as a single reading room with two thousand books now holds over two lakh volumes, a children's wing, and a digital archive that students use free of charge. Librarian Meera Joshi credits the turnaround to one decision: opening the doors at 7 a.m. so that students preparing for competitive examinations could study before college. A library is not a warehouse of books, she says. It is a workshop where a town thinks. The library now runs weekend workshops on writing, coding, and public speaking, and its membership has tripled in five years.' According to the passage, what does Meera Joshi compare the library to?",
    "According to the same passage, what decision is credited with the library's turnaround?":
        "Read the passage: 'The city library on MG Road has quietly become the busiest public space in town. What began in 1985 as a single reading room with two thousand books now holds over two lakh volumes, a children's wing, and a digital archive that students use free of charge. Librarian Meera Joshi credits the turnaround to one decision: opening the doors at 7 a.m. so that students preparing for competitive examinations could study before college. A library is not a warehouse of books, she says. It is a workshop where a town thinks. The library now runs weekend workshops on writing, coding, and public speaking, and its membership has tripled in five years.' According to the passage, what decision is credited with the library's turnaround?",
    'What is the main idea of the same passage?':
        "Read the passage: 'The city library on MG Road has quietly become the busiest public space in town. What began in 1985 as a single reading room with two thousand books now holds over two lakh volumes, a children's wing, and a digital archive that students use free of charge. Librarian Meera Joshi credits the turnaround to one decision: opening the doors at 7 a.m. so that students preparing for competitive examinations could study before college. A library is not a warehouse of books, she says. It is a workshop where a town thinks. The library now runs weekend workshops on writing, coding, and public speaking, and its membership has tripled in five years.' What is the main idea of the passage?",
    "In the same library passage, why does the author quote the line 'It is a workshop where a town thinks'?":
        "Read the passage: 'The city library on MG Road has quietly become the busiest public space in town. What began in 1985 as a single reading room with two thousand books now holds over two lakh volumes, a children's wing, and a digital archive that students use free of charge. Librarian Meera Joshi credits the turnaround to one decision: opening the doors at 7 a.m. so that students preparing for competitive examinations could study before college. A library is not a warehouse of books, she says. It is a workshop where a town thinks. The library now runs weekend workshops on writing, coding, and public speaking, and its membership has tripled in five years.' Why does the author quote the line 'It is a workshop where a town thinks'?",
}


class Command(BaseCommand):
    help = "Import seed question banks and coding problems from data/*.json"

    def handle(self, *args, **options):
        for old, new in QUESTION_TEXT_FIXES.items():
            Question.objects.filter(question=old).update(question=new)
        n_q = n_p = 0
        for fname in ("seed_apt.json", "seed_tech.json"):
            data = load(fname)
            if data is None:
                self.stdout.write(f"skip {fname} (not present)")
                continue
            subjects = {}
            for s in data.get("subjects", []):
                obj, _ = Subject.objects.update_or_create(
                    name=s["name"],
                    defaults={"category": s.get("category", "Technical MCQs"),
                              "code": s.get("code", ""),
                              "semester": s.get("semester")})
                subjects[s["id"]] = obj
            for t in data.get("topics", []):
                subj = subjects.get(t["subjectId"])
                if subj:
                    Topic.objects.update_or_create(
                        subject=subj, name=t["name"],
                        defaults={"notes": t.get("notes", "")})
            for q in data.get("questions", []):
                subj = subjects.get(q["subjectId"])
                if not subj:
                    continue
                obj, created = Question.objects.get_or_create(
                    subject=subj, question=q["question"],
                    defaults={"topic": q.get("topic", ""), "difficulty": q.get("difficulty", "easy"),
                              "type": q.get("type", "single"),
                              "explanation": q.get("explanation", ""),
                              "marks": q.get("marks", 1), "time_sec": q.get("timeSec", 60)})
                if created:
                    for i, text in enumerate(q["options"]):
                        QuestionOption.objects.create(
                            question=obj, option_index=i, option_text=text,
                            is_correct=(i == q["answer"]))
                    n_q += 1
        data = load("seed_coding.json")
        if data is not None:
            for p in data.get("problems", []):
                _, created = CodingProblem.objects.update_or_create(
                    title=p["title"],
                    defaults={"difficulty": p.get("difficulty", "easy"),
                              "topic": p.get("topic", ""),
                              "description": p.get("description", ""),
                              "input_format": p.get("inputFormat", ""),
                              "output_format": p.get("outputFormat", ""),
                              "constraints": p.get("constraints", ""),
                              "examples_json": p.get("examples", []),
                              "tests_json": p.get("tests", []),
                              "starter_code_json": p.get("starterCode", {}),
                              "reference_solution_json": p.get("referenceSolution", {}),
                              "time_complexity": p.get("timeComplexity", ""),
                              "space_complexity": p.get("spaceComplexity", ""),
                              "hints_json": p.get("hints", [])})
                n_p += 1 if created else 0
        if not User.objects.filter(username="admin@cseprep.local").exists():
            User.objects.create_superuser(username="admin@cseprep.local",
                                          email="admin@cseprep.local",
                                          password="admin123",
                                          first_name="Admin")
            self.stdout.write("created admin user: admin@cseprep.local / admin123 "
                              "(change this password after first login)")
        self.stdout.write(self.style.SUCCESS(
            f"seed complete: {n_q} new questions, {n_p} new coding problems "
            f"(totals: {Question.objects.count()} questions, "
            f"{CodingProblem.objects.count()} problems)"))
