#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def _relabel_legacy_app():
    """Rewrite legacy app labels to openvpn_dashboard before migrate plans.

    Existing databases recorded migrations under ui_ovpn (original) or
    openvpn_ui (after the first rename). Without this rewrite, Django would
    treat 0001-0006 as unapplied and try to recreate tables.
    """
    if len(sys.argv) < 2 or sys.argv[1] not in ('migrate', 'showmigrations'):
        return
    import django
    from django.db.utils import OperationalError, ProgrammingError

    django.setup()
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            for old_label in ('ui_ovpn', 'openvpn_ui'):
                cursor.execute(
                    "UPDATE django_migrations SET app = %s WHERE app = %s",
                    ['openvpn_dashboard', old_label],
                )
                cursor.execute(
                    "UPDATE django_content_type SET app_label = %s WHERE app_label = %s",
                    ['openvpn_dashboard', old_label],
                )
    except (OperationalError, ProgrammingError) as exc:
        msg = str(exc).lower()
        if 'no such table' in msg or 'does not exist' in msg:
            return
        print(
            f"Warning: could not relabel legacy app -> openvpn_dashboard ({exc})",
            file=sys.stderr,
        )


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    _relabel_legacy_app()
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
