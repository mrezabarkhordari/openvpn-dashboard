# custom_filters.py

from django import template
register = template.Library()

@register.simple_tag
def get_data_in_gb(dictionary, key1, key2):
    key = key1 + key2
    bytes = dictionary.get(key)
    if bytes is not None:
        # Convert bytes to gigabytes and round to 1 decimal place
        return round(int(bytes) / (1024 ** 3), 1)
    return None

@register.filter
def url_starts_with(url_name, prefix):
    """Check if URL name starts with a given prefix"""
    if not url_name:
        return False
    return str(url_name).startswith(prefix)