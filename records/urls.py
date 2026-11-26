
from django.urls import path
from . import views

urlpatterns = [
    # Main search page
    path('', views.search, name='search'),
    path('search/upload/', views.search_upload, name='search_upload'),

    # Search history page
    path('history/', views.history_list, name='history'),

    # Add and remove student/candidate records
    path('people/add/', views.add_person, name='add_person'),
    path('people/import/', views.import_people, name='import_people'),
    path('people/remove/', views.remove_person, name='remove_person'),
    path(
        'people/<int:person_id>/delete/',
        views.delete_person,
        name='delete_person'
    ),

    # Export search results
    path(
        'export/<int:history_id>/<str:fmt>/',
        views.export,
        name='export'
    ),
]
