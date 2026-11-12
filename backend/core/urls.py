from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (AdminUsersView, ApplicationDecisionView, ApplicationsView,
                    CheckpointQrView, CheckpointsView, DashboardView, IndoorRouteView, LayoutView,
                    ListingModerationView, ListingViewSet, LoginView, LogoutView, PasswordResetConfirmView,
                    PasswordResetRequestView, PricingRulesView,
                    MeView, MembershipView, MeasurementView, NotificationsView, RouteView,
                    PaymentUpdateView, RegisterView, ReportsView, ReservationViewSet,
                    VehicleViewSet)

router=DefaultRouter()
router.register("vehicles",VehicleViewSet,basename="vehicle")
router.register("listings",ListingViewSet,basename="listing")
router.register("reservations",ReservationViewSet,basename="reservation")
urlpatterns=[
    path("auth/register/",RegisterView.as_view(),name="register"),
    path("auth/login/",LoginView.as_view(),name="login"),
    path("auth/password-reset/",PasswordResetRequestView.as_view(),name="password-reset-request"),
    path("auth/password-reset/confirm/",PasswordResetConfirmView.as_view(),name="password-reset-confirm"),
    path("auth/logout/",LogoutView.as_view(),name="logout"),
    path("me/",MeView.as_view(),name="me"),
    path("dashboard/",DashboardView.as_view(),name="dashboard"),
    path("applications/",ApplicationsView.as_view(),name="applications"),
    path("applications/<int:application_id>/decision/",ApplicationDecisionView.as_view(),name="application-decision"),
    path("listings/<uuid:listing_id>/layout/",LayoutView.as_view(),name="listing-layout"),
    path("listings/<uuid:listing_id>/moderate/",ListingModerationView.as_view(),name="listing-moderate"),
    path("listings/<uuid:listing_id>/checkpoints/",CheckpointsView.as_view(),name="listing-checkpoints"),
    path("listings/<uuid:listing_id>/checkpoints/<str:checkpoint_code>/",CheckpointsView.as_view(),name="listing-checkpoint-detail"),
    path("listings/<uuid:listing_id>/checkpoints/<str:checkpoint_code>/qr.svg",CheckpointQrView.as_view(),name="checkpoint-qr"),
    path("listings/<uuid:listing_id>/measurements/",MeasurementView.as_view(),name="listing-measurements"),
    path("listings/<uuid:listing_id>/pricing/",PricingRulesView.as_view(),name="listing-pricing"),
    path("listings/<uuid:listing_id>/pricing/<int:rule_id>/",PricingRulesView.as_view(),name="listing-pricing-delete"),
    path("reservations/<uuid:reservation_id>/indoor-route/",IndoorRouteView.as_view(),name="indoor-route"),
    path("payments/<int:payment_id>/status/",PaymentUpdateView.as_view(),name="payment-status"),
    path("memberships/",MembershipView.as_view(),name="memberships"),
    path("notifications/",NotificationsView.as_view(),name="notifications"),
    path("notifications/read-all/",NotificationsView.as_view(),name="notifications-read-all"),
    path("notifications/<int:notification_id>/read/",NotificationsView.as_view(),name="notification-read"),
    path("admin/users/",AdminUsersView.as_view(),name="admin-users"),
    path("admin/users/<int:user_id>/",AdminUsersView.as_view(),name="admin-user-detail"),
    path("reports/",ReportsView.as_view(),name="reports"),
    path("routes/",RouteView.as_view(),name="route"),
    path("",include(router.urls)),
]
