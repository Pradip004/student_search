from django.contrib import admin
from .models import Person, SearchHistory

admin.site.register(Person)
admin.site.register(SearchHistory)