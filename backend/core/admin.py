from django.contrib import admin
from .models import (AuditLog, BoundaryPoint, CheckpointEdge, IndoorCheckpoint, LayoutVersion,
                     Membership, Notification, ParkingListing, ParkingSpace, ParkingZone,
                     PaymentTransaction, PricingRule, ProviderApplication, Reservation,
                     ReservationVehicle, SpaceAssignment, UsageEvent, UserProfile, Vehicle)

@admin.register(ParkingListing)
class ParkingListingAdmin(admin.ModelAdmin):
    list_display=("name","provider","city","status","hourly_rate","current_layout_version")
    list_filter=("status","covered","city")
    search_fields=("name","address","provider__username")
    readonly_fields=("created_at","updated_at")

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display=("code","listing","driver","starts_at","ends_at","status","total")
    list_filter=("status","listing__city")
    search_fields=("code","driver__username","listing__name")
    readonly_fields=("code","created_at")

admin.site.register([UserProfile,Vehicle,ProviderApplication,ParkingZone,ParkingSpace,LayoutVersion,
    BoundaryPoint,PricingRule,ReservationVehicle,SpaceAssignment,PaymentTransaction,Membership,
    IndoorCheckpoint,CheckpointEdge,Notification,AuditLog,UsageEvent])
