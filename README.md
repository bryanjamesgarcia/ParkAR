# ParkAR source project

ParkAR is a full-stack parking listing, reservation, provider operations, and indoor checkpoint wayfinding system. The client is an installable progressive web app. The backend is Django REST Framework with PostgreSQL in the container setup; local development can use SQLite.

## Start with Docker

1. Install Docker Desktop.
2. Copy `.env.example` to `.env` and change `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, and `BOOTSTRAP_ADMIN_PASSWORD` before first launch.
3. Run `docker compose up --build` from this folder.
4. Open `http://localhost:8000`. Sign in with the administrator email and password configured in `.env`.

The first start applies database migrations, creates the configured administrator account, collects static files, and starts the web server. PostgreSQL data is held in the `parkar-db` Docker volume. Provider and administrator accounts have separate landing dashboards and navigation.

## Start locally on Windows

Run `start-local.bat`. It creates a Python virtual environment, restores `pip` if needed, installs the packages in `requirements.txt`, creates a local SQLite database, and starts Django at `http://localhost:8000`. The script prompts for the initial administrator email and password if they are not already set in the environment.

To use a different database, set the `POSTGRES_*` environment variables before starting. The local script is for development; use Docker or a managed database for hosted operation.

## First-time setup

- Sign in as the bootstrapped administrator.
- Create a driver account from the registration screen.
- From the driver account, submit a provider application.
- From the administrator account, approve that application.
- Sign in as the approved provider, create a listing, configure its bays, rates, lot dimensions, and indoor checkpoints, then submit the listing for review.
- Approve the listing in the administrator workspace. Drivers can then find it and reserve available spaces.

## Included system areas

- Hashed-password accounts, token sign-in, driver/provider/administrator roles, account profile, vehicle profiles, provider applications, and admin verification.
- Parking listings with provider ownership, moderation status, coordinates, opening hours, cover type, and base hourly rate.
- Space and zone layout data, stable bay codes, accessibility flags, vehicle compatibility, lot dimensions, layout versions, and protection for spaces with future bookings.
- Search by name/address/city and covered/open-air type; 3D city map with location pins, building extrusion, and route line.
- Multi-vehicle reservations, motorcycle-to-space capacity grouping, vehicle/space compatibility, overlapping-booking checks inside a database transaction, server-calculated pricing, and cancellation.
- Vehicle-specific pricing rules, time windows, discounts, consolidated reservation totals, and payment records for pay-at-location or manually confirmed transfers.
- Exclusive membership assignments, in-app notifications, audit records, usage reports, and administrator account/listing views.
- Provider camera-assisted boundary review and manual measurement confirmation.
- Indoor route graph, entrance/aisle/row/bay checkpoints, printable QR markers, QR scanning on supported browsers, and a manual checkpoint selector.
- PWA manifest, install icon, and an offline-cached application shell. Booking and account changes require an online connection.

## Outdoor map and route configuration

The city map uses MapLibre GL JS and configurable vector-tile style URLs. The included defaults use OpenFreeMap for tiles and 3D building data. Route estimates call the OSRM-compatible endpoint configured by `ROUTING_BASE_URL`; the included public endpoint is suitable for evaluation only. For a real deployment, use a tile and routing service whose capacity, terms, and costs fit your expected traffic. Add valid latitude/longitude values to each listing to show it on the map and calculate routes.

Map tiles and the MapLibre module are fetched from external hosts, so that map view requires an internet connection even though the rest of the app shell can open offline. Replace `MAP_STYLE_URL` and `MAP_VECTOR_URL` with your approved tile provider before deployment.

## Indoor QR guidance setup

When a provider saves a layout, the system creates entrance, aisle junction, row, and bay checkpoints. The checkpoint screen displays and prints a QR marker for each checkpoint. Print and place the matching marker at that physical location in the lot. Drivers open **Indoor guide** from a confirmed reservation and scan a checkpoint marker; the server calculates a route from that checkpoint to the assigned bay. If camera scanning is unavailable, the driver can select the checkpoint manually.

Camera access requires `localhost` or HTTPS and user permission. Continuous indoor positioning between QR markers is not part of this web system; the driver updates position at each marker. Provider camera mapping is a visual boundary review tool. The provider must enter and confirm measured dimensions; the camera does not perform certified or device-independent measurement.

## API

All application endpoints are under `/api/v1/` and use DRF token authentication (`Authorization: Token <key>`). Main route groups include `auth/`, `me/`, `dashboard/`, `vehicles/`, `listings/`, `reservations/`, `applications/`, `memberships/`, `notifications/`, `reports/`, and `admin/users/`. Listing-specific routes cover layout, measurements, pricing rules, indoor checkpoints, moderation, and QR output. The built-in Django administration site is at `/admin/`.

## Password recovery

The sign-in screen includes **Forgot password?**. In local development, the reset email is printed in the same Command Prompt or PowerShell window that is running ParkAR. Open the one-time link there to set a new password. For hosted use, set `APP_BASE_URL`, `EMAIL_BACKEND` to Django SMTP, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` in the deployment environment. Reset requests always show a generic response so they do not reveal whether an email has an account.

## Payment operations

The application calculates reservation totals and records payment transactions. Providers can mark pay-at-location or manually transferred funds as collected and administrators can inspect the ledger. A card or e-wallet gateway is not wired in because the project plan leaves the payment provider and credentials undecided; add the selected gateway credentials and its server-side callback flow before accepting online payments.

## Security and deployment

- Keep `.env` private; it is excluded from source control and is not included in the package.
- Use unique production secrets, a private PostgreSQL instance, HTTPS, backups, and a configured trusted proxy before exposing the system publicly.
- Change the bootstrap administrator password after creating the initial account. Running bootstrap again promotes the account but does not change its existing password.
- Configure provider, map-tile, and routing operations for the actual deployment area.
- Run `python manage.py migrate` and `python manage.py collectstatic` as part of each release.

## Source tree

- `backend/config/`: Django settings, URL routing, and WSGI entry point.
- `backend/core/`: database models, migrations, permissions, serializers, booking/indoor route services, API views, and admin site.
- `backend/core/static/core/`: complete browser client, styles, PWA assets, and MapLibre setup.
- `requirements.txt`, `Dockerfile`, `compose.yaml`, and `.env.example`: install and deployment setup.
