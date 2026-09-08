from django.contrib import admin
from django.urls import path

from chores import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('create/', views.create_household, name='create_household'),
    path('join/', views.join_household, name='join_household'),
    path('household/code/', views.household_code, name='household_code'),
    path('chores/', views.chore_list, name='chore_list'),
    path('chores/<int:chore_id>/complete/', views.complete_chore_view, name='complete_chore'),
]
