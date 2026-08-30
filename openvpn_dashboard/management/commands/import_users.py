"""
Management command to import users and accounts from a CSV file.

CSV Format:
name,phone,info,account_number,expiration_date,status
John Doe,+1234567890,Some info,john_doe_001,2025-12-31,active
Jane Smith,+0987654321,,jane_smith_001,2025-06-30,active

Notes:
- expiration_date should be in YYYY-MM-DD format
- status can be: active, disabled, revoked, deleted, expired (defaults to 'active')
- info field is optional (can be empty)
- If a user with the same name and phone exists, the account will be added to that user
"""

import csv
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openvpn_dashboard.models import User, Account
from openvpn_dashboard.services.utils import create_openvpn_config


class Command(BaseCommand):
    help = 'Import users and accounts from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the CSV file')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate the CSV without actually importing',
        )
        parser.add_argument(
            '--skip-openvpn',
            action='store_true',
            help='Skip creating OpenVPN certificates (for importing existing users)',
        )
        parser.add_argument(
            '--delimiter',
            type=str,
            default=',',
            help='CSV delimiter (default: comma)',
        )

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        dry_run = options['dry_run']
        skip_openvpn = options['skip_openvpn']
        delimiter = options['delimiter']

        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                
                # Validate headers
                required_fields = {'name', 'phone', 'account_number', 'expiration_date'}
                if not required_fields.issubset(set(reader.fieldnames or [])):
                    missing = required_fields - set(reader.fieldnames or [])
                    raise CommandError(f'Missing required CSV columns: {missing}')
                
                rows = list(reader)
        except FileNotFoundError:
            raise CommandError(f'CSV file not found: {csv_file}')
        except Exception as e:
            raise CommandError(f'Error reading CSV file: {e}')

        self.stdout.write(f'Found {len(rows)} rows in CSV file')

        # Validate all rows first
        errors = []
        for i, row in enumerate(rows, start=2):  # Start at 2 (header is row 1)
            row_errors = self.validate_row(row, i)
            errors.extend(row_errors)

        if errors:
            self.stdout.write(self.style.ERROR('Validation errors found:'))
            for error in errors:
                self.stdout.write(self.style.ERROR(f'  - {error}'))
            raise CommandError('Fix the errors above and try again')

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Dry run completed. No errors found.'))
            return

        # Import the data
        created_users = 0
        created_accounts = 0
        skipped_accounts = 0

        with transaction.atomic():
            for row in rows:
                user, user_created = self.get_or_create_user(row)
                if user_created:
                    created_users += 1

                account, account_created = self.create_account(row, user, skip_openvpn)
                if account_created:
                    created_accounts += 1
                else:
                    skipped_accounts += 1

        self.stdout.write(self.style.SUCCESS(
            f'Import completed: {created_users} users created, '
            f'{created_accounts} accounts created, {skipped_accounts} accounts skipped (already exist)'
        ))

    def validate_row(self, row, row_num):
        """Validate a single CSV row."""
        errors = []

        if not row.get('name', '').strip():
            errors.append(f'Row {row_num}: name is required')

        if not row.get('phone', '').strip():
            errors.append(f'Row {row_num}: phone is required')

        if not row.get('account_number', '').strip():
            errors.append(f'Row {row_num}: account_number is required')

        exp_date = row.get('expiration_date', '').strip()
        if not exp_date:
            errors.append(f'Row {row_num}: expiration_date is required')
        else:
            try:
                datetime.strptime(exp_date, '%Y-%m-%d')
            except ValueError:
                errors.append(f'Row {row_num}: expiration_date must be in YYYY-MM-DD format')

        status = row.get('status', 'active').strip().lower()
        valid_statuses = {'active', 'disabled', 'revoked', 'deleted', 'expired'}
        if status and status not in valid_statuses:
            errors.append(f'Row {row_num}: invalid status "{status}". Must be one of: {valid_statuses}')

        return errors

    def get_or_create_user(self, row):
        """Get existing user or create a new one."""
        name = row['name'].strip()
        phone = row['phone'].strip()
        info = row.get('info', '').strip() or None

        # Try to find existing user by name and phone
        user = User.objects.filter(name=name, phone=phone).first()
        if user:
            return user, False

        # Create new user
        user = User.objects.create(
            name=name,
            phone=phone,
            info=info
        )
        self.stdout.write(f'  Created user: {name}')
        return user, True

    def create_account(self, row, user, skip_openvpn):
        """Create an account for the user."""
        account_number = row['account_number'].strip()
        expiration_date = datetime.strptime(row['expiration_date'].strip(), '%Y-%m-%d').date()
        status = row.get('status', 'active').strip().lower() or 'active'

        # Check if account already exists
        if Account.objects.filter(account_number=account_number).exists():
            self.stdout.write(self.style.WARNING(
                f'  Account {account_number} already exists, skipping'
            ))
            return None, False

        # Create OpenVPN config FIRST (before saving account to DB)
        # This ensures that if OpenVPN config creation fails, 
        # the account won't be created in the database
        if not skip_openvpn:
            try:
                create_openvpn_config(account_number)
                self.stdout.write(f'    OpenVPN config created for {account_number}')
            except Exception as e:
                # If OpenVPN config creation fails, don't create the account
                self.stdout.write(self.style.ERROR(
                    f'    Error: Could not create OpenVPN config for {account_number}: {e}'
                ))
                self.stdout.write(self.style.ERROR(
                    f'    Account {account_number} was NOT created due to OpenVPN config failure'
                ))
                raise  # Re-raise to trigger transaction rollback

        # Only create the account if OpenVPN config was created successfully (or if skipping OpenVPN)
        account = Account.objects.create(
            user=user,
            account_number=account_number,
            expiration_date=expiration_date,
            status=status
        )
        self.stdout.write(f'  Created account: {account_number}')

        return account, True



