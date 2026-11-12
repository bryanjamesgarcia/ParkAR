from collections import deque
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import atan2, degrees
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import (AuditLog, CheckpointEdge, IndoorCheckpoint, Membership, ParkingListing,
                     ParkingSpace, PaymentTransaction, Reservation, ReservationVehicle,
                     SpaceAssignment, UserProfile, Vehicle)

def role_of(user):
    if user.is_superuser: return "admin"
    return getattr(getattr(user, "profile", None), "role", "driver")

def record_audit(actor, action, obj, details=None):
    AuditLog.objects.create(actor=actor, action=action, object_type=obj.__class__.__name__, object_id=str(obj.pk), details=details or {})

def create_reservation(*, user, listing_id, vehicle_ids, starts_at, ends_at, payment_method="pay_on_site"):
    if starts_at <= timezone.now(): raise ValidationError({"starts_at": "Reservation start must be in the future."})
    if ends_at <= starts_at: raise ValidationError({"ends_at": "End time must be after start time."})
    if ends_at-starts_at>timedelta(hours=24): raise ValidationError({"ends_at": "A reservation cannot be longer than 24 hours."})
    if len(vehicle_ids) != len(set(vehicle_ids)) or not vehicle_ids: raise ValidationError({"vehicle_ids": "Choose one or more distinct vehicles."})
    with transaction.atomic():
        listing = ParkingListing.objects.select_for_update().get(pk=listing_id, status=ParkingListing.Status.ACTIVE)
        local_start=timezone.localtime(starts_at);local_end=timezone.localtime(ends_at)
        start_time=local_start.time();end_time=local_end.time()
        if listing.opening_time==listing.closing_time:
            inside_window=True
        elif listing.opening_time<listing.closing_time:
            inside_window=local_start.date()==local_end.date() and listing.opening_time<=start_time and end_time<=listing.closing_time
        else:
            inside_window=start_time>=listing.opening_time or end_time<=listing.closing_time
        if not inside_window:raise ValidationError({"starts_at": "The requested time falls outside the provider's opening hours."})
        vehicles = list(Vehicle.objects.filter(owner=user, id__in=vehicle_ids).order_by("id"))
        if len(vehicles) != len(vehicle_ids): raise ValidationError({"vehicle_ids": "One or more vehicles do not belong to your account."})
        overlapping = SpaceAssignment.objects.filter(space__listing=listing, reservation__status=Reservation.Status.CONFIRMED,
            reservation__starts_at__lt=ends_at, reservation__ends_at__gt=starts_at).values_list("space_id", flat=True)
        active_membership = Membership.objects.filter(listing=listing, active=True, starts_at__lt=ends_at, ends_at__gt=starts_at)
        member_space_ids = list(active_membership.exclude(user=user).values_list("space_id", flat=True))
        preferred_membership_space_ids=set(active_membership.filter(user=user).values_list("space_id",flat=True))
        eligible = ParkingSpace.objects.select_for_update().filter(listing=listing, status=ParkingSpace.Status.AVAILABLE).exclude(id__in=overlapping).exclude(id__in=member_space_ids).order_by("grid_row", "grid_column", "code")
        cars = [v for v in vehicles if v.category != Vehicle.Category.MOTORCYCLE]
        motorcycles = [v for v in vehicles if v.category == Vehicle.Category.MOTORCYCLE]
        groups = [(car, 1) for car in cars] + [(motorcycles[i:i+3], 1) for i in range(0, len(motorcycles), 3)]
        candidates = list(eligible)
        chosen = []
        rate_total = Decimal("0")
        discount_total = Decimal("0")
        hours = Decimal((ends_at - starts_at).total_seconds()) / Decimal(3600)
        for group, _ in groups:
            members = group if isinstance(group, list) else [group]
            category = members[0].category
            space = next((s for s in candidates if s.id in preferred_membership_space_ids and _space_fits(s,category)),None)
            if space is None:space=next((s for s in candidates if _space_fits(s, category)), None)
            if space is None: raise ValidationError({"availability": "There are not enough compatible spaces for the selected vehicles and time."})
            candidates.remove(space); chosen.append((space, members))
            rule = _pricing_rule(listing,category,starts_at)
            hourly = rule.hourly_rate if rule else listing.hourly_rate
            rate_total += hourly * hours
            if rule:discount_total += hourly * hours * rule.discount_percent / Decimal("100")
        subtotal = rate_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discount = min(subtotal,discount_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        reservation = Reservation.objects.create(driver=user, listing=listing, starts_at=starts_at, ends_at=ends_at,
            subtotal=subtotal, discount=discount, total=subtotal-discount)
        ReservationVehicle.objects.bulk_create([ReservationVehicle(reservation=reservation, vehicle=v) for v in vehicles])
        for space, members in chosen:
            SpaceAssignment.objects.create(reservation=reservation, space=space)
        PaymentTransaction.objects.create(reservation=reservation, amount=reservation.total, method=payment_method)
        record_audit(user, "reservation.created", reservation, {"listing": str(listing.pk), "space_codes": [s.code for s, _ in chosen]})
        from .models import Notification
        Notification.objects.create(user=user, title="Reservation confirmed", message=f"Your reservation {reservation.code} is confirmed for {listing.name}.")
        Notification.objects.create(user=listing.provider, title="New reservation", message=f"A driver reserved space at {listing.name}.")
        return reservation

def _space_fits(space, category):
    if space.vehicle_class == ParkingSpace.VehicleClass.ANY: return True
    if space.vehicle_class == ParkingSpace.VehicleClass.MOTORCYCLE: return category == Vehicle.Category.MOTORCYCLE
    if space.vehicle_class == ParkingSpace.VehicleClass.CAR: return category in (Vehicle.Category.CAR, Vehicle.Category.SUV)
    if space.vehicle_class == ParkingSpace.VehicleClass.LARGE: return category in (Vehicle.Category.SUV, Vehicle.Category.VAN)
    return False

def _pricing_rule(listing,category,starts_at):
    requested=timezone.localtime(starts_at).time()
    rules=list(listing.pricing_rules.filter(active=True).filter(Q(vehicle_category="")|Q(vehicle_category=category)))
    matching=[]
    for rule in rules:
        if rule.start_time and rule.end_time:
            if rule.start_time<=rule.end_time and not (rule.start_time<=requested<rule.end_time): continue
            if rule.start_time>rule.end_time and not (requested>=rule.start_time or requested<rule.end_time): continue
        matching.append(rule)
    return max(matching,key=lambda r:(bool(r.vehicle_category),r.discount_percent),default=None)

def build_indoor_route(listing, start_code, target_space_code):
    nodes = {n.code: n for n in listing.checkpoints.all()}
    if start_code not in nodes: raise ValidationError({"checkpoint": "Starting checkpoint does not belong to this parking lot."})
    target = f"BAY-{target_space_code}"
    if target not in nodes:
        bay = IndoorCheckpoint.objects.create(listing=listing, code=target, label=f"Bay {target_space_code}", kind="bay")
        row_label = ''.join(character for character in target_space_code if character.isalpha())
        row_code = f"ROW-{row_label}"
        row = nodes.get(row_code)
        if row:
            CheckpointEdge.objects.get_or_create(listing=listing, from_checkpoint=row, to_checkpoint=bay, defaults={"distance_m": Decimal("8"), "instruction": f"Turn into row {row_label} and follow bay numbers."})
            CheckpointEdge.objects.get_or_create(listing=listing, from_checkpoint=bay, to_checkpoint=row, defaults={"distance_m": Decimal("8"), "instruction": f"Return to row {row_label} aisle."})
        nodes[target] = bay
    adjacency = {code: [] for code in nodes}
    for edge in listing.checkpoint_edges.select_related("from_checkpoint", "to_checkpoint"):
        adjacency.setdefault(edge.from_checkpoint.code, []).append((edge.to_checkpoint.code, edge))
        if edge.bidirectional: adjacency.setdefault(edge.to_checkpoint.code, []).append((edge.from_checkpoint.code, edge))
    queue=deque([(start_code, [start_code], [])]); seen={start_code}
    while queue:
        code, path, edges = queue.popleft()
        if code == target:
            steps=[]
            for index,item in enumerate(path):
                node=nodes[item];bearing=None
                if index<len(path)-1:
                    next_node=nodes[path[index+1]]
                    dx=float(next_node.x_m-node.x_m);dy=float(next_node.y_m-node.y_m)
                    bearing=round((degrees(atan2(dx,dy))+360)%360,1)
                instruction=edges[index].instruction if index<len(edges) else "Arrive at your assigned parking bay."
                steps.append({"code":item,"label":node.label,"kind":node.kind,"instruction":instruction,"bearing_deg":bearing})
            return {"listing_id": str(listing.pk), "from": start_code, "target": target_space_code,
                    "distance_m": str(sum((e.distance_m for e in edges), Decimal("0"))),
                    "steps": steps,
                    "checkpoint_ids": path}
        for next_code, edge in adjacency.get(code, []):
            if next_code not in seen:
                seen.add(next_code); queue.append((next_code, path+[next_code], edges+[edge]))
    raise ValidationError({"route": "No indoor route connects this checkpoint to the assigned bay. Ask the provider to map the aisle connection."})

