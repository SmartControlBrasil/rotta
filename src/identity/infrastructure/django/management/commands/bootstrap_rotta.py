from django.core.management.base import BaseCommand

from src.identity.infrastructure.django.rbac import sync_rbac


class Command(BaseCommand):
    help = "Bootstrap Rotta foundation structural data."

    def handle(self, *args, **options):
        stats = sync_rbac()
        self.stdout.write(self.style.SUCCESS("Rotta foundation bootstrap completed."))
        for field, value in stats.__dict__.items():
            self.stdout.write(f"{field}: {value}")
