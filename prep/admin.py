from django.contrib import admin
from .models import (Subject, Topic, Question, QuestionOption, TestConfiguration,
                     Test, TestQuestion, Attempt, Bookmark, CodingProblem,
                     CodingSubmission, StudySession)


class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 4


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "code", "semester")
    list_filter = ("category", "semester")


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("name", "subject")
    list_filter = ("subject",)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("question", "subject", "topic", "difficulty", "type")
    list_filter = ("subject", "difficulty", "type")
    search_fields = ("question", "topic")
    inlines = [QuestionOptionInline]


@admin.register(CodingProblem)
class CodingProblemAdmin(admin.ModelAdmin):
    list_display = ("title", "difficulty", "topic")
    list_filter = ("difficulty",)


admin.site.register(TestConfiguration)
admin.site.register(Test)
admin.site.register(TestQuestion)
admin.site.register(Attempt)
admin.site.register(Bookmark)
admin.site.register(CodingSubmission)
admin.site.register(StudySession)
