from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from .models import (AuditLog, BoundaryPoint, CheckpointEdge, IndoorCheckpoint, Membership,
                     ParkingListing, ParkingSpace, PaymentTransaction, ProviderApplication,
                     PricingRule, Reservation, ReservationVehicle, SpaceAssignment, UserProfile, Vehicle)
from django.utils import timezone

def role_of(user):
    if user.is_superuser:
        return "admin"
    return getattr(getattr(user, "profile", None), "role", "driver")

class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "phone", "role"]
    def get_role(self, obj): return role_of(obj)
    def get_phone(self, obj): return getattr(getattr(obj, "profile", None), "phone", "")

class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=10, write_only=True)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists(): raise serializers.ValidationError("An account with this email already exists.")
        return value
    def validate_username(self,value):
        if User.objects.filter(username__iexact=value).exists():raise serializers.ValidationError("That username is already in use.")
        return value
    def validate_password(self,value):
        try:validate_password(value)
        except Exception as error:raise serializers.ValidationError(list(error.messages))
        return value
    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        UserProfile.objects.create(user=user, role=UserProfile.Role.DRIVER)
        return user

class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = ["id", "name", "category", "plate_number", "length_m", "width_m", "created_at"]
        read_only_fields = ["id", "created_at"]

class SpaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParkingSpace
        fields = ["id", "code", "status", "is_accessible", "vehicle_class", "width_m", "length_m", "grid_row", "grid_column", "layout_version"]
        read_only_fields = ["id", "layout_version"]

class ListingSerializer(serializers.ModelSerializer):
    provider_name = serializers.SerializerMethodField()
    spaces = SpaceSerializer(many=True, read_only=True)
    available_count = serializers.SerializerMethodField()
    class Meta:
        model = ParkingListing
        fields = ["id", "provider_name", "name", "description", "address", "city", "latitude", "longitude", "covered", "opening_time", "closing_time", "hourly_rate", "status", "width_m", "length_m", "current_layout_version", "spaces", "available_count", "created_at", "updated_at"]
        read_only_fields = ["id", "provider_name", "status", "current_layout_version", "spaces", "available_count", "created_at", "updated_at"]
    def get_provider_name(self, obj):
        return obj.provider.get_full_name() or obj.provider.username
    def get_available_count(self, obj):
        now=timezone.now()
        return obj.spaces.filter(status=ParkingSpace.Status.AVAILABLE).exclude(
            assignments__reservation__status=Reservation.Status.CONFIRMED,
            assignments__reservation__starts_at__lte=now,
            assignments__reservation__ends_at__gt=now,
        ).distinct().count()

class ProviderApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderApplication
        fields = ["id", "legal_name", "business_name", "contact_phone", "address", "notes", "status", "reviewed_at", "created_at"]
        read_only_fields = ["id", "status", "reviewed_at", "created_at"]

class PricingRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model=PricingRule
        fields=["id","name","vehicle_category","hourly_rate","start_time","end_time","discount_percent","active"]
        read_only_fields=["id"]
    def validate_discount_percent(self,value):
        if value<0 or value>100:raise serializers.ValidationError("Discount must be between 0 and 100 percent.")
        return value
    def validate_hourly_rate(self,value):
        if value<=0:raise serializers.ValidationError("Hourly rate must be greater than zero.")
        return value

class ReservationVehicleSerializer(serializers.ModelSerializer):
    vehicle_name = serializers.CharField(source="vehicle.name", read_only=True)
    plate_number = serializers.CharField(source="vehicle.plate_number", read_only=True)
    class Meta:
        model = ReservationVehicle
        fields = ["vehicle", "vehicle_name", "plate_number"]

class SpaceAssignmentSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source="space.code", read_only=True)
    class Meta:
        model = SpaceAssignment
        fields = ["space", "code"]

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = ["id", "amount", "currency", "method", "status", "external_reference", "created_at"]
        read_only_fields = ["id", "created_at"]

class ReservationSerializer(serializers.ModelSerializer):
    listing_name = serializers.CharField(source="listing.name", read_only=True)
    listing_address = serializers.CharField(source="listing.address", read_only=True)
    vehicles = ReservationVehicleSerializer(source="reservation_vehicles", many=True, read_only=True)
    assignments = SpaceAssignmentSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    class Meta:
        model = Reservation
        fields = ["id", "code", "listing", "listing_name", "listing_address", "starts_at", "ends_at", "status", "subtotal", "discount", "total", "vehicles", "assignments", "payments", "created_at"]
        read_only_fields = fields

class CheckpointSerializer(serializers.ModelSerializer):
    marker_value = serializers.SerializerMethodField()
    qr_image_url = serializers.SerializerMethodField()
    class Meta:
        model = IndoorCheckpoint
        fields = ["id", "code", "label", "kind", "x_m", "y_m", "marker_value", "qr_image_url"]
        read_only_fields = ["id", "marker_value"]
    def get_marker_value(self, obj): return f"PARKAR|{obj.listing_id}|{obj.code}"
    def get_qr_image_url(self,obj): return f"/api/v1/listings/{obj.listing_id}/checkpoints/{obj.code}/qr.svg"

class EdgeSerializer(serializers.ModelSerializer):
    from_code = serializers.CharField(source="from_checkpoint.code", read_only=True)
    to_code = serializers.CharField(source="to_checkpoint.code", read_only=True)
    class Meta:
        model = CheckpointEdge
        fields = ["id", "from_checkpoint", "to_checkpoint", "from_code", "to_code", "distance_m", "instruction", "bidirectional"]

class AuditSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    class Meta:
        model = AuditLog
        fields = ["id", "actor_name", "action", "object_type", "object_id", "details", "created_at"]
    def get_actor_name(self, obj): return obj.actor.username if obj.actor else "System"

