from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path

from chores import views, webhooks

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('create/', views.create_household, name='create_household'),
    path('join/', views.join_household, name='join_household'),
    path('household/code/', views.household_code, name='household_code'),
    path('chores/', views.chore_list, name='chore_list'),
    path('chores/new/', views.chore_create, name='chore_create'),
    path('chores/<int:chore_id>/edit/', views.chore_edit, name='chore_edit'),
    path('chores/<int:chore_id>/swap/', views.request_swap_view, name='request_swap'),
    path('chores/<int:chore_id>/complete/', views.complete_chore_view, name='complete_chore'),
    path('swaps/<int:swap_id>/accept/', views.respond_swap_view, {'decision': 'accept'}, name='accept_swap'),
    path('swaps/<int:swap_id>/decline/', views.respond_swap_view, {'decision': 'decline'}, name='decline_swap'),
    path('supplies/', views.supplies_list, name='supplies_list'),
    path('supplies/<int:supply_id>/toggle/', views.toggle_supply, name='toggle_supply'),
    path('history/', views.history_list, name='history_list'),
    path('settings/', views.settings_view, name='settings'),
    path('help/', views.help_page, name='help'),
    path('push/subscribe/', views.push_subscribe, name='push_subscribe'),
    path('manifest.webmanifest', views.manifest, name='manifest'),
    path('icons/icon-<int:size>.png', views.app_icon, name='app_icon'),
    path('service-worker.js', views.service_worker, name='service_worker'),
    path('offline/', views.offline, name='offline'),
    path('webhooks/whatsapp/', webhooks.whatsapp_webhook, name='whatsapp_webhook'),
    path('ai/prompt/', views.ai_prompt, name='ai_prompt'),
    path('ai/confirm/', views.ai_confirm, name='ai_confirm'),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
