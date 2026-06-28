"""Superuser-only user management views."""
from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render

from ..form_utils import clean_person_text, form_errors_to_messages
from ._helpers import User, _superuser_required, _validate_user_name_fields


@_superuser_required
def user_list(request):
    users = User.objects.order_by('-is_superuser', '-is_active', 'username')
    return render(request, 'users/user_list.html', {'users': users})


@_superuser_required
def user_create(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        names_ok = _validate_user_name_fields(request)
        if form.is_valid() and names_ok:
            user = form.save(commit=False)
            user.is_staff = request.POST.get('is_staff') == 'on'
            user.is_superuser = request.POST.get('is_superuser') == 'on'
            user.email = request.POST.get('email', '')
            user.first_name = clean_person_text(request.POST.get('first_name', ''))
            user.last_name = clean_person_text(request.POST.get('last_name', ''))
            user.save()
            messages.success(request, f'User "{user.username}" created successfully.')
            return redirect('core:user_list')
        elif not form.is_valid():
            form_errors_to_messages(request, form)
    else:
        form = UserCreationForm()
    return render(request, 'users/user_form.html', {'form': form, 'action': 'Create'})


@_superuser_required
def user_change_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = SetPasswordForm(target, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f'Password for "{target.username}" changed successfully.')
            return redirect('core:user_list')
        else:
            form_errors_to_messages(request, form)
    else:
        form = SetPasswordForm(target)
    return render(request, 'users/user_password.html', {'form': form, 'target': target})


@_superuser_required
def user_toggle_active(request, pk):
    if request.method == 'POST':
        target = get_object_or_404(User, pk=pk)
        if target == request.user:
            messages.error(request, 'You cannot deactivate your own account.')
        else:
            target.is_active = not target.is_active
            target.save()
            state = 'activated' if target.is_active else 'deactivated'
            messages.success(request, f'User "{target.username}" has been {state}.')
    return redirect('core:user_list')
