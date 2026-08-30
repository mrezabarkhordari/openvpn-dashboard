"""
App URL configuration for openvpn_dashboard.
"""
from django.urls import path

from .services.utils import get_openvpn_config
from .views import (
    admin_login,
    admin_logout,
    user_list,
    user_create,
    user_update,
    user_show,
    user_delete,
    account_list,
    account_create,
    account_update,
    account_delete,
    update_account_status,
    account_sessions,
    renew_account_certificate,
    reset_account_usage_view,
    reset_all_usage_view,
    daily_stats_list,
    daily_stats_account,
    server_status,
    save_server_url,
    save_server_port,
)

urlpatterns = [
    # Authentication
    path('login/', admin_login, name='login'),
    path('logout/', admin_logout, name='logout'),

    # Home - Account list
    path('', account_list, name='account_list'),

    # User management
    path('users/', user_list, name='user_list'),
    path('user/create/', user_create, name='user_create'),
    path('user/<int:user_id>/', user_show, name='user_show'),
    path('user/update/<int:user_id>/', user_update, name='user_update'),
    path('users/<int:user_id>/delete/', user_delete, name='user_delete'),

    # Account management
    path('account/create/', account_create, name='account_create'),
    path('account/<int:account_id>/update/', account_update, name='account_update'),
    path('accounts/<int:account_id>/delete/', account_delete, name='account_delete'),
    path('accounts/<str:account_number>/<str:status>/update_status/', update_account_status, name='update_account_status'),
    path('account/<int:account_id>/sessions/', account_sessions, name='account_sessions'),

    # Usage management
    path('account/<int:account_id>/reset-usage/', reset_account_usage_view, name='reset_account_usage'),
    path('accounts/reset-all-usage/', reset_all_usage_view, name='reset_all_usage'),

    # Daily statistics
    path('stats/daily/', daily_stats_list, name='daily_stats_list'),
    path('stats/daily/account/<int:account_id>/', daily_stats_account, name='daily_stats_account'),

    # Certificate management
    path('account/<int:account_id>/renew-certificate/', renew_account_certificate, name='renew_account_certificate'),

    # Downloads
    path('download/<str:account_number>/', get_openvpn_config, name='download_file'),

    # Server status
    path('status/', server_status, name='server_status'),

    # Settings
    path('settings/server-url/', save_server_url, name='save_server_url'),
    path('settings/server-port/', save_server_port, name='save_server_port'),
]
