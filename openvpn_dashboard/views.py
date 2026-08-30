from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.db.models import F
from .forms import UserCreationForm, AccountCreationForm, AccountStatusForm
from .models import Account, User, ConnectionSession, Setting, DailyUsageStats, ServerDailyStats
from .services.utils import (
    create_openvpn_config,
    enable_openvpn_user,
    disable_openvpn_user,
    delete_openvpn_user,
    renew_openvpn_user,
    get_user_data_for_template,
    get_connected_clients,
    get_server_status,
    is_client_connected,
)
from .services.usage_collector import get_usage_stats, reset_account_usage, reset_all_usage
import logging

logger = logging.getLogger(__name__)


def admin_login(request):
    """Admin login view."""
    if request.user.is_authenticated:
        return redirect('account_list')
    
    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None and user.is_staff:
            login(request, user)
            next_url = request.GET.get('next', 'account_list')
            return redirect(next_url)
        else:
            error = 'Invalid credentials or insufficient permissions.'
    
    return render(request, 'openvpn_dashboard/login.html', {'error': error})


def admin_logout(request):
    """Admin logout view."""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('login')


@login_required
def user_list(request):
    """Display list of all users with their account information."""
    users = User.objects.all()
    
    # Add account information for each user (for delete confirmation)
    for user in users:
        user.accounts_list = list(Account.objects.filter(user=user).values_list('account_number', flat=True))
        user.account_count = len(user.accounts_list)
    
    return render(request, 'openvpn_dashboard/user_list.html', {'users': users})


@login_required
def user_create(request):
    """Create a new user."""
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'User created successfully.')
            return redirect('user_list')
    else:
        form = UserCreationForm()
    return render(request, 'openvpn_dashboard/user_create.html', {'form': form})


@login_required
def user_update(request, user_id):
    """Update an existing user and show their accounts."""
    user = get_object_or_404(User, id=user_id)
    
    # Get all accounts for this user
    accounts = Account.objects.filter(user=user).order_by('-created_at')
    
    # Get connected clients for status indication
    connected_clients = {c.common_name for c in get_connected_clients()}
    
    # Add connection status to each account
    for account in accounts:
        account.is_connected = account.account_number in connected_clients
    
    if request.method == 'POST':
        form = UserCreationForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, 'User updated successfully.')
            return redirect('user_list')
    else:
        form = UserCreationForm(instance=user)
    
    return render(request, 'openvpn_dashboard/user_update.html', {
        'form': form,
        'user': user,
        'accounts': accounts,
    })


@login_required
def user_show(request, user_id):
    """Display user details."""
    user = get_object_or_404(User, id=user_id)
    return render(request, 'openvpn_dashboard/user_show.html', {'user': user})


@login_required
def user_delete(request, user_id):
    """Delete a user and all their accounts."""
    user = get_object_or_404(User, pk=user_id)
    
    # Get all accounts for this user
    accounts = Account.objects.filter(user=user)

    if request.method == 'POST':
        # Revoke all OpenVPN certificates for user's accounts before deletion
        revoke_errors = []
        for account in accounts:
            try:
                delete_openvpn_user(account.account_number)
                logger.info(f"Revoked OpenVPN certificate for account '{account.account_number}'")
            except Exception as e:
                logger.error(f"Failed to revoke OpenVPN user '{account.account_number}': {e}")
                revoke_errors.append(f"{account.account_number}: {e}")
        
        # Delete user (CASCADE will delete all accounts from database)
        user.delete()
        
        if revoke_errors:
            messages.warning(
                request,
                f'User deleted but some OpenVPN revocations failed: {", ".join(revoke_errors)}'
            )
        else:
            messages.success(request, 'User and all accounts deleted successfully.')
        
        return redirect('user_list')

    return render(request, 'openvpn_dashboard/user_delete.html', {'user': user, 'accounts': accounts})


@login_required
def account_list(request):
    """Display list of all accounts with traffic data."""
    import os
    from django.db.models import Sum, Q, F
    from django.utils import timezone
    from datetime import timedelta
    
    # Calculate current calendar day (00:00 to 23:59)
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get accounts with usage data, ordered by total usage
    # Use a different name for annotation to avoid conflict with @property
    accounts = Account.objects.select_related('user').annotate(
        usage_total=F('total_bytes_sent') + F('total_bytes_received'),
        # Calculate today's usage using subquery aggregation
        # Count sessions that have activity today:
        # - Started today (count all their usage)
        # - Disconnected today (count all their usage - approximation)
        # - Still active (count their current usage)
        # Note: This is an approximation - for sessions that started before today but
        # disconnected today, we count all usage, not just today's portion
        last_24h_sent=Sum(
            'sessions__bytes_sent',
            filter=Q(
                sessions__connected_at__gte=today_start
            ) | Q(
                sessions__disconnected_at__gte=today_start,
                sessions__disconnected_at__isnull=False
            ) | Q(
                sessions__is_active=True
            )
        ),
        last_24h_received=Sum(
            'sessions__bytes_received',
            filter=Q(
                sessions__connected_at__gte=today_start
            ) | Q(
                sessions__disconnected_at__gte=today_start,
                sessions__disconnected_at__isnull=False
            ) | Q(
                sessions__is_active=True
            )
        )
    ).order_by('-usage_total')
    
    last_usage_updated = None
    for acc in accounts:
        if acc.usage_last_updated and (last_usage_updated is None or acc.usage_last_updated > last_usage_updated):
            last_usage_updated = acc.usage_last_updated
    
    # Get live traffic data from OpenVPN status (current session data)
    user_data = get_user_data_for_template()
    
    # Get connected clients for status indication
    connected_clients = {c.common_name for c in get_connected_clients()}
    
    # Add connection status and format today's usage to context
    for account in accounts:
        account.is_connected = account.account_number in connected_clients
        # Format today's usage (default to 0 if None)
        account.last_24h_sent = account.last_24h_sent or 0
        account.last_24h_received = account.last_24h_received or 0
        account.last_24h_sent_human = Account._format_bytes(account.last_24h_sent)
        account.last_24h_received_human = Account._format_bytes(account.last_24h_received)
        account.last_24h_total = account.last_24h_sent + account.last_24h_received
        account.last_24h_total_human = Account._format_bytes(account.last_24h_total)
    
    # Get usage stats summary
    usage_stats = get_usage_stats()
    
    # Calculate total today's usage for stats bar
    total_last_24h_sent = sum(acc.last_24h_sent for acc in accounts)
    total_last_24h_received = sum(acc.last_24h_received for acc in accounts)
    total_last_24h_total = total_last_24h_sent + total_last_24h_received
    usage_stats['last_24h_sent'] = Account._format_bytes(total_last_24h_sent)
    usage_stats['last_24h_received'] = Account._format_bytes(total_last_24h_received)
    usage_stats['last_24h_total'] = Account._format_bytes(total_last_24h_total)
    
    # Get server URL from settings, fallback to environment variable
    server_url = Setting.get_value('server_url', os.environ.get('SERVER_URL', ''))
    # Get server port from settings, fallback to environment variable
    server_port = Setting.get_value('server_port', os.environ.get('SERVER_PORT', ''))
    
    context = {
        'accounts': accounts,
        'user_data': user_data,
        'usage_stats': usage_stats,
        'server_url': server_url,
        'server_port': server_port,
        'last_usage_updated': last_usage_updated,
    }
    
    return render(request, 'openvpn_dashboard/account_list.html', context)


@login_required
def account_create(request):
    """Create a new account and generate OpenVPN config."""
    # Check if a user_id was passed as a query parameter (from user info page)
    preselected_user_id = request.GET.get('user_id')
    preselected_user = None
    
    if preselected_user_id:
        try:
            preselected_user = User.objects.get(id=preselected_user_id)
        except User.DoesNotExist:
            pass
    
    # Get the 'next' parameter for redirect after save
    next_url = request.GET.get('next') or request.POST.get('next')
    
    if request.method == 'POST':
        form = AccountCreationForm(request.POST)
        if form.is_valid():
            try:
                # Get account_number from form before saving
                account_number = form.cleaned_data.get('account_number')
                
                # Create OpenVPN configuration FIRST (before saving account to DB)
                # This ensures that if OpenVPN config creation fails, 
                # the account won't be created in the database
                try:
                    ovpn_path = create_openvpn_config(account_number)
                    logger.info(f"OpenVPN config created successfully for '{account_number}' at {ovpn_path}")
                except Exception as e:
                    # If OpenVPN config creation fails, don't create the account
                    logger.error(f"Failed to create OpenVPN config for '{account_number}': {e}")
                    messages.error(
                        request,
                        f'Failed to create OpenVPN configuration: {e}. Account was not created.'
                    )
                    return render(request, 'openvpn_dashboard/account_create.html', {
                        'form': form, 
                        'error': f'Failed to create OpenVPN configuration: {e}',
                        'preselected_user': preselected_user,
                        'next_url': next_url,
                    })
                
                # Only save the account if OpenVPN config was created successfully
                account = form.save()
                messages.success(
                    request, 
                    f'Account created successfully. Config saved to {ovpn_path}'
                )
                
                # Redirect to 'next' URL if provided, otherwise to user_update if preselected_user, else account_list
                if next_url:
                    return redirect(next_url)
                elif preselected_user_id:
                    return redirect('user_update', user_id=preselected_user_id)
                return redirect('account_list')
                
            except Exception as e:
                logger.error(f"Failed to create account: {e}")
                messages.error(request, f'Failed to create account: {e}')
                return render(request, 'openvpn_dashboard/account_create.html', {
                    'form': form, 
                    'error': str(e),
                    'preselected_user': preselected_user,
                    'next_url': next_url,
                })
    else:
        initial_data = {'status': 'active'}
        if preselected_user:
            initial_data['user'] = preselected_user
        form = AccountCreationForm(initial=initial_data)
    
    return render(request, 'openvpn_dashboard/account_create.html', {
        'form': form,
        'preselected_user': preselected_user,
        'next_url': next_url,
    })


@login_required
def account_update(request, account_id):
    """Update an existing account."""
    account = get_object_or_404(Account, id=account_id)
    old_status = account.status
    old_expiration_date = account.expiration_date
    
    # Get the 'next' parameter for redirect after save
    next_url = request.GET.get('next') or request.POST.get('next')
    
    if request.method == 'POST':
        form = AccountCreationForm(request.POST, instance=account)
        if form.is_valid():
            updated_account = form.save()
            
            # Handle status change - enable/disable OpenVPN user accordingly
            new_status = updated_account.status
            new_expiration_date = updated_account.expiration_date
            
            # Check if expiration date was extended for an expired account
            from django.utils import timezone
            today = timezone.now().date()
            expiration_extended = (old_status == 'expired' and 
                                 old_expiration_date < today and 
                                 new_expiration_date > today)
            
            if old_status != new_status:
                if new_status == 'active':
                    enable_openvpn_user(updated_account.account_number)
                elif new_status in ['disabled', 'expired']:
                    disable_openvpn_user(updated_account.account_number)
            elif expiration_extended and new_status == 'active':
                # Account was automatically reactivated by save() method, enable OpenVPN user
                enable_openvpn_user(updated_account.account_number)
            
            messages.success(request, 'Account updated successfully.')
            # Redirect to 'next' URL if provided, otherwise to account_list
            if next_url:
                return redirect(next_url)
            return redirect('account_list')
    else:
        form = AccountCreationForm(instance=account)
    
    # Check if expiration date is in the future (to enable status toggle)
    from django.utils import timezone
    from datetime import timedelta
    today = timezone.now().date()
    expiration_in_future = account.expiration_date > today
    
    # Get daily usage statistics for this account (last 30 days by default)
    days = int(request.GET.get('days', 30))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days-1)
    
    daily_stats = DailyUsageStats.objects.filter(
        account=account,
        date__gte=start_date,
        date__lte=end_date
    ).order_by('-date')
    
    # Calculate totals
    totals = {
        'total_bytes_sent': sum(s.bytes_sent for s in daily_stats),
        'total_bytes_received': sum(s.bytes_received for s in daily_stats),
        'total_sessions': sum(s.session_count for s in daily_stats),
        'total_days': daily_stats.count(),
    }
    totals['total_bytes'] = totals['total_bytes_sent'] + totals['total_bytes_received']
    totals['total_bytes_sent_human'] = Account._format_bytes(totals['total_bytes_sent'])
    totals['total_bytes_received_human'] = Account._format_bytes(totals['total_bytes_received'])
    totals['total_bytes_human'] = Account._format_bytes(totals['total_bytes'])
    
    # Calculate average daily usage
    if totals['total_days'] > 0:
        avg_bytes = totals['total_bytes'] // totals['total_days']
        totals['avg_daily_bytes_human'] = Account._format_bytes(avg_bytes)
    else:
        totals['avg_daily_bytes_human'] = '0 B'
    
    return render(request, 'openvpn_dashboard/account_update.html', {
        'form': form, 
        'account': account, 
        'next_url': next_url,
        'expiration_in_future': expiration_in_future,
        'daily_stats': daily_stats,
        'totals': totals,
        'start_date': start_date,
        'end_date': end_date,
        'days': days,
    })


@login_required
def update_account_status(request, account_number, status):
    """
    Update account status via AJAX.
    
    Handles activate, deactivate, and expired status changes.
    """
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            account = Account.objects.get(account_number=account_number)
            
            if status == 'activate':
                account.status = 'active'
                account.save()
                enable_openvpn_user(account.account_number)
                success_message = 'Account activated successfully.'
                
            elif status == 'deactivate':
                account.status = 'disabled'
                account.save()
                disable_openvpn_user(account.account_number)
                success_message = 'Account deactivated successfully.'
                
            elif status == 'expired':
                account.status = 'expired'
                account.save()
                # Optionally disable the user when expired
                disable_openvpn_user(account.account_number)
                success_message = 'Account marked as expired.'
                
            else:
                return JsonResponse({
                    'success': False, 
                    'message': 'Invalid status.'
                })
            
            return JsonResponse({
                'success': True, 
                'message': success_message, 
                'updated_status': account.status
            })
        
        except Account.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'message': 'Account not found.'
            })
        except Exception as e:
            logger.error(f"Failed to update account status: {e}")
            return JsonResponse({
                'success': False, 
                'message': f'Error: {str(e)}'
            })
    else:
        return JsonResponse({
            'success': False, 
            'message': 'Invalid request.'
        })


@login_required
def account_delete(request, account_id):
    """Delete an account and revoke OpenVPN certificate."""
    account = get_object_or_404(Account, pk=account_id)

    if request.method == 'POST':
        try:
            # Revoke OpenVPN certificate
            delete_openvpn_user(account.account_number)
        except Exception as e:
            logger.error(f"Failed to revoke OpenVPN user: {e}")
            messages.warning(
                request,
                f'Account deleted but OpenVPN revocation failed: {e}'
            )
        
        account.delete()
        messages.success(request, 'Account deleted successfully.')
        return redirect('account_list')

    return render(request, 'openvpn_dashboard/account_delete.html', {'account': account})


@login_required
def reset_account_usage_view(request, account_id):
    """Reset usage counters for a specific account via AJAX."""
    if request.method == 'POST':
        try:
            account = get_object_or_404(Account, pk=account_id)
            account.reset_usage()
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Usage reset for {account.account_number}',
                    'total_bytes_sent': 0,
                    'total_bytes_received': 0,
                })
            else:
                messages.success(request, f'Usage reset for {account.account_number}')
                return redirect('account_list')
                
        except Exception as e:
            logger.error(f"Failed to reset usage: {e}")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': str(e)
                })
            else:
                messages.error(request, f'Failed to reset usage: {e}')
                return redirect('account_list')
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def reset_all_usage_view(request):
    """Reset usage counters for all accounts."""
    if request.method == 'POST':
        try:
            count = reset_all_usage()
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Usage reset for {count} accounts'
                })
            else:
                messages.success(request, f'Usage reset for {count} accounts')
                return redirect('account_list')
                
        except Exception as e:
            logger.error(f"Failed to reset all usage: {e}")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': str(e)
                })
            else:
                messages.error(request, f'Failed to reset usage: {e}')
                return redirect('account_list')
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def server_status(request):
    """
    Display OpenVPN server status.
    
    Shows connected clients, traffic statistics, and server health.
    """
    status = get_server_status()
    connected = get_connected_clients()
    usage_stats = get_usage_stats()
    
    # Get active sessions with more details
    active_sessions = ConnectionSession.objects.filter(
        is_active=True
    ).select_related('account', 'account__user').order_by('-connected_at')
    
    # Get recent sessions (last 24 hours)
    from django.utils import timezone
    from datetime import timedelta
    
    recent_cutoff = timezone.now() - timedelta(hours=24)
    recent_sessions = ConnectionSession.objects.filter(
        connected_at__gte=recent_cutoff
    ).select_related('account').order_by('-connected_at')[:50]
    
    context = {
        'status': status,
        'connected_clients': connected,
        'usage_stats': usage_stats,
        'active_sessions': active_sessions,
        'recent_sessions': recent_sessions,
    }
    
    return render(request, 'openvpn_dashboard/server_status.html', context)


@login_required
def account_sessions(request, account_id):
    """Display session history for a specific account."""
    account = get_object_or_404(Account, pk=account_id)
    
    sessions = ConnectionSession.objects.filter(
        account=account
    ).order_by('-connected_at')[:100]
    
    context = {
        'account': account,
        'sessions': sessions,
    }
    
    return render(request, 'openvpn_dashboard/account_sessions.html', context)


@login_required
def save_server_url(request):
    """Save the server URL setting via AJAX."""
    if request.method == 'POST':
        try:
            server_url = request.POST.get('server_url', '').strip()
            Setting.set_value('server_url', server_url)
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Server URL saved successfully',
                    'server_url': server_url
                })
            else:
                messages.success(request, 'Server URL saved successfully')
                return redirect('account_list')
                
        except Exception as e:
            logger.error(f"Failed to save server URL: {e}")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': str(e)
                })
            else:
                messages.error(request, f'Failed to save server URL: {e}')
                return redirect('account_list')
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def save_server_port(request):
    """Save the server port setting via AJAX."""
    if request.method == 'POST':
        try:
            server_port = request.POST.get('server_port', '').strip()
            Setting.set_value('server_port', server_port)
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Server port saved successfully',
                    'server_port': server_port
                })
            else:
                messages.success(request, 'Server port saved successfully')
                return redirect('account_list')
                
        except Exception as e:
            logger.error(f"Failed to save server port: {e}")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': str(e)
                })
            else:
                messages.error(request, f'Failed to save server port: {e}')
                return redirect('account_list')
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def renew_account_certificate(request, account_id):
    """
    Renew the OpenVPN certificate for an account.
    
    This regenerates the client certificate and updates the .ovpn config file.
    """
    if request.method == 'POST':
        try:
            account = get_object_or_404(Account, pk=account_id)
            
            # Renew the certificate
            ovpn_path = renew_openvpn_user(account.account_number)
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Certificate renewed for {account.account_number}',
                    'ovpn_path': ovpn_path
                })
            else:
                messages.success(request, f'Certificate renewed for {account.account_number}')
                next_url = request.POST.get('next') or request.GET.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect('account_update', account_id)
                
        except Exception as e:
            logger.error(f"Failed to renew certificate: {e}")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': str(e)
                })
            else:
                messages.error(request, f'Failed to renew certificate: {e}')
                next_url = request.POST.get('next') or request.GET.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect('account_update', account_id)
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def daily_stats_list(request):
    """Display daily usage statistics for all accounts."""
    from datetime import timedelta
    from django.utils import timezone
    
    # Get date range from query params (default: last 30 days)
    days = int(request.GET.get('days', 30))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days-1)
    
    # Get server-wide daily stats
    server_stats = ServerDailyStats.objects.filter(
        date__gte=start_date,
        date__lte=end_date
    ).order_by('-date')
    
    context = {
        'server_stats': server_stats,
        'start_date': start_date,
        'end_date': end_date,
        'days': days,
    }
    
    return render(request, 'openvpn_dashboard/daily_stats_list.html', context)


@login_required
def daily_stats_account(request, account_id):
    """Display daily usage statistics for a specific account."""
    from datetime import timedelta
    from django.utils import timezone
    
    account = get_object_or_404(Account, pk=account_id)
    
    # Get date range from query params (default: last 30 days)
    days = int(request.GET.get('days', 30))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days-1)
    
    # Get daily stats for this account
    stats = DailyUsageStats.objects.filter(
        account=account,
        date__gte=start_date,
        date__lte=end_date
    ).order_by('-date')
    
    # Calculate totals
    totals = {
        'total_bytes_sent': sum(s.bytes_sent for s in stats),
        'total_bytes_received': sum(s.bytes_received for s in stats),
        'total_sessions': sum(s.session_count for s in stats),
        'total_days': stats.count(),
    }
    totals['total_bytes'] = totals['total_bytes_sent'] + totals['total_bytes_received']
    totals['total_bytes_sent_human'] = Account._format_bytes(totals['total_bytes_sent'])
    totals['total_bytes_received_human'] = Account._format_bytes(totals['total_bytes_received'])
    totals['total_bytes_human'] = Account._format_bytes(totals['total_bytes'])
    
    # Calculate average daily usage
    if totals['total_days'] > 0:
        avg_bytes = totals['total_bytes'] // totals['total_days']
        totals['avg_daily_bytes_human'] = Account._format_bytes(avg_bytes)
    else:
        totals['avg_daily_bytes_human'] = '0 B'
    
    context = {
        'account': account,
        'stats': stats,
        'totals': totals,
        'start_date': start_date,
        'end_date': end_date,
        'days': days,
    }
    
    return render(request, 'openvpn_dashboard/daily_stats_account.html', context)
