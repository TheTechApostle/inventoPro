from .base import *  # noqa

DEBUG = True
ALLOWED_HOSTS = ["https://invento-pro-frontend.vercel.app", "localhost:5173", "https://inventopro-ei3c.onrender.com"]

# Disable throttling in development
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa

# Email in dev — print to console
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Simpler logging in dev
LOGGING["root"]["level"] = "DEBUG"  # noqa
