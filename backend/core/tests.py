from datetime import timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from core.models import ParkingListing, ParkingSpace, UserProfile, Vehicle, Reservation

class ParkARComprehensiveTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Create admin user
        self.admin = User.objects.create_superuser(username="admin@parkar.local", email="admin@parkar.local", password="AdminPassword123!")
        UserProfile.objects.create(user=self.admin, role=UserProfile.Role.ADMIN, provider_verified=True)

        # Create provider user
        self.provider = User.objects.create_user(username="provider@parkar.local", email="provider@parkar.local", password="ProviderPassword123!")
        UserProfile.objects.create(user=self.provider, role=UserProfile.Role.PROVIDER, provider_verified=True)

        # Create driver user
        self.driver = User.objects.create_user(username="driver@parkar.local", email="driver@parkar.local", password="DriverPassword123!")
        UserProfile.objects.create(user=self.driver, role=UserProfile.Role.DRIVER)

        # Create sample listing
        self.listing = ParkingListing.objects.create(
            provider=self.provider,
            name="Downtown Central Parking",
            address="123 Ayala Ave",
            city="Makati",
            hourly_rate=Decimal("50.00"),
            status=ParkingListing.Status.ACTIVE,
            opening_time="00:00",
            closing_time="23:59",
        )
        self.space1 = ParkingSpace.objects.create(listing=self.listing, code="A1", grid_row=0, grid_column=0, status=ParkingSpace.Status.AVAILABLE)
        self.space2 = ParkingSpace.objects.create(listing=self.listing, code="A2", grid_row=0, grid_column=1, status=ParkingSpace.Status.AVAILABLE)

        # Create driver vehicle
        self.vehicle = Vehicle.objects.create(owner=self.driver, name="Sedan", category=Vehicle.Category.CAR, plate_number="ABC-1234")

    def test_user_registration_and_login(self):
        # Register new driver
        reg_resp = self.client.post("/api/v1/auth/register/", {
            "email": "newdriver@parkar.local",
            "password": "ValidPassword123!",
            "username": "newdriver"
        }, format="json")
        self.assertEqual(reg_resp.status_code, 201)
        self.assertIn("token", reg_resp.data)

        # Login
        login_resp = self.client.post("/api/v1/auth/login/", {
            "email": "newdriver@parkar.local",
            "password": "ValidPassword123!"
        }, format="json")
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn("token", login_resp.data)

    def test_password_reset_flow(self):
        # Request password reset
        req_resp = self.client.post("/api/v1/auth/password-reset/", {"email": "driver@parkar.local"}, format="json")
        self.assertEqual(req_resp.status_code, 200)

    def test_account_settings_and_password_change(self):
        self.client.force_authenticate(user=self.driver)
        # Update name and phone
        patch_resp = self.client.patch("/api/v1/me/", {
            "first_name": "Juan",
            "last_name": "Cruz",
            "phone": "+639123456789"
        }, format="json")
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(patch_resp.data["first_name"], "Juan")
        self.assertEqual(patch_resp.data["phone"], "+639123456789")

        # Change password with valid current password
        pw_resp = self.client.patch("/api/v1/me/", {
            "current_password": "DriverPassword123!",
            "new_password": "NewSecretPass123!"
        }, format="json")
        self.assertEqual(pw_resp.status_code, 200)

        # Verify new password works
        self.client.force_authenticate(user=None)
        login_resp = self.client.post("/api/v1/auth/login/", {
            "email": "driver@parkar.local",
            "password": "NewSecretPass123!"
        }, format="json")
        self.assertEqual(login_resp.status_code, 200)

    def test_admin_create_and_manage_users(self):
        self.client.force_authenticate(user=self.admin)
        # Create an admin user via API
        create_resp = self.client.post("/api/v1/admin/users/", {
            "email": "newadmin@parkar.local",
            "password": "SuperAdminPass123!",
            "role": "admin"
        }, format="json")
        self.assertEqual(create_resp.status_code, 201)
        new_id = create_resp.data["id"]

        # Toggle user active status
        patch_resp = self.client.patch(f"/api/v1/admin/users/{new_id}/", {"active": False}, format="json")
        self.assertEqual(patch_resp.status_code, 200)
        self.assertFalse(patch_resp.data["active"])

        # Change user role to provider
        role_resp = self.client.patch(f"/api/v1/admin/users/{new_id}/", {"role": "provider"}, format="json")
        self.assertEqual(role_resp.status_code, 200)
        self.assertEqual(role_resp.data["role"], "provider")

    def test_reservation_and_ticket_pass(self):
        self.client.force_authenticate(user=self.driver)
        starts = timezone.now() + timedelta(hours=2)
        ends = starts + timedelta(hours=3)

        book_resp = self.client.post("/api/v1/reservations/", {
            "listing_id": str(self.listing.id),
            "vehicle_ids": [self.vehicle.id],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "payment_method": "pay_on_site"
        }, format="json")
        self.assertEqual(book_resp.status_code, 201)
        res_id = book_resp.data["id"]

        # View ticket pass
        ticket_resp = self.client.get(f"/api/v1/reservations/{res_id}/ticket/")
        self.assertEqual(ticket_resp.status_code, 200)
        self.assertIn("pass_qr_svg", ticket_resp.data)

        # Check layout slots preview
        layout_preview = self.client.get(f"/api/v1/listings/{self.listing.id}/layout/?starts_at={starts.isoformat()}&ends_at={ends.isoformat()}")
        self.assertEqual(layout_preview.status_code, 200)
        spaces = layout_preview.data["spaces"]
        statuses = [s["slot_status"] for s in spaces]
        self.assertIn("reserved", statuses)

