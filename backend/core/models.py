import uuid
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

class UserProfile(models.Model):
    class Role(models.TextChoices):
        DRIVER = "driver", "Driver"
        PROVIDER = "provider", "Provider"
        ADMIN = "admin", "Administrator"
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.DRIVER)
    phone = models.CharField(max_length=32, blank=True)
    provider_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email or self.user.username} ({self.role})"

class Vehicle(models.Model):
    class Category(models.TextChoices):
        MOTORCYCLE = "motorcycle", "Motorcycle"
        CAR = "car", "Car"
        SUV = "suv", "SUV"
        VAN = "van", "Van"
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vehicles")
    name = models.CharField(max_length=80)
    category = models.CharField(max_length=16, choices=Category.choices)
    plate_number = models.CharField(max_length=24)
    length_m = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("4.50"))
    width_m = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.80"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("owner", "plate_number")]

class ProviderApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="provider_applications")
    legal_name = models.CharField(max_length=160)
    business_name = models.CharField(max_length=160, blank=True)
    contact_phone = models.CharField(max_length=32)
    address = models.TextField()
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_provider_applications")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class ParkingListing(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending review"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="parking_listings")
    name = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    address = models.TextField()
    city = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    covered = models.BooleanField(default=True)
    opening_time = models.TimeField(default="06:00")
    closing_time = models.TimeField(default="22:00")
    hourly_rate = models.DecimalField(max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    width_m = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    length_m = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    current_layout_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["name"]
    def __str__(self):
        return self.name

class ParkingZone(models.Model):
    listing = models.ForeignKey(ParkingListing, on_delete=models.CASCADE, related_name="zones")
    name = models.CharField(max_length=60)
    order = models.PositiveSmallIntegerField(default=0)

class ParkingSpace(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        BLOCKED = "blocked", "Blocked by provider"
    class VehicleClass(models.TextChoices):
        ANY = "any", "Any configured vehicle"
        MOTORCYCLE = "motorcycle", "Motorcycle"
        CAR = "car", "Car"
        LARGE = "large", "SUV / van"
    listing = models.ForeignKey(ParkingListing, on_delete=models.CASCADE, related_name="spaces")
    zone = models.ForeignKey(ParkingZone, null=True, blank=True, on_delete=models.SET_NULL, related_name="spaces")
    code = models.CharField(max_length=20)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.AVAILABLE)
    is_accessible = models.BooleanField(default=False)
    vehicle_class = models.CharField(max_length=16, choices=VehicleClass.choices, default=VehicleClass.ANY)
    width_m = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("2.50"))
    length_m = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))
    grid_row = models.PositiveSmallIntegerField(default=0)
    grid_column = models.PositiveSmallIntegerField(default=0)
    layout_version = models.PositiveIntegerField(default=1)
    class Meta:
        unique_together = [("listing", "code")]
        ordering = ["grid_row", "grid_column", "code"]
    def __str__(self):
        return f"{self.listing.name} · {self.code}"

class LayoutVersion(models.Model):
    listing = models.ForeignKey(ParkingListing, on_delete=models.CASCADE, related_name="layout_versions")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("listing", "version")]

class BoundaryPoint(models.Model):
    listing = models.ForeignKey(ParkingListing, on_delete=models.CASCADE, related_name="boundary_points")
    index = models.PositiveSmallIntegerField()
    x_m = models.DecimalField(max_digits=8, decimal_places=3)
    y_m = models.DecimalField(max_digits=8, decimal_places=3)
    class Meta:
        unique_together = [("listing", "index")]
        ordering = ["index"]

class MeasurementRecord(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        CAMERA_ESTIMATE = "camera_estimate", "Camera estimate"
    listing = models.ForeignKey(ParkingListing, on_delete=models.CASCADE, related_name="measurements")
    source = models.CharField(max_length=20, choices=Source.choices)
    width_m = models.DecimalField(max_digits=7, decimal_places=2)
    length_m = models.DecimalField(max_digits=7, decimal_places=2)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class PricingRule(models.Model):
    listing = models.ForeignKey(ParkingListing, on_delete=models.CASCADE, related_name="pricing_rules")
    name = models.CharField(max_length=80)
    vehicle_category = models.CharField(max_length=16, choices=Vehicle.Category.choices, blank=True)
    hourly_rate = models.DecimalField(max_digits=9, decimal_places=2)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    active = models.BooleanField(default=True)

class Reservation(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=14, unique=True, editable=False)
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reservations")
    listing = models.ForeignKey(ParkingListing, on_delete=models.PROTECT, related_name="reservations")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CONFIRMED)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["status", "starts_at", "ends_at"]),
            models.Index(fields=["listing", "status"]),
        ]
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = uuid.uuid4().hex[:10].upper()
        super().save(*args, **kwargs)

class ReservationVehicle(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="reservation_vehicles")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="reservation_vehicles")
    class Meta:
        unique_together = [("reservation", "vehicle")]

class SpaceAssignment(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="assignments")
    space = models.ForeignKey(ParkingSpace, on_delete=models.PROTECT, related_name="assignments")
    class Meta:
        unique_together = [("reservation", "space")]

class PaymentTransaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"
        FAILED = "failed", "Failed"
    reservation = models.ForeignKey(Reservation, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="PHP")
    method = models.CharField(max_length=24, default="pay_on_site")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    external_reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="parking_memberships")
    listing = models.ForeignKey(ParkingListing, on_delete=models.CASCADE, related_name="memberships")
    space = models.ForeignKey(ParkingSpace, on_delete=models.PROTECT, related_name="memberships")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    active = models.BooleanField(default=True)

class IndoorCheckpoint(models.Model):
    listing = models.ForeignKey(ParkingListing, on_delete=models.CASCADE, related_name="checkpoints")
    code = models.CharField(max_length=32)
    label = models.CharField(max_length=80)
    kind = models.CharField(max_length=16, default="aisle")
    x_m = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    y_m = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    class Meta:
        unique_together = [("listing", "code")]

class CheckpointEdge(models.Model):
    listing = models.ForeignKey(ParkingListing, on_delete=models.CASCADE, related_name="checkpoint_edges")
    from_checkpoint = models.ForeignKey(IndoorCheckpoint, on_delete=models.CASCADE, related_name="outgoing_edges")
    to_checkpoint = models.ForeignKey(IndoorCheckpoint, on_delete=models.CASCADE, related_name="incoming_edges")
    distance_m = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("10"))
    instruction = models.CharField(max_length=120, blank=True)
    bidirectional = models.BooleanField(default=True)

class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=120)
    message = models.TextField()
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=80)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

class UsageEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    listing = models.ForeignKey(ParkingListing, null=True, blank=True, on_delete=models.SET_NULL)
    event = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)
