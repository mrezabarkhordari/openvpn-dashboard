"""
Django settings for the OpenVPN Dashboard project.

This settings file supports both development and production (Docker) deployments
through environment variables.

For local development:
    - Set DEBUG=True
    - Uses default SQLite in project directory

For Docker/Production:
    - Set environment variables (see config.config for full list)
    - Uses SQLite in /app/data/ (mounted volume)
    - Static files collected to /app/staticfiles/

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/
"""

import os
from pathlib import Path

# Import configuration module
from .config import get_config, get_env_bool, get_env_list

# Get configuration
config = get_config()

# Repo root (config/settings.py -> config/ -> repo)
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config.app.secret_key

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config.app.debug

ALLOWED_HOSTS = config.app.allowed_hosts


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'openvpn_dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Serve static files
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': config.app.database_path,
    }
}


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = config.app.time_zone

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = config.app.static_root

# WhiteNoise configuration for serving static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Authentication settings
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'account_list'
LOGOUT_REDIRECT_URL = 'login'


# OpenVPN Configuration
# These settings are used by services.utils and services.openvpn_manager
OPENVPN_CONFIG = config.openvpn.to_dict()


# CSRF Configuration for reverse proxy
if config.app.csrf_trusted_origins:
    CSRF_TRUSTED_ORIGINS = config.app.csrf_trusted_origins


# Security settings for production
if not DEBUG:
    # HTTPS settings
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = get_env_bool('SESSION_COOKIE_SECURE', True)
    CSRF_COOKIE_SECURE = get_env_bool('CSRF_COOKIE_SECURE', True)

    # HSTS settings (enable if using HTTPS)
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = get_env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', False)
    SECURE_HSTS_PRELOAD = get_env_bool('SECURE_HSTS_PRELOAD', False)


# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': config.app.log_level,
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': config.app.log_level,
            'propagate': False,
        },
        'openvpn_dashboard': {
            'handlers': ['console'],
            'level': config.app.log_level,
            'propagate': False,
        },
        'usage_collector': {
            'handlers': ['console'],
            'level': config.app.log_level,
            'propagate': False,
        },
    },
}
