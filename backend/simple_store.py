"""Simple in-memory store implementation for ChatKit."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from chatkit.store import Store, StoreItemType
from chatkit.types import Page, Thread, ThreadItem, ThreadMetadata


class SimpleStore(Store[dict[str, Any]]):
    """Simple in-memory implementation of the ChatKit Store protocol."""

    def __init__(self):
        self.threads: dict[str, ThreadMetadata] = {}
        self.thread_items: dict[str, list[ThreadItem]] = {}
        self.items_by_id: dict[str, ThreadItem] = {}
        self.attachments: dict[str, Any] = {}

    async def save_thread(self, thread: ThreadMetadata, context: dict[str, Any]) -> None:
        """Save or update a thread."""
        self.threads[thread.id] = thread
        if thread.id not in self.thread_items:
            self.thread_items[thread.id] = []

    async def load_thread(self, thread_id: str, context: dict[str, Any]) -> ThreadMetadata:
        """Load a thread by ID, or raise if not found."""
        thread = self.threads.get(thread_id)
        if thread is None:
            # You can define your own exception, or use a built-in one.
            raise KeyError(f"Thread with id '{thread_id}' not found")
        return thread

    async def load_threads(
        self,
        limit: int,
        after: str | None,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadMetadata]:
        """Load a page of threads."""
        threads = list(self.threads.values())
        
        # Simple pagination
        if order == "desc":
            threads.sort(key=lambda t: t.created_at, reverse=True)
        else:
            threads.sort(key=lambda t: t.created_at)

        paged_threads = threads[:limit]
        return Page(data=paged_threads, has_more=len(threads) > limit)

    async def delete_thread(self, thread_id: str, context: dict[str, Any]) -> bool:
        """Delete a thread and all its items."""
        if thread_id in self.threads:
            del self.threads[thread_id]
            if thread_id in self.thread_items:
                # Remove items from items_by_id
                for item in self.thread_items[thread_id]:
                    self.items_by_id.pop(item.id, None)
                del self.thread_items[thread_id]
            return True
        return False

    async def save_item(
        self, thread_id: str, item: ThreadItem, context: dict[str, Any]
    ) -> None:
        """Save a thread item."""
        if thread_id not in self.thread_items:
            self.thread_items[thread_id] = []
        self.thread_items[thread_id].append(item)
        self.items_by_id[item.id] = item

    async def add_thread_item(
        self, thread_id: str, item: ThreadItem, context: dict[str, Any]
    ) -> None:
        """Add a thread item (alias for save_item)."""
        await self.save_item(thread_id, item, context)

    async def load_item(
        self, thread_id: str, item_id: str, context: dict[str, Any]
    ) -> ThreadItem | None:
        """Load a specific item."""
        return self.items_by_id.get(item_id)

    async def load_thread_items(
        self,
        thread_id: str,
        after: str | None,
        limit: int,
        order: str,
        context: dict[str, Any],
    ) -> Page[ThreadItem]:
        """Load thread items."""
        items = self.thread_items.get(thread_id, [])
        
        if order == "desc":
            items = list(reversed(items))
        
        return Page(data=items[:limit], has_more=len(items) > limit)

    async def delete_item(
        self, thread_id: str, item_id: str, context: dict[str, Any]
    ) -> bool:
        """Delete a specific thread item."""
        if thread_id in self.thread_items:
            items = self.thread_items[thread_id]
            self.thread_items[thread_id] = [item for item in items if item.id != item_id]
            self.items_by_id.pop(item_id, None)
            return True
        return False

    async def delete_thread_item(
        self, thread_id: str, item_id: str, context: dict[str, Any]
    ) -> bool:
        """Delete a thread item (alias for delete_item)."""
        return await self.delete_item(thread_id, item_id, context)

    async def save_attachment(
        self, attachment: Any, context: dict[str, Any]
    ) -> None:
        """Save an attachment."""
        if hasattr(attachment, 'id'):
            self.attachments[attachment.id] = attachment

    async def load_attachment(
        self, attachment_id: str, context: dict[str, Any]
    ) -> Any | None:
        """Load an attachment."""
        return self.attachments.get(attachment_id)

    async def delete_attachment(
        self, attachment_id: str, context: dict[str, Any]
    ) -> bool:
        """Delete an attachment."""
        if attachment_id in self.attachments:
            del self.attachments[attachment_id]
            return True
        return False

    def generate_id(self, item_type: StoreItemType) -> str:
        """Generate a unique ID for an item."""
        import uuid
        return f"{item_type}_{uuid.uuid4().hex[:12]}"
