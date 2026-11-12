import os
import sys
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from core.models import UserProfile

class Command(BaseCommand):
    help = "Create or promote a ParkAR administrator account via CLI arguments, environment variables, or interactive prompts."

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, help="Administrator email address")
        parser.add_argument("--password", type=str, help="Administrator password (minimum 8 characters; 12+ recommended)")
        parser.add_argument("--username", type=str, help="Optional username (defaults to email)")
        parser.add_argument("--noinput", action="store_true", help="Do not prompt for input if values are missing")

    def handle(self, *args, **options):
        email = (options.get("email") or os.getenv("BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower()
        password = options.get("password") or os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or ""
        username = (options.get("username") or "").strip()

        noinput = options.get("noinput", False)

        if not email and not noinput and sys.stdin.isatty():
            self.stdout.write("ParkAR Admin Account Setup")
            try:
                email = input("Administrator email: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                raise CommandError("Admin creation cancelled.")

        if not password and not noinput and sys.stdin.isatty():
            import getpass
            try:
                password = getpass.getpass("Administrator password (min 8 chars): ").strip()
            except (KeyboardInterrupt, EOFError):
                raise CommandError("Admin creation cancelled.")

        if not email or not password:
            raise CommandError("Administrator email and password are required. Provide --email and --password, set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD, or run without --noinput.")

        if len(password) < 8:
            raise CommandError("Password must contain at least 8 characters.")

        if not username:
            username = email

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            if User.objects.filter(username__iexact=username).exists():
                username = email
            user = User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Successfully created administrator account '{email}'."))
        else:
            user.is_staff = True
            user.is_superuser = True
            if options.get("password"):
                user.set_password(password)
                user.save(update_fields=["is_staff", "is_superuser", "password"])
                self.stdout.write(self.style.SUCCESS(f"Promoted '{email}' to administrator and updated password."))
            else:
                user.save(update_fields=["is_staff", "is_superuser"])
                self.stdout.write(self.style.SUCCESS(f"Administrator access enabled for '{email}' (existing password retained)."))

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = UserProfile.Role.ADMIN
        profile.provider_verified = True
        profile.save(update_fields=["role", "provider_verified"])
