# Inventra — Multi-Tenant Inventory & Business Operations Platform

Production-grade Django/DRF platform for inventory, sales, purchases, finance, and analytics.
Supports single businesses, multi-branch enterprises, and SaaS white-label deployments.

---

## Quick Start

```bash
# 1. Clone and setup
git clone <repo>
cd inventra
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements/development.txt

# 2. Environment
cp .env.example .env
# Edit .env with your DB, Redis credentials

# 3. Create logs directory
mkdir -p logs

# 4. Database
createdb inventra_db
python manage.py migrate

# 5. Run
python manage.py runserver

# 6. Celery worker (separate terminal)
celery -A config.celery worker --loglevel=info

# 7. Celery beat scheduler (separate terminal)
celery -A config.celery beat --loglevel=info
```

---

## Architecture

### Multi-Tenancy
Row-level tenancy via `TenantAwareModel`. Every scoped model carries a `tenant` FK.
`TenantMiddleware` resolves tenant from:
1. `X-Tenant-Slug` request header (API/mobile clients)
2. Subdomain: `acme.inventra.io` → slug=`acme`

`TenantAwareManager` auto-filters all querysets. Use `.unscoped()` only in admin/tasks.

### Service Layer
All business logic lives in service classes — never in views or models.
- `StockService` — ALL stock mutations (adjust, transfer, purchase receipt, sale)
- `SalesService` — order creation, confirmation, payment, POS
- `TenantService` — tenant onboarding
- `DashboardService` — analytics aggregation

### Permission System
JWT payload carries `role` and `permissions` list. Zero DB hits per request.
```
POST /api/v1/auth/login/  →  JWT with:
  {
    "tenant_id": "...",
    "tenant_slug": "acme",
    "role": "manager",
    "permissions": ["inventory.view", "sales.create", ...]
  }
```

---

## API Reference

Base URL: `https://{tenant}.inventra.io/api/v1/`
Auth header: `Authorization: Bearer <access_token>`
Tenant header: `X-Tenant-Slug: acme`

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login/` | Login → JWT |
| POST | `/auth/logout/` | Blacklist refresh token |
| POST | `/auth/token/refresh/` | Refresh access token |
| GET | `/auth/me/` | Current user profile |
| PATCH | `/auth/me/` | Update profile |
| POST | `/auth/change-password/` | Change password |
| GET | `/auth/roles/` | List roles |
| GET | `/auth/team/` | List team members |
| POST | `/auth/team/invite/` | Invite user |

### Tenants
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/tenants/register/` | Register new tenant |
| GET | `/tenants/me/` | Current tenant info |
| PATCH | `/tenants/me/` | Update branding |
| GET/PATCH | `/tenants/settings/` | Tenant settings |

### Inventory
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/inventory/stock/` | All stock levels |
| GET | `/inventory/stock/low_stock/` | Low stock items |
| GET | `/inventory/stock/out_of_stock/` | Zero stock |
| GET | `/inventory/stock/valuation/` | Inventory valuation |
| POST | `/inventory/stock/adjust/` | Manual adjustment |
| POST | `/inventory/stock/bulk-adjust/` | Bulk stocktake |
| GET | `/inventory/movements/` | Stock ledger |
| GET | `/inventory/movements/summary/` | Movement stats |
| POST | `/inventory/transfers/` | Create transfer |
| POST | `/inventory/transfers/{id}/confirm/` | Confirm transfer |
| POST | `/inventory/transfers/{id}/receive/` | Receive transfer |
| GET | `/inventory/batches/expiring_soon/` | Expiring batches |
| GET | `/inventory/serials/search/?q=` | Serial lookup |

### Sales
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sales/customers/` | Customer list |
| GET | `/sales/customers/{id}/orders/` | Customer orders |
| GET | `/sales/customers/{id}/statement/` | Balance statement |
| POST | `/sales/orders/` | Create order |
| GET | `/sales/orders/today/` | Today's sales |
| POST | `/sales/orders/{id}/confirm/` | Confirm + deduct stock |
| POST | `/sales/orders/{id}/pay/` | Record payment |
| POST | `/sales/orders/{id}/deliver/` | Mark delivered |
| POST | `/sales/orders/{id}/cancel/` | Cancel + reverse stock |
| POST | `/sales/pos/open/` | Open POS session |
| POST | `/sales/pos/{id}/close/` | Close POS session |
| GET | `/sales/pos/current/` | Current open session |

### Purchases
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/purchases/suppliers/` | Supplier list |
| POST | `/purchases/orders/` | Create PO |
| POST | `/purchases/orders/{id}/approve/` | Approve PO |
| POST | `/purchases/orders/{id}/receive/` | Receive goods → updates stock |
| POST | `/purchases/orders/{id}/cancel/` | Cancel PO |

### Finance
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/finance/expenses/` | Expense list |
| GET | `/finance/expenses/summary/` | Expense by category |
| POST | `/finance/expenses/{id}/submit/` | Submit for approval |
| POST | `/finance/expenses/{id}/approve/` | Approve expense |
| GET | `/finance/pl/` | P&L report |
| GET | `/finance/tax-rates/` | Tax rates |

### Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/analytics/overview/?days=30` | KPI summary |
| GET | `/analytics/revenue_trend/?days=30&group_by=day` | Revenue chart data |
| GET | `/analytics/top_products/?days=30` | Best sellers |
| GET | `/analytics/top_customers/?days=30` | Top buyers |
| GET | `/analytics/sales_by_channel/` | Channel breakdown |
| GET | `/analytics/warehouse_comparison/` | Warehouse stats |
| GET | `/analytics/stock_movement_trend/` | In/out trend |
| GET | `/analytics/inventory_aging/` | Aging analysis |

### Notifications
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/notifications/` | All notifications |
| GET | `/notifications/unread/` | Unread only |
| GET | `/notifications/count/` | Unread count |
| POST | `/notifications/{id}/read/` | Mark single read |
| POST | `/notifications/read_all/` | Mark all read |

WebSocket: `wss://{tenant}.inventra.io/ws/notifications/?token=<jwt>`

---

## Project Structure

```
inventra/
├── config/                 # Django project config
│   ├── settings/           # base, development, production
│   ├── urls.py
│   ├── asgi.py             # WebSockets
│   ├── wsgi.py
│   └── celery.py
│
├── core/                   # Shared infrastructure
│   ├── models.py           # BaseModel, TenantAwareModel
│   ├── managers.py         # TenantAwareManager + thread-locals
│   ├── middleware.py       # TenantMiddleware
│   ├── permissions.py      # RBAC permission classes
│   ├── exceptions.py       # Custom exceptions + handler
│   ├── pagination.py       # StandardPagination
│   ├── mixins.py           # ViewSet mixins
│   ├── serializers.py      # BaseModelSerializer
│   └── utils.py            # Shared utilities
│
├── apps/
│   ├── tenants/            # Tenant management + onboarding
│   ├── accounts/           # Users, roles, memberships, invitations
│   ├── warehouses/         # Warehouses, branches
│   ├── products/           # Product catalog, variants, bundles
│   ├── inventory/          # Stock levels, movements, transfers
│   │   └── services/
│   │       └── stock_service.py   ← Core engine
│   ├── sales/              # Orders, customers, POS, payments
│   │   └── services/
│   │       └── sales_service.py
│   ├── purchases/          # Suppliers, POs, goods receipt
│   ├── finance/            # Expenses, P&L, tax rates
│   ├── analytics/          # Dashboards, KPIs, trends
│   │   └── services/
│   │       └── dashboard_service.py
│   ├── notifications/      # In-app, email, WebSocket
│   └── audit/              # Immutable audit trail
│
├── requirements/
│   ├── base.txt
│   ├── development.txt
│   └── production.txt
│
├── .env.example
├── manage.py
├── gunicorn.conf.py
├── nginx.conf
└── pytest.ini
```

---

## Key Rules for Developers

1. **NEVER write to StockLevel directly** — always use `StockService.adjust_stock()`
2. **NEVER skip TenantMiddleware** — all tenant-scoped views need `TenantPermission`
3. **Business logic belongs in services**, not views or models
4. **StockMovement records are immutable** — never update them after creation
5. **Use `.unscoped()` only in** Celery tasks, management commands, and admin
6. **JWT permissions are read from payload** — adding new permissions requires re-login
7. **All financial calculations use Decimal**, never float

---

## Running Tests

```bash
pytest
pytest apps/inventory/         # single app
pytest --cov-report=html       # HTML coverage report
```

---

## Production Deployment

```bash
# Collect static
python manage.py collectstatic --noinput

# Run migrations
python manage.py migrate

# Start Gunicorn (HTTP)
gunicorn -c gunicorn.conf.py config.wsgi:application

# Start Daphne (WebSockets)
daphne -b 0.0.0.0 -p 8001 config.asgi:application

# Start Celery worker
celery -A config.celery worker --concurrency=4 --loglevel=info

# Start Celery beat
celery -A config.celery beat --loglevel=info

# Configure Nginx with nginx.conf
```
