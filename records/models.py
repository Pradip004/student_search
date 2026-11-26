from django.db import models

class Person(models.Model):
    TYPE = [
        ("student", "Student"),
        ("candidate", "Candidate"),
        ("employee", "Employee"),
    ]
    person_type = models.CharField(max_length=10, choices=TYPE)
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=100, blank=True)
    course = models.CharField(max_length=100, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class SearchHistory(models.Model):
    session_key = models.CharField(max_length=40)
    query_text = models.TextField()
    filters = models.JSONField(default=dict)
    result_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)