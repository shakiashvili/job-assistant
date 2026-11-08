import logging
from typing import List
from fastapi import APIRouter, HTTPException
from ..models.schemas import ApplicationItem, ApplicationCreate, ApplicationUpdate
from ..storage.tracker_store import tracker_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/applications", tags=["Application Tracker"])


@router.get("", response_model=List[ApplicationItem])
def list_applications():
    """Lists all tracked job applications (Saved, Applied, Interviewing, Rejected)."""
    return tracker_store.get_all()


@router.post("", response_model=ApplicationItem)
def create_application(item: ApplicationCreate):
    """Adds a new application to the tracker board."""
    try:
        return tracker_store.create(item)
    except Exception as e:
        logger.error(f"Error creating application: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{app_id}", response_model=ApplicationItem)
def update_application(app_id: str, item_update: ApplicationUpdate):
    """Updates status, notes, or details for an application."""
    updated = tracker_store.update(app_id, item_update)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return updated


@router.delete("/{app_id}")
def delete_application(app_id: str):
    """Removes an application from tracking."""
    deleted = tracker_store.delete(app_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return {"status": "success", "message": f"Application {app_id} deleted"}
