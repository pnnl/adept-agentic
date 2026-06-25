"""
OpenAI-compatible pagination utilities.

Ensures all paginated responses match OpenAI's cursor-based pagination format.
"""
from typing import List, Optional, Dict, Any, TypeVar, Generic
from pydantic import BaseModel, Field
from datetime import datetime
import base64
import json

T = TypeVar('T')

class OpenAIPaginationParams(BaseModel):
    """OpenAI-compatible pagination parameters."""
    limit: Optional[int] = Field(20, description="Number of objects to return (1-100)", ge=1, le=100)
    order: Optional[str] = Field("desc", description="Sort order: 'asc' or 'desc'")
    after: Optional[str] = Field(None, description="Cursor for pagination after this object ID")
    before: Optional[str] = Field(None, description="Cursor for pagination before this object ID")

class OpenAIPaginatedResponse(BaseModel, Generic[T]):
    """OpenAI-compatible paginated response format."""
    object: str = "list"
    data: List[T]
    first_id: Optional[str] = None
    last_id: Optional[str] = None
    has_more: bool = False

class PaginationCursor:
    """Handles cursor encoding/decoding for pagination."""
    
    @staticmethod
    def encode_cursor(object_id: str, timestamp: datetime) -> str:
        """
        Encode object ID and timestamp into a cursor.
        
        OpenAI uses opaque cursors, but they're typically base64-encoded JSON.
        """
        cursor_data = {
            "id": object_id,
            "timestamp": timestamp.isoformat()
        }
        cursor_json = json.dumps(cursor_data, sort_keys=True)
        return base64.b64encode(cursor_json.encode()).decode()
    
    @staticmethod
    def decode_cursor(cursor: str) -> Dict[str, Any]:
        """Decode cursor back to object ID and timestamp."""
        try:
            cursor_json = base64.b64decode(cursor).decode()
            return json.loads(cursor_json)
        except Exception:
            raise ValueError(f"Invalid cursor: {cursor}")

class OpenAIPaginator:
    """Handles OpenAI-compatible pagination logic."""
    
    @staticmethod
    def paginate_results(
        items: List[Dict[str, Any]],
        params: OpenAIPaginationParams,
        total_count: Optional[int] = None
    ) -> OpenAIPaginatedResponse:
        """
        Apply OpenAI-compatible pagination to a list of items.
        
        Args:
            items: List of items to paginate (must have 'id' and 'created_at' fields)
            params: Pagination parameters
            total_count: Total number of items (if known)
        
        Returns:
            OpenAI-compatible paginated response
        """
        if not items:
            return OpenAIPaginatedResponse(
                data=[],
                first_id=None,
                last_id=None,
                has_more=False
            )
        
        # Sort items based on order parameter
        reverse_order = params.order == "desc"
        sorted_items = sorted(
            items, 
            key=lambda x: x.get('created_at', 0), 
            reverse=reverse_order
        )
        
        # Apply cursor filtering
        if params.after:
            try:
                after_cursor = PaginationCursor.decode_cursor(params.after)
                after_timestamp = datetime.fromisoformat(after_cursor['timestamp'])
                if reverse_order:
                    sorted_items = [
                        item for item in sorted_items 
                        if datetime.fromtimestamp(item.get('created_at', 0)) < after_timestamp
                    ]
                else:
                    sorted_items = [
                        item for item in sorted_items 
                        if datetime.fromtimestamp(item.get('created_at', 0)) > after_timestamp
                    ]
            except Exception:
                # Invalid cursor, ignore
                pass
        
        if params.before:
            try:
                before_cursor = PaginationCursor.decode_cursor(params.before)
                before_timestamp = datetime.fromisoformat(before_cursor['timestamp'])
                if reverse_order:
                    sorted_items = [
                        item for item in sorted_items 
                        if datetime.fromtimestamp(item.get('created_at', 0)) > before_timestamp
                    ]
                else:
                    sorted_items = [
                        item for item in sorted_items 
                        if datetime.fromtimestamp(item.get('created_at', 0)) < before_timestamp
                    ]
            except Exception:
                # Invalid cursor, ignore
                pass
        
        # Apply limit
        limited_items = sorted_items[:params.limit]
        
        # Determine if there are more items
        has_more = len(sorted_items) > params.limit
        
        # Get first and last IDs
        first_id = limited_items[0]['id'] if limited_items else None
        last_id = limited_items[-1]['id'] if limited_items else None
        
        return OpenAIPaginatedResponse(
            data=limited_items,
            first_id=first_id,
            last_id=last_id,
            has_more=has_more
        )

class AsyncOpenAIPaginator:
    """Async version of OpenAI paginator for database queries."""
    
    @staticmethod
    async def paginate_db_query(
        query_func,
        params: OpenAIPaginationParams,
        **query_kwargs
    ) -> OpenAIPaginatedResponse:
        """
        Apply pagination to a database query function.
        
        Args:
            query_func: Async function that returns (items, total_count)
            params: Pagination parameters
            query_kwargs: Additional arguments for query_func
        
        Returns:
            OpenAI-compatible paginated response
        """
        # Apply cursor filters to query_kwargs if needed
        if params.after:
            try:
                after_cursor = PaginationCursor.decode_cursor(params.after)
                query_kwargs['after_timestamp'] = datetime.fromisoformat(after_cursor['timestamp'])
                query_kwargs['after_id'] = after_cursor['id']
            except Exception:
                pass
        
        if params.before:
            try:
                before_cursor = PaginationCursor.decode_cursor(params.before)
                query_kwargs['before_timestamp'] = datetime.fromisoformat(before_cursor['timestamp'])
                query_kwargs['before_id'] = before_cursor['id']
            except Exception:
                pass
        
        query_kwargs['limit'] = params.limit + 1  # Get one extra to check has_more
        query_kwargs['order'] = params.order
        
        items, total_count = await query_func(**query_kwargs)
        
        # Check if there are more items
        has_more = len(items) > params.limit
        if has_more:
            items = items[:params.limit]  # Remove the extra item
        
        # Get first and last IDs
        first_id = items[0]['id'] if items else None
        last_id = items[-1]['id'] if items else None
        
        return OpenAIPaginatedResponse(
            data=items,
            first_id=first_id,
            last_id=last_id,
            has_more=has_more
        )

# Helper function for FastAPI dependency injection
def get_pagination_params(
    limit: Optional[int] = 20,
    order: Optional[str] = "desc", 
    after: Optional[str] = None,
    before: Optional[str] = None
) -> OpenAIPaginationParams:
    """FastAPI dependency for extracting pagination parameters."""
    return OpenAIPaginationParams(
        limit=limit,
        order=order,
        after=after,
        before=before
    )