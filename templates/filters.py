# filters.py
from datetime import datetime

def datetimeformat(value, format='%b %d, %H:%M'):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except:
            return value
    if isinstance(value, datetime):
        return value.strftime(format)
    return value