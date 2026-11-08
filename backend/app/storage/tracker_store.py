import json
import logging
import uuid
from typing import List, Dict, Any, Optional
from ..config import APPLICATIONS_FILE
from ..models.schemas import ApplicationItem, ApplicationCreate, ApplicationUpdate

logger = logging.getLogger(__name__)


class TrackerStore:
    def __init__(self, filepath=APPLICATIONS_FILE):
        self.filepath = filepath

    def get_all(self) -> List[ApplicationItem]:
        try:
            if not self.filepath.exists():
                return []
            with open(self.filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
                return [ApplicationItem(**item) for item in raw]
        except Exception as e:
            logger.error(f"Error reading applications: {e}")
            return []

    def save_all(self, items: List[ApplicationItem]) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump([item.model_dump() for item in items], f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving applications: {e}")
            raise

    def create(self, item_in: ApplicationCreate) -> ApplicationItem:
        items = self.get_all()
        new_id = f"app-{uuid.uuid4().hex[:6]}"
        item = ApplicationItem(id=new_id, **item_in.model_dump())
        items.insert(0, item)
        self.save_all(items)
        return item

    def update(self, item_id: str, item_update: ApplicationUpdate) -> Optional[ApplicationItem]:
        items = self.get_all()
        for i, item in enumerate(items):
            if item.id == item_id:
                data = item.model_dump()
                update_data = {k: v for k, v in item_update.model_dump().items() if v is not None}
                data.update(update_data)
                updated_item = ApplicationItem(**data)
                items[i] = updated_item
                self.save_all(items)
                return updated_item
        return None

    def delete(self, item_id: str) -> bool:
        items = self.get_all()
        initial_len = len(items)
        items = [item for item in items if item.id != item_id]
        if len(items) < initial_len:
            self.save_all(items)
            return True
        return False


tracker_store = TrackerStore()
