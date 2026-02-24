import sys
import os
# Add parent directory to sys.path to find 'common'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jobCollectionWebApi.core.celery_app import celery_app
from config import settings

# Register Signal Handlers (Logging)
import core.celery_events
core.celery_events.setup()

if __name__ == "__main__":
    celery_app.start()
