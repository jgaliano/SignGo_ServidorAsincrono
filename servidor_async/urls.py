from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path('helloworld/', views.helloworld, name="helloworld"),
    path('tarea_async/', views.tarea_async, name="tarea_async"),
    path('prueba/', views.prueba, name="prueba"),
]
