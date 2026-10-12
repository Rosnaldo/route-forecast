import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Block until the database accepts connections (used by the Docker entrypoint)."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)

    def handle(self, *args, timeout: int, **options):
        deadline = time.monotonic() + timeout
        while True:
            try:
                connections["default"].ensure_connection()
                self.stdout.write(self.style.SUCCESS("Database available."))
                return
            except OperationalError:
                if time.monotonic() > deadline:
                    raise CommandError(f"Database not available after {timeout}s.") from None
                self.stdout.write("Waiting for database...")
                time.sleep(1)
