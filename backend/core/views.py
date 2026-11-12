from datetime import timedelta
import json
import os
from urllib.error import URLError, HTTPError
from urllib.request import urlopen
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.core.mail import send_mail
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import (AuditLog, BoundaryPoint, CheckpointEdge, IndoorCheckpoint, Membership,
                     Notification, ParkingListing, ParkingSpace, PaymentTransaction,
                     ProviderApplication, Reservation, SpaceAssignment, UserProfile,
                     UsageEvent, Vehicle)
from .permissions import IsAdministrator, IsProvider
from .serializers import (AuditSerializer, CheckpointSerializer, EdgeSerializer,
                          ListingSerializer, ProviderApplicationSerializer,
                          PricingRuleSerializer, RegisterSerializer, ReservationSerializer, SpaceSerializer,
                          UserSerializer, VehicleSerializer, role_of)
from .services import build_indoor_route, create_reservation, record_audit

def app_shell(request):
    return render(request, "core/index.html", {"map_style_url":os.getenv("MAP_STYLE_URL","https://tiles.openfreemap.org/styles/bright"),"map_vector_url":os.getenv("MAP_VECTOR_URL","https://tiles.openfreemap.org/planet")})

class LoginView(APIView):
    permission_classes=[AllowAny]
    authentication_classes=[]
    def post(self, request):
        identity=request.data.get("email", "").strip()
        password=request.data.get("password", "")
        user_record=User.objects.filter(email__iexact=identity).first()
        username=user_record.username if user_record else identity
        user=authenticate(request, username=username, password=password)
        if not user: return Response({"detail":"Email or password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)
        token,_=Token.objects.get_or_create(user=user)
        return Response({"token":token.key,"user":UserSerializer(user).data})

class PasswordResetRequestView(APIView):
    permission_classes=[AllowAny]
    authentication_classes=[]
    def post(self,request):
        email=str(request.data.get("email","")).strip()
        user=User.objects.filter(email__iexact=email,is_active=True).first() if email else None
        reset_url=None
        if user and user.has_usable_password():
            uid=urlsafe_base64_encode(force_bytes(user.pk))
            token=default_token_generator.make_token(user)
            base_url=os.getenv("APP_BASE_URL","http://localhost:8000").rstrip("/")
            reset_url=f"{base_url}/?uid={uid}&token={token}"
            try:
                send_mail(
                    "Reset your ParkAR password",
                    f"Use this link to set a new ParkAR password. The link can only be used once:\n\n{reset_url}\n\nIf you did not request this, you can ignore this email.",
                    os.getenv("DEFAULT_FROM_EMAIL","ParkAR <noreply@parkar.local>"),
                    [user.email],
                    fail_silently=True,
                )
            except Exception:
                pass
        resp_data={"detail":"If an account with that email exists, password reset instructions have been sent."}
        if reset_url and (settings.DEBUG or os.getenv("EMAIL_BACKEND","").endswith("console.EmailBackend")):
            resp_data["reset_url"]=reset_url
        return Response(resp_data)

class PasswordResetConfirmView(APIView):
    permission_classes=[AllowAny]
    authentication_classes=[]
    def post(self,request):
        uid=request.data.get("uid","")
        token=request.data.get("token","")
        password=request.data.get("password","")
        if not isinstance(uid,str) or not isinstance(token,str) or not isinstance(password,str):
            return Response({"detail":"Enter a valid password reset link and password."},status=400)
        try:
            user_id=force_str(urlsafe_base64_decode(uid))
            user=User.objects.get(pk=user_id,is_active=True)
        except (TypeError,ValueError,OverflowError,User.DoesNotExist):
            return Response({"detail":"This password reset link is invalid or has expired."},status=400)
        if not token or not default_token_generator.check_token(user,token):
            return Response({"detail":"This password reset link is invalid or has expired."},status=400)
        try:
            validate_password(password,user)
        except DjangoValidationError as error:
            return Response({"password":error.messages},status=400)
        user.set_password(password)
        user.save(update_fields=["password"])
        Token.objects.filter(user=user).delete()
        return Response({"detail":"Your password has been updated. Please sign in again."})

class RegisterView(APIView):
    permission_classes=[AllowAny]
    authentication_classes=[]
    def post(self, request):
        serializer=RegisterSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        user=serializer.save(); token=Token.objects.create(user=user)
        return Response({"token":token.key,"user":UserSerializer(user).data}, status=status.HTTP_201_CREATED)

class MeView(APIView):
    def get(self,request): return Response(UserSerializer(request.user).data)
    def patch(self,request):
        for key in ("first_name","last_name"):
            if key in request.data: setattr(request.user,key,str(request.data[key])[:150])
        new_password = str(request.data.get("new_password", "")).strip()
        current_password = str(request.data.get("current_password", "")).strip()
        if new_password:
            if not request.user.check_password(current_password):
                return Response({"current_password": "Your current password is incorrect."}, status=400)
            try:
                validate_password(new_password, request.user)
            except DjangoValidationError as error:
                return Response({"new_password": error.messages}, status=400)
            request.user.set_password(new_password)
            request.user.save()
        else:
            request.user.save(update_fields=["first_name","last_name"])
        if "phone" in request.data:
            profile,_=UserProfile.objects.get_or_create(user=request.user)
            profile.phone=str(request.data["phone"])[:32]
            profile.save(update_fields=["phone"])
            request.user.profile = profile
        return Response(UserSerializer(request.user).data)

class LogoutView(APIView):
    def post(self,request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class VehicleViewSet(viewsets.ModelViewSet):
    serializer_class=VehicleSerializer
    def get_queryset(self): return Vehicle.objects.filter(owner=self.request.user)
    def perform_create(self,serializer): serializer.save(owner=self.request.user)

class ListingViewSet(viewsets.ModelViewSet):
    serializer_class=ListingSerializer
    lookup_field="id"
    def get_queryset(self):
        role=role_of(self.request.user)
        qs=ParkingListing.objects.prefetch_related("spaces")
        if role=="admin": return qs
        if role=="provider": return qs.filter(provider=self.request.user)
        qs=qs.filter(status=ParkingListing.Status.ACTIVE)
        city=self.request.query_params.get("city")
        if city: qs=qs.filter(city__icontains=city)
        covered=self.request.query_params.get("covered")
        if covered in ("true","false"): qs=qs.filter(covered=(covered=="true"))
        search=self.request.query_params.get("q")
        if search: qs=qs.filter(name__icontains=search) | qs.filter(address__icontains=search) | qs.filter(city__icontains=search)
        return qs.distinct()
    def get_permissions(self):
        if self.action in ("create","update","partial_update","destroy"): return [IsProvider()]
        return [IsAuthenticated()]
    def perform_create(self,serializer):
        profile,_=UserProfile.objects.get_or_create(user=self.request.user)
        if role_of(self.request.user)!="provider" or not profile.provider_verified:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("An approved provider account is required to create a listing.")
        listing=serializer.save(provider=self.request.user,status=ParkingListing.Status.PENDING)
        try: initial_spaces=max(1,min(130,int(self.request.data.get("initial_space_count",10))))
        except (TypeError,ValueError): initial_spaces=10
        for index in range(initial_spaces):
            row=index//5;column=index%5;code=f"{_row_label(row)}{column+1}"
            ParkingSpace.objects.create(listing=listing,code=code,grid_row=row,grid_column=column)
        _ensure_default_checkpoints(listing)
        record_audit(self.request.user,"listing.created",listing)
    def perform_update(self,serializer):
        listing=serializer.save()
        record_audit(self.request.user,"listing.updated",listing)

class ListingModerationView(APIView):
    permission_classes=[IsAdministrator]
    def post(self,request,listing_id):
        listing=ParkingListing.objects.filter(pk=listing_id).first()
        if not listing:return Response({"detail":"Listing not found."},status=404)
        decision=request.data.get("decision")
        if decision not in ("approve","suspend","reject"):return Response({"decision":"Choose approve, suspend, or reject."},status=400)
        listing.status=ParkingListing.Status.ACTIVE if decision=="approve" else ParkingListing.Status.SUSPENDED if decision=="suspend" else ParkingListing.Status.DRAFT
        listing.save(update_fields=["status","updated_at"])
        Notification.objects.create(user=listing.provider,title="Parking listing reviewed",message=f"{listing.name} was {decision}d by an administrator.")
        record_audit(request.user,f"listing.{decision}d",listing)
        return Response(ListingSerializer(listing).data)

class LayoutView(APIView):
    def get(self,request,listing_id):
        listing=get_listing_for_user(request,listing_id)
        spaces_qs=listing.spaces.all()
        starts_at_str = request.query_params.get("starts_at", "").replace(" ", "+")
        ends_at_str = request.query_params.get("ends_at", "").replace(" ", "+")
        reserved_space_ids = set()
        if starts_at_str and ends_at_str:
            s_dt = parse_datetime(starts_at_str)
            e_dt = parse_datetime(ends_at_str)
            if s_dt and timezone.is_naive(s_dt): s_dt = timezone.make_aware(s_dt)
            if e_dt and timezone.is_naive(e_dt): e_dt = timezone.make_aware(e_dt)
            if s_dt and e_dt:
                reserved_space_ids = set(SpaceAssignment.objects.filter(
                    space__listing=listing,
                    reservation__status=Reservation.Status.CONFIRMED,
                    reservation__starts_at__lt=e_dt,
                    reservation__ends_at__gt=s_dt
                ).values_list("space_id", flat=True))
        serialized_spaces=[]
        for sp in spaces_qs:
            data=SpaceSerializer(sp).data
            if sp.id in reserved_space_ids:
                data["slot_status"]="reserved"
            elif sp.status==ParkingSpace.Status.BLOCKED:
                data["slot_status"]="blocked"
            else:
                data["slot_status"]="available"
            serialized_spaces.append(data)
        return Response({"listing":ListingSerializer(listing).data,"spaces":serialized_spaces,
                         "zones":list(listing.zones.values("id","name","order")),"boundary_points":list(listing.boundary_points.values("index","x_m","y_m"))})
    def put(self,request,listing_id):
        listing=get_listing_for_user(request,listing_id,edit=True)
        if not isinstance(request.data.get("spaces"),list): return Response({"spaces":"An array of spaces is required."},status=400)
        payload=request.data["spaces"]
        codes=[str(item.get("code","" )).strip().upper() for item in payload]
        if any(not c for c in codes) or len(set(codes))!=len(codes): return Response({"spaces":"Each space needs a unique code."},status=400)
        with transaction.atomic():
            listing=ParkingListing.objects.select_for_update().get(pk=listing.pk)
            active_assignments=SpaceAssignment.objects.filter(space__listing=listing,reservation__status=Reservation.Status.CONFIRMED,reservation__ends_at__gt=timezone.now()).select_related("space")
            active=set(active_assignments.values_list("space__code",flat=True))
            incoming=set(codes)
            if active-incoming: return Response({"spaces":f"These reserved spaces cannot be removed: {', '.join(active-incoming)}"},status=409)
            by_code={item["code"].strip().upper():item for item in payload}
            for assignment in active_assignments:
                proposed=by_code[assignment.space.code]
                if proposed.get("status","available")!="available": return Response({"spaces":f"Bay {assignment.space.code} has a future reservation and cannot be blocked."},status=409)
                protected=("vehicle_class","width_m","length_m","grid_row","grid_column")
                if any(str(proposed.get(field,getattr(assignment.space,field)))!=str(getattr(assignment.space,field)) for field in protected):
                    return Response({"spaces":f"Bay {assignment.space.code} has a future reservation and its dimensions or compatibility cannot change."},status=409)
            listing.current_layout_version+=1;listing.save(update_fields=["current_layout_version","updated_at"])
            snapshot=list(listing.spaces.values("code","status","vehicle_class","width_m","length_m","grid_row","grid_column"))
            from .models import LayoutVersion
            LayoutVersion.objects.create(listing=listing,version=listing.current_layout_version,snapshot={"spaces":snapshot},created_by=request.user)
            for i,item in enumerate(payload):
                values={"status":item.get("status","available"),"is_accessible":item.get("is_accessible",False),"vehicle_class":item.get("vehicle_class","any"),"width_m":item.get("width_m",2.5),"length_m":item.get("length_m",5),"grid_row":item.get("grid_row",i//5),"grid_column":item.get("grid_column",i%5),"layout_version":listing.current_layout_version}
                ParkingSpace.objects.update_or_create(listing=listing,code=codes[i],defaults=values)
            listing.spaces.exclude(code__in=codes).delete()
            width=request.data.get("width_m");length=request.data.get("length_m")
            if width is not None: listing.width_m=width
            if length is not None: listing.length_m=length
            listing.save(update_fields=["width_m","length_m","updated_at"])
            _ensure_default_checkpoints(listing)
            record_audit(request.user,"layout.updated",listing,{"version":listing.current_layout_version,"spaces":len(codes)})
        return self.get(request,listing_id)

class RouteView(APIView):
    def get(self,request):
        try:
            origin_lat=float(request.query_params["origin_lat"]);origin_lon=float(request.query_params["origin_lon"])
            listing=ParkingListing.objects.get(pk=request.query_params["listing_id"],status=ParkingListing.Status.ACTIVE)
        except (KeyError,ValueError,ParkingListing.DoesNotExist):return Response({"detail":"Provide a valid active listing and origin coordinates."},status=400)
        if listing.latitude is None or listing.longitude is None:return Response({"detail":"This listing needs verified map coordinates."},status=409)
        base=os.getenv("ROUTING_BASE_URL","https://router.project-osrm.org/route/v1/driving").rstrip("/")
        url=f"{base}/{origin_lon},{origin_lat};{listing.longitude},{listing.latitude}?overview=full&geometries=geojson"
        try:
            with urlopen(url,timeout=8) as response: data=json.loads(response.read().decode("utf-8"))
            route=data["routes"][0]
            UsageEvent.objects.create(user=request.user,listing=listing,event="route.requested")
            return Response({"listing_id":str(listing.pk),"distance_m":route["distance"],"duration_s":route["duration"],"geometry":route["geometry"],"source":"OSRM"})
        except (URLError,HTTPError,TimeoutError,KeyError,IndexError,ValueError):
            return Response({"detail":"The routing service is unavailable. Configure ROUTING_BASE_URL or open directions in your map app."},status=503)

class ApplicationsView(APIView):
    def get_permissions(self): return [IsAuthenticated()]
    def get(self,request):
        if role_of(request.user)=="admin": qs=ProviderApplication.objects.select_related("user").order_by("created_at")
        else: qs=ProviderApplication.objects.filter(user=request.user).order_by("-created_at")
        return Response([dict(ProviderApplicationSerializer(a).data,user_email=a.user.email,user_name=a.user.get_full_name() or a.user.username) for a in qs])
    def post(self,request):
        if role_of(request.user)=="admin": return Response({"detail":"Administrators cannot apply as providers."},status=400)
        if ProviderApplication.objects.filter(user=request.user,status=ProviderApplication.Status.PENDING).exists(): return Response({"detail":"A provider application is already awaiting review."},status=409)
        s=ProviderApplicationSerializer(data=request.data);s.is_valid(raise_exception=True);app=s.save(user=request.user)
        record_audit(request.user,"provider_application.submitted",app)
        return Response(ProviderApplicationSerializer(app).data,status=201)

class ApplicationDecisionView(APIView):
    permission_classes=[IsAdministrator]
    def post(self,request,application_id):
        app=ProviderApplication.objects.select_related("user").filter(pk=application_id).first()
        if not app: return Response({"detail":"Application not found."},status=404)
        decision=request.data.get("decision")
        if decision not in ("approve","reject"): return Response({"decision":"Choose approve or reject."},status=400)
        app.status=ProviderApplication.Status.APPROVED if decision=="approve" else ProviderApplication.Status.REJECTED
        app.reviewed_by=request.user;app.reviewed_at=timezone.now();app.save(update_fields=["status","reviewed_by","reviewed_at"])
        if decision=="approve":
            profile,_=UserProfile.objects.get_or_create(user=app.user);profile.role=UserProfile.Role.PROVIDER;profile.provider_verified=True;profile.save(update_fields=["role","provider_verified"])
        Notification.objects.create(user=app.user,title="Provider application reviewed",message=f"Your application was {app.status}.")
        record_audit(request.user,f"provider_application.{decision}d",app)
        return Response(ProviderApplicationSerializer(app).data)

class ReservationViewSet(viewsets.ViewSet):
    def list(self,request):
        role=role_of(request.user)
        qs=Reservation.objects.select_related("listing").prefetch_related("reservation_vehicles__vehicle","assignments__space","payments")
        qs=qs.filter(listing__provider=request.user) if role=="provider" else qs if role=="admin" else qs.filter(driver=request.user)
        return Response(ReservationSerializer(qs,many=True).data)
    def create(self,request):
        serializer=ReservationCreateSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        reservation=create_reservation(user=request.user,**serializer.validated_data)
        return Response(ReservationSerializer(reservation).data,status=201)
    @action(detail=True,methods=["post"])
    @transaction.atomic
    def cancel(self,request,pk=None):
        reservation=Reservation.objects.select_for_update().filter(pk=pk).first()
        if not reservation: return Response({"detail":"Reservation not found."},status=404)
        if reservation.driver_id!=request.user.id and reservation.listing.provider_id!=request.user.id and role_of(request.user)!="admin": return Response({"detail":"You cannot cancel this reservation."},status=403)
        if reservation.status!=Reservation.Status.CONFIRMED: return Response({"detail":"Only confirmed reservations can be cancelled."},status=409)
        if reservation.starts_at<=timezone.now(): return Response({"detail":"Reservations already in progress cannot be cancelled here."},status=409)
        reservation.status=Reservation.Status.CANCELLED;reservation.cancelled_at=timezone.now();reservation.save(update_fields=["status","cancelled_at"])
        record_audit(request.user,"reservation.cancelled",reservation)
        return Response(ReservationSerializer(reservation).data)
    @action(detail=True,methods=["get"])
    def ticket(self,request,pk=None):
        import qrcode
        from qrcode.image.svg import SvgPathImage
        reservation=Reservation.objects.select_related("listing").prefetch_related("reservation_vehicles__vehicle","assignments__space","payments").filter(pk=pk).first()
        if not reservation: return Response({"detail":"Reservation not found."},status=404)
        if reservation.driver_id!=request.user.id and reservation.listing.provider_id!=request.user.id and role_of(request.user)!="admin":
            return Response({"detail":"You cannot view this ticket."},status=403)
        qr=qrcode.QRCode(version=None,error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=6,border=2,image_factory=SvgPathImage)
        qr.add_data(f"PARKAR|PASS|{reservation.code}|{reservation.id}");qr.make(fit=True)
        svg=qr.make_image().to_string(encoding="unicode")
        data=ReservationSerializer(reservation).data
        data["pass_qr_svg"]=svg
        return Response(data)

class ReservationCreateSerializer(serializers.Serializer):
    listing_id=serializers.UUIDField()
    vehicle_ids=serializers.ListField(child=serializers.IntegerField(),allow_empty=False)
    starts_at=serializers.DateTimeField()
    ends_at=serializers.DateTimeField()
    payment_method=serializers.ChoiceField(choices=["pay_on_site","manual_transfer"],default="pay_on_site")

class IndoorRouteView(APIView):
    def get(self,request,reservation_id):
        reservation=Reservation.objects.select_related("listing").prefetch_related("assignments__space").filter(pk=reservation_id).first()
        if not reservation: return Response({"detail":"Reservation not found."},status=404)
        if reservation.driver_id!=request.user.id and reservation.listing.provider_id!=request.user.id and role_of(request.user)!="admin": return Response({"detail":"You cannot view this route."},status=403)
        if reservation.status!=Reservation.Status.CONFIRMED: return Response({"detail":"Only confirmed reservations have an active guide."},status=409)
        target=reservation.assignments.select_related("space").first()
        if not target: return Response({"detail":"This booking has no assigned space."},status=409)
        start=request.query_params.get("from","ENTRANCE")
        try: route=build_indoor_route(reservation.listing,start,target.space.code)
        except Exception as e:
            from rest_framework.exceptions import ValidationError
            if isinstance(e,ValidationError): raise
            return Response({"detail":"Could not calculate an indoor route."},status=400)
        route["reservation_code"]=reservation.code
        return Response(route)

class CheckpointsView(APIView):
    def get(self,request,listing_id):
        listing=get_listing_for_user(request,listing_id)
        return Response({"checkpoints":CheckpointSerializer(listing.checkpoints.all(),many=True).data,"edges":EdgeSerializer(listing.checkpoint_edges.select_related("from_checkpoint","to_checkpoint"),many=True).data})
    def post(self,request,listing_id):
        listing=get_listing_for_user(request,listing_id,edit=True)
        action=request.data.get("action")
        if action=="checkpoint":
            s=CheckpointSerializer(data=request.data.get("checkpoint",{}));s.is_valid(raise_exception=True)
            checkpoint=IndoorCheckpoint.objects.create(listing=listing,**s.validated_data)
            record_audit(request.user,"indoor_checkpoint.created",checkpoint)
            return Response(CheckpointSerializer(checkpoint).data,status=201)
        if action=="connect":
            source=IndoorCheckpoint.objects.filter(listing=listing,code=request.data.get("from_code")).first()
            target=IndoorCheckpoint.objects.filter(listing=listing,code=request.data.get("to_code")).first()
            if not source or not target:return Response({"detail":"Both checkpoints must belong to this listing."},status=400)
            edge,created=CheckpointEdge.objects.get_or_create(listing=listing,from_checkpoint=source,to_checkpoint=target,defaults={"distance_m":request.data.get("distance_m",10),"instruction":request.data.get("instruction","Follow the signed aisle."),"bidirectional":request.data.get("bidirectional",True)})
            return Response(EdgeSerializer(edge).data,status=201 if created else 200)
        return Response({"action":"Use checkpoint or connect."},status=400)
    def delete(self,request,listing_id,checkpoint_code=None):
        listing=get_listing_for_user(request,listing_id,edit=True)
        if not checkpoint_code:
            return Response({"detail":"Checkpoint code required."}, status=400)
        checkpoint=IndoorCheckpoint.objects.filter(listing=listing,code=checkpoint_code).first()
        if not checkpoint:
            return Response({"detail":"Checkpoint not found."}, status=404)
        record_audit(request.user,"indoor_checkpoint.deleted",checkpoint,{"code":checkpoint.code})
        checkpoint.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class CheckpointQrView(APIView):
    permission_classes=[]
    authentication_classes=[]
    def get(self,request,listing_id,checkpoint_code):
        import qrcode
        from qrcode.image.svg import SvgPathImage
        checkpoint=IndoorCheckpoint.objects.filter(listing_id=listing_id,code=checkpoint_code).first()
        if not checkpoint:return Response({"detail":"Checkpoint not found."},status=404)
        qr=qrcode.QRCode(version=None,error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=8,border=4,image_factory=SvgPathImage)
        qr.add_data(f"PARKAR|{listing_id}|{checkpoint.code}");qr.make(fit=True)
        svg=qr.make_image().to_string(encoding="unicode").encode("utf-8")
        response=HttpResponse(svg,content_type="image/svg+xml")
        response["Cache-Control"]="public, max-age=3600"
        return response

class MeasurementView(APIView):
    def post(self,request,listing_id):
        listing=get_listing_for_user(request,listing_id,edit=True)
        width=request.data.get("width_m");length=request.data.get("length_m");source=request.data.get("source","manual")
        if source not in ("manual","camera_estimate"):return Response({"source":"Invalid measurement source."},status=400)
        try:width=float(width);length=float(length)
        except (TypeError,ValueError):return Response({"detail":"Valid width_m and length_m values are required."},status=400)
        if width<=0 or length<=0:return Response({"detail":"Dimensions must be greater than zero."},status=400)
        from .models import MeasurementRecord
        record=MeasurementRecord.objects.create(listing=listing,source=source,width_m=width,length_m=length,confirmed_by=request.user,notes=str(request.data.get("notes",""))[:1000])
        listing.width_m=width;listing.length_m=length;listing.save(update_fields=["width_m","length_m","updated_at"])
        record_audit(request.user,"measurement.confirmed",record,{"source":source})
        return Response({"id":record.id,"source":record.source,"width_m":record.width_m,"length_m":record.length_m,"confirmed_at":record.created_at},status=201)

class PricingRulesView(APIView):
    def get(self,request,listing_id):
        listing=get_listing_for_user(request,listing_id)
        return Response(PricingRuleSerializer(listing.pricing_rules.order_by("name"),many=True).data)
    def post(self,request,listing_id):
        listing=get_listing_for_user(request,listing_id,edit=True)
        serializer=PricingRuleSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        rule=serializer.save(listing=listing)
        record_audit(request.user,"pricing_rule.created",rule)
        return Response(PricingRuleSerializer(rule).data,status=201)
    def delete(self,request,listing_id,rule_id):
        listing=get_listing_for_user(request,listing_id,edit=True)
        rule=listing.pricing_rules.filter(pk=rule_id).first()
        if not rule:return Response(status=404)
        record_audit(request.user,"pricing_rule.deleted",rule);rule.delete()
        return Response(status=204)

class PaymentUpdateView(APIView):
    def post(self,request,payment_id):
        payment=PaymentTransaction.objects.select_related("reservation__listing").filter(pk=payment_id).first()
        if not payment:return Response({"detail":"Payment record not found."},status=404)
        if payment.reservation.listing.provider_id!=request.user.id and role_of(request.user)!="admin":return Response({"detail":"Only the listing provider can update payment records."},status=403)
        action=request.data.get("status")
        if action not in ("paid","refunded","failed"):return Response({"status":"Set paid, refunded, or failed."},status=400)
        payment.status=action;payment.external_reference=str(request.data.get("reference",""))[:120];payment.save(update_fields=["status","external_reference"])
        record_audit(request.user,"payment.status_updated",payment,{"status":action})
        return Response({"id":payment.id,"status":payment.status,"amount":payment.amount,"currency":payment.currency})

class MembershipView(APIView):
    def get(self,request):
        qs=Membership.objects.select_related("listing","space")
        if role_of(request.user)=="driver":qs=qs.filter(user=request.user)
        elif role_of(request.user)=="provider":qs=qs.filter(listing__provider=request.user)
        return Response([{"id":m.id,"user":m.user.username,"listing":str(m.listing_id),"listing_name":m.listing.name,"space":m.space.code,"starts_at":m.starts_at,"ends_at":m.ends_at,"active":m.active} for m in qs])
    def post(self,request):
        listing=get_listing_for_user(request,request.data.get("listing_id"),edit=True)
        space=ParkingSpace.objects.filter(listing=listing,code=request.data.get("space_code")).first()
        user=User.objects.filter(pk=request.data.get("user_id")).first()
        if not space or not user:return Response({"detail":"A valid space and customer are required."},status=400)
        start=parse_datetime(str(request.data.get("starts_at","")));end=parse_datetime(str(request.data.get("ends_at","")))
        if not start or not end:return Response({"detail":"Provide valid ISO 8601 membership dates."},status=400)
        if timezone.is_naive(start):start=timezone.make_aware(start)
        if timezone.is_naive(end):end=timezone.make_aware(end)
        if end<=start:return Response({"detail":"Membership end must follow its start."},status=400)
        if Membership.objects.filter(space=space,active=True,starts_at__lt=end,ends_at__gt=start).exists():return Response({"detail":"This space has an overlapping exclusive allocation."},status=409)
        membership=Membership.objects.create(user=user,listing=listing,space=space,starts_at=start,ends_at=end)
        record_audit(request.user,"membership.created",membership)
        return Response({"id":membership.id,"listing":listing.name,"space":space.code,"user":user.username},status=201)

class NotificationsView(APIView):
    def get(self,request):
        return Response(list(request.user.notifications.order_by("-created_at").values("id","title","message","read_at","created_at")[:100]))
    def post(self,request,notification_id=None):
        if notification_id:
            item=request.user.notifications.filter(pk=notification_id).first()
            if not item:return Response(status=404)
            item.read_at=timezone.now();item.save(update_fields=["read_at"])
            return Response({"id":item.id,"read_at":item.read_at})
        request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response(status=204)

class DashboardView(APIView):
    def get(self,request):
        role=role_of(request.user)
        listings=ParkingListing.objects.all() if role=="admin" else ParkingListing.objects.filter(provider=request.user) if role=="provider" else ParkingListing.objects.filter(status=ParkingListing.Status.ACTIVE)
        bookings=Reservation.objects.select_related("listing").prefetch_related("reservation_vehicles__vehicle","assignments__space","payments")
        if role=="provider":bookings=bookings.filter(listing__provider=request.user)
        elif role!="admin":bookings=bookings.filter(driver=request.user)
        apps=ProviderApplication.objects.select_related("user").all() if role=="admin" else ProviderApplication.objects.filter(user=request.user)
        application_data=[dict(ProviderApplicationSerializer(app).data,user_email=app.user.email,user_name=app.user.get_full_name() or app.user.username) for app in apps]
        return Response({"user":UserSerializer(request.user).data,"vehicles":VehicleSerializer(Vehicle.objects.filter(owner=request.user),many=True).data,
            "listings":ListingSerializer(listings.prefetch_related("spaces"),many=True).data,"reservations":ReservationSerializer(bookings,many=True).data,
            "applications":application_data,"notifications":list(request.user.notifications.order_by("-created_at").values("id","title","message","read_at","created_at")[:10]),
            "counts":{"users":User.objects.count() if role=="admin" else None,"providers":UserProfile.objects.filter(provider_verified=True).count() if role=="admin" else None,"pending_applications":ProviderApplication.objects.filter(status="pending").count() if role=="admin" else None}})

class AdminUsersView(APIView):
    permission_classes=[IsAdministrator]
    def get(self,request):
        qs=User.objects.select_related("profile").order_by("username")
        return Response([{"id":u.id,"username":u.username,"email":u.email,"role":role_of(u),"active":u.is_active,"joined_at":u.date_joined} for u in qs])
    def post(self,request):
        email=str(request.data.get("email","")).strip().lower()
        password=str(request.data.get("password","")).strip()
        role=str(request.data.get("role","driver")).strip().lower()
        username=str(request.data.get("username","")).strip() or email
        if not email or not password:
            return Response({"detail":"Email and password are required."}, status=400)
        if len(password)<8:
            return Response({"detail":"Password must be at least 8 characters."}, status=400)
        if User.objects.filter(email__iexact=email).exists():
            return Response({"detail":"An account with this email already exists."}, status=400)
        if User.objects.filter(username__iexact=username).exists():
            username=f"{email.split('@')[0]}_{User.objects.count()+1}"
        is_admin = role == "admin"
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_staff=is_admin,
            is_superuser=is_admin
        )
        profile_role = UserProfile.Role.ADMIN if is_admin else (UserProfile.Role.PROVIDER if role=="provider" else UserProfile.Role.DRIVER)
        UserProfile.objects.create(
            user=user,
            role=profile_role,
            provider_verified=is_admin or (role=="provider")
        )
        record_audit(request.user, "admin.user_created", user)
        return Response({"id":user.id,"username":user.username,"email":user.email,"role":role_of(user),"active":user.is_active,"joined_at":user.date_joined}, status=status.HTTP_201_CREATED)
    def patch(self,request,user_id=None):
        target_user=User.objects.filter(pk=user_id).first()
        if not target_user:
            return Response({"detail":"User not found."}, status=404)
        if "active" in request.data:
            target_user.is_active=bool(request.data["active"])
            target_user.save(update_fields=["is_active"])
        if "role" in request.data:
            new_role=str(request.data["role"]).strip().lower()
            if new_role not in ("driver","provider","admin"):
                return Response({"detail":"Invalid role. Choose driver, provider, or admin."}, status=400)
            profile,_=UserProfile.objects.get_or_create(user=target_user)
            if new_role=="admin":
                target_user.is_staff=True
                target_user.is_superuser=True
                target_user.save(update_fields=["is_staff","is_superuser"])
                profile.role=UserProfile.Role.ADMIN
                profile.provider_verified=True
            elif new_role=="provider":
                target_user.is_staff=False
                target_user.is_superuser=False
                target_user.save(update_fields=["is_staff","is_superuser"])
                profile.role=UserProfile.Role.PROVIDER
                profile.provider_verified=True
            else:
                target_user.is_staff=False
                target_user.is_superuser=False
                target_user.save(update_fields=["is_staff","is_superuser"])
                profile.role=UserProfile.Role.DRIVER
            profile.save(update_fields=["role","provider_verified"])
        record_audit(request.user, "admin.user_updated", target_user)
        return Response({"id":target_user.id,"username":target_user.username,"email":target_user.email,"role":role_of(target_user),"active":target_user.is_active,"joined_at":target_user.date_joined})

class ReportsView(APIView):
    def get(self,request):
        role=role_of(request.user)
        if role=="admin":qs=Reservation.objects.all();listings=ParkingListing.objects.all()
        elif role=="provider":qs=Reservation.objects.filter(listing__provider=request.user);listings=ParkingListing.objects.filter(provider=request.user)
        else:qs=Reservation.objects.filter(driver=request.user);listings=ParkingListing.objects.none()
        by_listing=qs.values("listing__name").annotate(bookings=Count("id"),revenue=Sum("total")).order_by("listing__name")
        return Response({"confirmed_bookings":qs.filter(status="confirmed").count(),"booking_value":qs.filter(status="confirmed").aggregate(total=Sum("total"))["total"] or 0,"spaces":ParkingSpace.objects.filter(listing__in=listings).count(),"by_listing":list(by_listing)})

def get_listing_for_user(request,listing_id,edit=False):
    from rest_framework.exceptions import NotFound, PermissionDenied
    listing=ParkingListing.objects.filter(pk=listing_id).first()
    if not listing: raise NotFound("Parking listing not found.")
    role=role_of(request.user)
    if edit and (role not in ("provider","admin") or (role=="provider" and listing.provider_id!=request.user.id)): raise PermissionDenied("You cannot edit this parking listing.")
    if not edit and role=="driver" and listing.status!=ParkingListing.Status.ACTIVE: raise NotFound("Parking listing not found.")
    if not edit and role=="provider" and listing.provider_id!=request.user.id and listing.status!=ParkingListing.Status.ACTIVE: raise NotFound("Parking listing not found.")
    return listing

def _row_label(index):
    label="";number=index+1
    while number:
        number,remainder=divmod(number-1,26);label=chr(65+remainder)+label
    return label

def _ensure_default_checkpoints(listing):
    entry,_=IndoorCheckpoint.objects.get_or_create(listing=listing,code="ENTRANCE",defaults={"label":"Parking entrance","kind":"entrance","x_m":0,"y_m":-12})
    junction,_=IndoorCheckpoint.objects.get_or_create(listing=listing,code="JUNCTION",defaults={"label":"Main aisle junction","kind":"aisle"})
    CheckpointEdge.objects.get_or_create(listing=listing,from_checkpoint=entry,to_checkpoint=junction,defaults={"distance_m":20,"instruction":"Enter the marked main aisle and continue to the junction."})
    CheckpointEdge.objects.get_or_create(listing=listing,from_checkpoint=junction,to_checkpoint=entry,defaults={"distance_m":20,"instruction":"Follow the aisle back toward the entrance."})
    rows={}
    for space in listing.spaces.all():
        row_label=''.join(ch for ch in space.code if ch.isalpha());row_code=f"ROW-{row_label}"
        row,created=IndoorCheckpoint.objects.get_or_create(listing=listing,code=row_code,defaults={"label":f"Row {row_label} aisle","kind":"aisle","x_m":space.grid_row*8,"y_m":10})
        rows[row_code]=row
        CheckpointEdge.objects.get_or_create(listing=listing,from_checkpoint=junction,to_checkpoint=row,defaults={"distance_m":8,"instruction":f"Continue from the main aisle to row {row_label}."})
        CheckpointEdge.objects.get_or_create(listing=listing,from_checkpoint=row,to_checkpoint=junction,defaults={"distance_m":8,"instruction":"Return to the main aisle junction."})
        bay,created=IndoorCheckpoint.objects.get_or_create(listing=listing,code=f"BAY-{space.code}",defaults={"label":f"Bay {space.code}","kind":"bay","x_m":space.grid_row*8+space.grid_column*3,"y_m":15})
        CheckpointEdge.objects.get_or_create(listing=listing,from_checkpoint=row,to_checkpoint=bay,defaults={"distance_m":5,"instruction":f"Turn into row {row_label} and follow bay numbers to {space.code}."})
        CheckpointEdge.objects.get_or_create(listing=listing,from_checkpoint=bay,to_checkpoint=row,defaults={"distance_m":5,"instruction":f"Return to row {row_label} aisle."})

