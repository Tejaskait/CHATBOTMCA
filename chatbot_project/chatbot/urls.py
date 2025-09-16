from django.urls import path
from . import views

urlpatterns = [
    path("", views.chat_view, name="chat_home"),           # renders page (GET) and handles API (POST)
    path("chat/", views.chat_view, name="chat_api"),       # POST endpoint for sending messages
    path("history/", views.history_list, name="history_list"),
    path("history/<str:session_id>/", views.history_detail, name="history_detail"),
        path("history/<str:session_id>/delete/", views.history_delete, name="history_delete"),
]
