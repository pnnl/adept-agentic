"""
Enhanced Session Navigator Component for Streamlit (Phase 2)

Provides advanced UI for browsing, filtering, sorting, and managing conversation sessions
with performance optimizations using Phase 2 database indexes.

Features:
- Table-based session view (replaces dropdown)
- Advanced filtering (status, date range, tags, cost/token thresholds, search)
- Multi-column sorting (cost, tokens, date, title)
- Pagination with configurable page size
- Batch queries to avoid N+1 problem
- Inline actions (rename, archive, delete)
- Manual and auto-refresh
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from sqlalchemy import and_, asc, cast, desc, func, or_, select, text, Text
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.orm import Session as SQLAlchemySession

from agentic_framework_pkg.logger_config import get_logger
from agentic_framework_pkg.orchestration_service.models.session_models import (
    SessionMessage,
    UserSession,
)
from agentic_framework_pkg.orchestration_service.persistence.checkpointing import (
    get_async_session,
)

logger = get_logger(__name__)


class SortColumn(str, Enum):
    """Sort column options for session table."""

    CREATED_AT = "created_at"
    LAST_ACTIVE = "last_active_at"
    COST = "estimated_cost_usd"
    TOKENS = "total_tokens"
    TITLE = "title"


class SortOrder(str, Enum):
    """Sort order options."""

    ASC = "asc"
    DESC = "desc"


@dataclass
class SessionFilters:
    """
    Filter criteria for session queries.

    All filters are optional and combine with AND logic.
    """

    status: Optional[List[str]] = None  # ["active", "archived"]
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    tags: Optional[List[str]] = None  # Must have ALL tags (AND logic)
    search_text: Optional[str] = None  # Fuzzy search in session_id + title + summary
    min_cost: Optional[float] = None
    max_cost: Optional[float] = None
    min_tokens: Optional[int] = None
    max_tokens: Optional[int] = None


@dataclass
class PaginationParams:
    """Pagination parameters for query results."""

    page: int = 1  # 1-indexed
    page_size: int = 20  # Default page size
    total_count: int = 0  # Total results (for pagination UI)

    @property
    def offset(self) -> int:
        """Calculate SQL OFFSET from page number."""
        return (self.page - 1) * self.page_size

    @property
    def total_pages(self) -> int:
        """Calculate total pages from count."""
        if self.total_count == 0:
            return 0
        return (self.total_count + self.page_size - 1) // self.page_size


class EnhancedSessionNavigator:
    """
    Enhanced session navigator with table UI, filtering, sorting, and pagination.

    Replaces Phase 1 dropdown UI with full-featured table interface.
    Leverages Phase 2 database indexes for performance.
    """

    def __init__(self, user_id: str, username: str):
        """
        Initialize EnhancedSessionNavigator.

        Args:
            user_id: User identifier (extracted from JWT token or username)
            username: Username from Keycloak authentication
        """
        self.user_id = user_id
        self.username = username

    @staticmethod
    def _toggle_session_selection(session_id: str) -> None:
        """Callback to toggle individual session selection."""
        if session_id in st.session_state.selected_sessions:
            st.session_state.selected_sessions.remove(session_id)
        else:
            st.session_state.selected_sessions.append(session_id)

    @staticmethod
    def _toggle_select_all() -> None:
        """Callback to toggle select all sessions."""
        # Check the NEW checkbox value (after toggle)
        select_all_checked = st.session_state.select_all_header
        all_session_ids = st.session_state._current_page_sessions

        if select_all_checked:
            # Checkbox is now checked - select all
            for sid in all_session_ids:
                if sid not in st.session_state.selected_sessions:
                    st.session_state.selected_sessions.append(sid)
                # Update individual checkbox key for immediate visual feedback
                st.session_state[f"select_{sid}"] = True
        else:
            # Checkbox is now unchecked - deselect all
            for sid in all_session_ids:
                if sid in st.session_state.selected_sessions:
                    st.session_state.selected_sessions.remove(sid)
                # Update individual checkbox key for immediate visual feedback
                st.session_state[f"select_{sid}"] = False

    def render(self) -> None:
        """
        Render enhanced session navigation UI in Streamlit.

        This is the synchronous entry point for Streamlit. It wraps the async
        implementation with asyncio.run() to handle database queries.
        """
        try:
            asyncio.run(self._render_async())
        except Exception as e:
            logger.error(
                f"Failed to render enhanced session navigator: {e}", exc_info=True
            )
            st.error("Failed to load session navigator. Please try again.")

    async def _render_async(self) -> None:
        """
        Async implementation of enhanced session navigation UI rendering.

        Phase 2 features:
        - Table view with sortable columns
        - Advanced filters (status, date range, tags, cost/tokens, search)
        - Pagination with page size selector
        - Inline actions (rename, archive, delete)
        - Manual and auto-refresh
        """
        # Handle pending actions (rename, archive, delete)
        await self._handle_pending_actions()

        # Initialize session state for filters and pagination
        if "session_filters" not in st.session_state:
            st.session_state.session_filters = SessionFilters(
                status=["active"]  # Default to active sessions only
            )
        if "pagination" not in st.session_state:
            st.session_state.pagination = PaginationParams(page=1, page_size=20)
        if "sort_column" not in st.session_state:
            st.session_state.sort_column = SortColumn.LAST_ACTIVE
        if "sort_order" not in st.session_state:
            st.session_state.sort_order = SortOrder.DESC
        if "selected_sessions" not in st.session_state:
            st.session_state.selected_sessions = []  # List of selected session_ids

        # Render filter controls
        self._render_filter_controls()

        # Render refresh controls
        self._render_refresh_controls()

        # Render bulk action buttons
        self._render_bulk_actions()

        # Query filtered and sorted sessions
        filters = st.session_state.session_filters
        pagination = st.session_state.pagination
        sort_col = st.session_state.sort_column
        sort_order = st.session_state.sort_order

        sessions, total_count = await self._get_filtered_sessions(
            filters=filters,
            sort_column=sort_col,
            sort_order=sort_order,
            pagination=pagination,
        )

        # Update pagination total count
        pagination.total_count = total_count

        if not sessions:
            st.info("No sessions found matching your filters.")
            return

        # Batch query for message counts (avoid N+1)
        session_ids = [s.session_id for s in sessions]
        message_counts = await self._get_session_message_counts(session_ids)

        # Render session table
        self._render_session_table(sessions, message_counts)

        # Render pagination controls
        self._render_pagination_controls()

    async def _get_filtered_sessions(
        self,
        filters: SessionFilters,
        sort_column: SortColumn,
        sort_order: SortOrder,
        pagination: PaginationParams,
    ) -> Tuple[List[UserSession], int]:
        """
        Query sessions with filtering, sorting, and pagination.

        Uses Phase 2 indexes for performance:
        - idx_user_sessions_tags (GIN on tags)
        - idx_user_sessions_title_trgm (fuzzy search on title)
        - idx_user_sessions_metadata_summary (fuzzy search on summary)
        - idx_user_sessions_cost (cost sorting)
        - idx_user_sessions_tokens (token sorting)

        Args:
            filters: Filter criteria
            sort_column: Column to sort by
            sort_order: Sort order (asc/desc)
            pagination: Pagination parameters

        Returns:
            Tuple of (sessions, total_count)
        """
        async with get_async_session() as session:
            # Build base query
            query = select(UserSession).where(UserSession.user_id == self.user_id)

            # Apply filters
            if filters.status:
                query = query.where(UserSession.status.in_(filters.status))

            if filters.date_from:
                query = query.where(UserSession.created_at >= filters.date_from)

            if filters.date_to:
                # Add 1 day to include the entire day
                date_to_end = filters.date_to + timedelta(days=1)
                query = query.where(UserSession.created_at < date_to_end)

            if filters.tags:
                # Use PostgreSQL array contains operator (@>)
                # Requires ALL tags to be present (AND logic)
                # IMPORTANT: Use Text type to match database column (text[])
                # Using String would create varchar[] which is incompatible
                query = query.where(
                    UserSession.tags.op("@>")(cast(filters.tags, PG_ARRAY(Text)))
                )

            if filters.search_text:
                # Fuzzy search using pg_trgm similarity on title, summary, and session_id
                # Uses idx_user_sessions_title_trgm and idx_user_sessions_metadata_summary
                search_pattern = f"%{filters.search_text}%"
                query = query.where(
                    or_(
                        UserSession.session_id.ilike(search_pattern),  # Added: Search by session ID
                        UserSession.title.ilike(search_pattern),
                        UserSession.session_metadata["summary_5w"].astext.ilike(
                            search_pattern
                        ),
                        UserSession.session_metadata["summary_10w"].astext.ilike(
                            search_pattern
                        ),
                    )
                )

            if filters.min_cost is not None:
                query = query.where(UserSession.estimated_cost_usd >= filters.min_cost)

            if filters.max_cost is not None:
                query = query.where(UserSession.estimated_cost_usd <= filters.max_cost)

            if filters.min_tokens is not None:
                query = query.where(UserSession.total_tokens >= filters.min_tokens)

            if filters.max_tokens is not None:
                query = query.where(UserSession.total_tokens <= filters.max_tokens)

            # Count total results (before pagination)
            count_query = select(func.count()).select_from(query.subquery())
            total_count = (await session.execute(count_query)).scalar()

            # Apply sorting
            sort_col_obj = getattr(UserSession, sort_column.value)
            if sort_order == SortOrder.DESC:
                query = query.order_by(desc(sort_col_obj).nullslast())
            else:
                query = query.order_by(asc(sort_col_obj).nullslast())

            # Apply pagination
            query = query.limit(pagination.page_size).offset(pagination.offset)

            # Execute query
            result = await session.execute(query)
            sessions = result.scalars().all()

            return list(sessions), total_count

    async def _get_session_message_counts(
        self, session_ids: List[str]
    ) -> Dict[str, int]:
        """
        Batch query for message counts per session (avoid N+1 problem).

        Args:
            session_ids: List of session IDs to query

        Returns:
            Dictionary mapping session_id -> message_count
        """
        if not session_ids:
            return {}

        async with get_async_session() as session:
            # Batch query with GROUP BY
            query = (
                select(SessionMessage.session_id, func.count(SessionMessage.id))
                .where(SessionMessage.session_id.in_(session_ids))
                .group_by(SessionMessage.session_id)
            )

            result = await session.execute(query)
            counts = {row[0]: row[1] for row in result}

            # Return 0 for sessions with no messages
            return {sid: counts.get(sid, 0) for sid in session_ids}

    def _render_filter_controls(self) -> None:
        """
        Render filter controls in Streamlit expander.

        Filters:
        - Status (multiselect)
        - Date range (date_input)
        - Tags (multiselect)
        - Search text (text_input with fuzzy search)
        - Cost range (number_input)
        - Token range (number_input)
        """
        with st.expander("🔍 Filters", expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                # Status filter
                status_options = ["active", "archived", "pending_deletion", "deleted"]
                selected_statuses = st.multiselect(
                    "Status",
                    options=status_options,
                    default=st.session_state.session_filters.status or ["active"],
                    key="filter_status",
                )
                st.session_state.session_filters.status = selected_statuses

                # Date range filter
                date_from = st.date_input(
                    "From Date",
                    value=st.session_state.session_filters.date_from,
                    key="filter_date_from",
                )
                if date_from:
                    st.session_state.session_filters.date_from = datetime.combine(
                        date_from, datetime.min.time()
                    )

                # Cost range filter
                col_cost1, col_cost2 = st.columns(2)
                with col_cost1:
                    min_cost = st.number_input(
                        "Min Cost ($)",
                        min_value=0.0,
                        value=st.session_state.session_filters.min_cost or 0.0,
                        step=0.01,
                        format="%.2f",
                        key="filter_min_cost",
                    )
                    if min_cost > 0:
                        st.session_state.session_filters.min_cost = min_cost
                with col_cost2:
                    max_cost = st.number_input(
                        "Max Cost ($)",
                        min_value=0.0,
                        value=st.session_state.session_filters.max_cost or 0.0,
                        step=0.01,
                        format="%.2f",
                        key="filter_max_cost",
                    )
                    if max_cost > 0:
                        st.session_state.session_filters.max_cost = max_cost

            with col2:
                # Search text filter (includes session ID, title, and summary)
                search_text = st.text_input(
                    "Search (ID/title/summary)",
                    value=st.session_state.session_filters.search_text or "",
                    placeholder="Search by session ID, title, or summary...",
                    key="filter_search",
                )
                if search_text:
                    st.session_state.session_filters.search_text = search_text
                else:
                    st.session_state.session_filters.search_text = None

                # Date range filter (to)
                date_to = st.date_input(
                    "To Date",
                    value=st.session_state.session_filters.date_to,
                    key="filter_date_to",
                )
                if date_to:
                    st.session_state.session_filters.date_to = datetime.combine(
                        date_to, datetime.max.time()
                    )

                # Token range filter
                col_token1, col_token2 = st.columns(2)
                with col_token1:
                    min_tokens = st.number_input(
                        "Min Tokens",
                        min_value=0,
                        value=st.session_state.session_filters.min_tokens or 0,
                        step=1000,
                        key="filter_min_tokens",
                    )
                    if min_tokens > 0:
                        st.session_state.session_filters.min_tokens = min_tokens
                with col_token2:
                    max_tokens = st.number_input(
                        "Max Tokens",
                        min_value=0,
                        value=st.session_state.session_filters.max_tokens or 0,
                        step=1000,
                        key="filter_max_tokens",
                    )
                    if max_tokens > 0:
                        st.session_state.session_filters.max_tokens = max_tokens

            # Clear filters button
            if st.button("Clear All Filters"):
                st.session_state.session_filters = SessionFilters(status=["active"])
                st.rerun()

    def _render_refresh_controls(self) -> None:
        """
        Render manual and auto-refresh controls.

        Features:
        - Manual refresh button
        - Auto-refresh toggle with interval selector
        """
        col1, col2, col3 = st.columns([1, 1, 2])

        with col1:
            if st.button("🔄 Refresh"):
                st.rerun()

        with col2:
            auto_refresh = st.checkbox(
                "Auto-refresh",
                value=st.session_state.get("auto_refresh", False),
                key="auto_refresh_toggle",
            )
            st.session_state.auto_refresh = auto_refresh

        with col3:
            if auto_refresh:
                refresh_interval = st.selectbox(
                    "Interval",
                    options=[30, 60, 120, 300],
                    format_func=lambda x: f"{x}s",
                    index=1,  # Default 60s
                    key="refresh_interval",
                )
                # TODO: Implement auto-refresh with st.empty() and asyncio.sleep()
                st.info(
                    f"Auto-refresh every {refresh_interval}s (implementation pending)"
                )

    def _render_bulk_actions(self) -> None:
        """
        Render bulk action buttons for multi-select operations.

        Features:
        - Archive selected sessions
        - Delete selected sessions
        - Clear selection
        - Shows count of selected sessions
        """
        selected_count = len(st.session_state.selected_sessions)

        if selected_count > 0:
            st.divider()
            col1, col2, col3, col4 = st.columns([2, 1, 1, 2])

            with col1:
                st.markdown(f"**{selected_count} session(s) selected**")

            with col2:
                if st.button(
                    f"📦 Archive Selected ({selected_count})",
                    key="bulk_archive_btn",
                    help=f"Archive {selected_count} selected session(s)",
                ):
                    st.session_state.bulk_archive_pending = True
                    st.rerun()

            with col3:
                if st.button(
                    f"🗑️ Delete Selected ({selected_count})",
                    key="bulk_delete_btn",
                    help=f"Permanently delete {selected_count} selected session(s)",
                ):
                    st.session_state.bulk_delete_pending = True
                    st.rerun()

            with col4:
                if st.button("Clear Selection", key="clear_selection_btn"):
                    st.session_state.selected_sessions = []
                    st.rerun()

    def _render_session_table(
        self, sessions: List[UserSession], message_counts: Dict[str, int]
    ) -> None:
        """
        Render session table with sortable columns and inline actions.

        Args:
            sessions: List of UserSession objects
            message_counts: Dictionary mapping session_id -> message_count
        """
        # Apply compact CSS styling to reduce row spacing
        st.markdown(
            """
        <style>
            /* Target parent containers for more aggressive spacing reduction */
            div[data-testid="stVerticalBlock"] > div[data-testid="element-container"] {
                padding-top: 0.1rem !important;
                padding-bottom: 0.1rem !important;
                margin-top: 0 !important;
                margin-bottom: 0 !important;
            }

            /* Reduce horizontal block spacing */
            div[data-testid="stHorizontalBlock"] {
                gap: 0.25rem !important;
                padding: 0 !important;
            }

            /* Compact column spacing */
            div[data-testid="column"] {
                padding-top: 0.1rem !important;
                padding-bottom: 0.1rem !important;
                margin: 0 !important;
            }

            /* Ultra-compact buttons */
            div.row-widget.stButton > button {
                padding: 0.15rem 0.4rem !important;
                margin: 0 !important;
                height: 1.5rem !important;
                min-height: 1.5rem !important;
                font-size: 0.85rem !important;
                line-height: 1.2 !important;
            }

            /* Compact checkbox */
            div.row-widget.stCheckbox {
                margin: 0 !important;
                padding: 0 !important;
            }

            /* Compact text elements */
            div[data-testid="column"] p {
                margin: 0 !important;
                padding: 0 !important;
                line-height: 1.3 !important;
            }

            /* Reduce spacing in specific session table container */
            div.session-table-container {
                padding: 0 !important;
                margin: 0 !important;
            }
        </style>
        """,
            unsafe_allow_html=True,
        )

        # Table header with sort controls
        header_cols = st.columns([0.5, 3, 2, 1, 1, 1, 2, 2])

        # Select all checkbox
        with header_cols[0]:
            all_session_ids = [s.session_id for s in sessions]
            all_selected = all(
                sid in st.session_state.selected_sessions for sid in all_session_ids
            )

            # Store current page session IDs for callback to access
            st.session_state._current_page_sessions = all_session_ids

            # Use checkbox with callback to update state before render
            st.checkbox(
                "Select all sessions",
                value=all_selected,
                key="select_all_header",
                label_visibility="hidden",
                help="Select/Deselect all",
                on_change=EnhancedSessionNavigator._toggle_select_all,
            )

        sort_columns = [
            ("Title", SortColumn.TITLE),
            ("Last Active", SortColumn.LAST_ACTIVE),
            ("Messages", None),
            ("Tokens", SortColumn.TOKENS),
            ("Cost", SortColumn.COST),
            ("Status", None),
            ("Actions", None),
        ]

        for col, (label, sort_col) in zip(header_cols[1:], sort_columns):
            with col:
                if sort_col:
                    # Sortable column
                    current_sort = st.session_state.sort_column
                    current_order = st.session_state.sort_order
                    icon = (
                        ("🔽" if current_order == SortOrder.DESC else "🔼")
                        if current_sort == sort_col
                        else ""
                    )
                    if st.button(f"{label} {icon}", key=f"sort_{sort_col.value}"):
                        # Toggle sort order if same column, else default to DESC
                        if current_sort == sort_col:
                            st.session_state.sort_order = (
                                SortOrder.ASC
                                if current_order == SortOrder.DESC
                                else SortOrder.DESC
                            )
                        else:
                            st.session_state.sort_column = sort_col
                            st.session_state.sort_order = SortOrder.DESC
                        st.rerun()
                else:
                    st.markdown(f"**{label}**")

        st.divider()

        # Initialize checkbox keys from selected_sessions before rendering
        # This ensures checkboxes reflect the correct state after Select All toggle
        for session in sessions:
            checkbox_key = f"select_{session.session_id}"
            is_selected = session.session_id in st.session_state.selected_sessions
            # Initialize or update the checkbox key to match selected_sessions
            st.session_state[checkbox_key] = is_selected

        # Table rows
        for session in sessions:
            row_cols = st.columns([0.5, 3, 2, 1, 1, 1, 2, 2])

            # Checkbox for row selection
            with row_cols[0]:
                # Use checkbox with key only (no value parameter to avoid conflict)
                # State is managed through session_state key
                st.checkbox(
                    f"Select session {session.session_id[:16]}",
                    key=f"select_{session.session_id}",
                    label_visibility="hidden",
                    help=f"Select session {session.session_id[:16]}",
                    on_change=lambda sid=session.session_id: EnhancedSessionNavigator._toggle_session_selection(
                        sid
                    ),
                )

            with row_cols[1]:
                # Title (or fallback to session_id)
                title = session.title or session.session_id[:16]
                st.markdown(f"**{title}**")

            with row_cols[2]:
                # Last active (relative time)
                last_active = self._format_relative_time(session.last_active_at)
                st.text(last_active)

            with row_cols[3]:
                # Message count
                msg_count = message_counts.get(session.session_id, 0)
                st.text(str(msg_count))

            with row_cols[4]:
                # Token count (formatted with K/M suffix)
                tokens = self._format_token_count(session.total_tokens)
                st.text(tokens)

            with row_cols[5]:
                # Cost (formatted currency)
                cost = self._format_cost(session.estimated_cost_usd)
                st.text(cost)

            with row_cols[6]:
                # Status badge
                status_badge = self._render_status_badge(session.status)
                st.markdown(status_badge, unsafe_allow_html=True)

            with row_cols[7]:
                # Inline actions (Load, Rename, Archive, Delete)
                action_cols = st.columns(4)
                with action_cols[0]:
                    if st.button(
                        "📂",
                        key=f"load_{session.session_id}",
                        help="Load this session into Chat page",
                    ):
                        st.session_state.load_session_id = session.session_id
                        st.rerun()
                with action_cols[1]:
                    if st.button(
                        "✏️",
                        key=f"rename_{session.session_id}",
                        help="Rename this session",
                    ):
                        st.session_state.rename_session_id = session.session_id
                        st.rerun()
                with action_cols[2]:
                    if st.button(
                        "📦",
                        key=f"archive_{session.session_id}",
                        help="Archive this session (move to archived status)",
                    ):
                        st.session_state.archive_session_id = session.session_id
                        st.rerun()
                with action_cols[3]:
                    if st.button(
                        "🗑️",
                        key=f"delete_{session.session_id}",
                        help="Delete this session permanently",
                    ):
                        st.session_state.delete_session_id = session.session_id
                        st.rerun()

    def _render_pagination_controls(self) -> None:
        """
        Render pagination controls (page selector, page size).

        Features:
        - Previous/Next buttons
        - Page number selector
        - Page size selector
        - Total results count
        """
        pagination = st.session_state.pagination

        st.divider()
        col1, col2, col3, col4 = st.columns([1, 2, 1, 1])

        with col1:
            if st.button("⬅️ Previous", disabled=pagination.page <= 1):
                pagination.page -= 1
                st.rerun()

        with col2:
            st.markdown(
                f"Page {pagination.page} of {pagination.total_pages} "
                f"({pagination.total_count} total sessions)"
            )

        with col3:
            if st.button("Next ➡️", disabled=pagination.page >= pagination.total_pages):
                pagination.page += 1
                st.rerun()

        with col4:
            page_size = st.selectbox(
                "Per page",
                options=[10, 20, 50, 100],
                index=1,  # Default 20
                key="page_size_selector",
            )
            if page_size != pagination.page_size:
                pagination.page_size = page_size
                pagination.page = 1  # Reset to first page
                st.rerun()

    def _format_relative_time(self, dt: datetime) -> str:
        """
        Format datetime as relative time (e.g., '2 hours ago').

        Args:
            dt: Datetime to format

        Returns:
            Relative time string
        """
        now = datetime.utcnow()
        delta = now - dt

        if delta.days > 365:
            years = delta.days // 365
            return f"{years}y ago"
        elif delta.days > 30:
            months = delta.days // 30
            return f"{months}mo ago"
        elif delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours}h ago"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes}m ago"
        else:
            return "just now"

    def _format_token_count(self, count: int) -> str:
        """
        Format token count with K/M suffix.

        Args:
            count: Token count

        Returns:
            Formatted string (e.g., '12.5K', '2.3M')
        """
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K"
        else:
            return str(count)

    def _format_cost(self, cost: float) -> str:
        """
        Format cost in USD with appropriate precision.

        Args:
            cost: Cost in USD

        Returns:
            Formatted string (e.g., '$0.12', '$12.34', '$1.2K')
        """
        if cost >= 1000:
            return f"${cost / 1000:.1f}K"
        elif cost >= 1:
            return f"${cost:.2f}"
        elif cost >= 0.01:
            return f"${cost:.3f}"
        else:
            return f"${cost:.4f}"

    def _render_status_badge(self, status: str) -> str:
        """
        Render status as colored HTML badge.

        Args:
            status: Session status

        Returns:
            HTML badge string
        """
        colors = {
            "active": "#28a745",
            "archived": "#6c757d",
            "pending_deletion": "#ffc107",
            "deleted": "#dc3545",
        }
        color = colors.get(status, "#6c757d")
        return f'<span style="background-color: {color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px;">{status}</span>'

    async def _handle_pending_actions(self) -> None:
        """
        Handle pending actions from session state (load, rename, archive, delete).

        This method checks for action flags in session state and displays
        appropriate dialogs or executes actions.
        """
        # Handle load session action
        if st.session_state.get("load_session_id"):
            session_id = st.session_state.load_session_id
            with st.spinner(f"Loading session {session_id[:16]}..."):
                await self._load_session_into_state(session_id)
                del st.session_state.load_session_id
                # Show success message
                message_count = len(st.session_state.get("conversation_history", []))
                st.success(f"✅ Session loaded! {message_count} messages restored. Switch to Chat page to continue conversation.")
                st.info("💡 Navigate to the Chat page (📬 Adept Chat) to see your loaded conversation.")
            st.stop()  # Prevent rendering rest of UI while message is shown

        # Handle rename action
        if st.session_state.get("rename_session_id"):
            session_id = st.session_state.rename_session_id
            with st.form(key="rename_form"):
                st.subheader(f"Rename Session: {session_id[:16]}...")
                new_title = st.text_input(
                    "New Title",
                    placeholder="Enter new session title",
                    max_chars=100,
                )
                col1, col2 = st.columns(2)
                with col1:
                    if st.form_submit_button("✅ Rename"):
                        if new_title:
                            await self._rename_session(session_id, new_title)
                            del st.session_state.rename_session_id
                            st.rerun()
                        else:
                            st.warning("Please enter a title")
                with col2:
                    if st.form_submit_button("❌ Cancel"):
                        del st.session_state.rename_session_id
                        st.rerun()
            st.stop()  # Prevent rendering rest of UI while dialog is open

        # Handle archive action
        if st.session_state.get("archive_session_id"):
            session_id = st.session_state.archive_session_id
            st.warning(f"⚠️ Archive session {session_id[:16]}?")
            st.markdown(
                "This will move the session to archived status. You can restore it later."
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Archive", key="confirm_archive"):
                    await self._archive_session(session_id)
                    del st.session_state.archive_session_id
                    st.rerun()
            with col2:
                if st.button("❌ Cancel", key="cancel_archive"):
                    del st.session_state.archive_session_id
                    st.rerun()
            st.stop()  # Prevent rendering rest of UI while dialog is open

        # Handle delete action
        if st.session_state.get("delete_session_id"):
            session_id = st.session_state.delete_session_id
            st.error(f"⚠️ Permanently delete session {session_id[:16]}?")
            st.markdown(
                "**WARNING**: This action cannot be undone. All messages and metadata will be permanently deleted."
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🗑️ Delete Permanently", key="confirm_delete"):
                    await self._delete_session(session_id)
                    del st.session_state.delete_session_id
                    st.rerun()
            with col2:
                if st.button("❌ Cancel", key="cancel_delete"):
                    del st.session_state.delete_session_id
                    st.rerun()
            st.stop()  # Prevent rendering rest of UI while dialog is open

        # Handle bulk archive action
        if st.session_state.get("bulk_archive_pending"):
            session_ids = st.session_state.selected_sessions
            count = len(session_ids)
            st.warning(f"⚠️ Archive {count} selected session(s)?")
            st.markdown(
                f"This will move {count} session(s) to archived status. You can restore them later."
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button(
                    f"✅ Archive {count} Session(s)", key="confirm_bulk_archive"
                ):
                    await self._bulk_archive_sessions(session_ids)
                    st.session_state.selected_sessions = []
                    del st.session_state.bulk_archive_pending
                    st.rerun()
            with col2:
                if st.button("❌ Cancel", key="cancel_bulk_archive"):
                    del st.session_state.bulk_archive_pending
                    st.rerun()
            st.stop()  # Prevent rendering rest of UI while dialog is open

        # Handle bulk delete action
        if st.session_state.get("bulk_delete_pending"):
            session_ids = st.session_state.selected_sessions
            count = len(session_ids)
            st.error(f"⚠️ Permanently delete {count} selected session(s)?")
            st.markdown(
                f"**WARNING**: This action cannot be undone. All messages and metadata for {count} session(s) will be permanently deleted."
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button(
                    f"🗑️ Delete {count} Session(s) Permanently",
                    key="confirm_bulk_delete",
                ):
                    await self._bulk_delete_sessions(session_ids)
                    st.session_state.selected_sessions = []
                    del st.session_state.bulk_delete_pending
                    st.rerun()
            with col2:
                if st.button("❌ Cancel", key="cancel_bulk_delete"):
                    del st.session_state.bulk_delete_pending
                    st.rerun()
            st.stop()  # Prevent rendering rest of UI while dialog is open

    async def _rename_session(self, session_id: str, new_title: str) -> None:
        """
        Rename a session (update title).

        Args:
            session_id: Session ID to rename
            new_title: New title for the session
        """
        try:
            async with get_async_session() as session:
                from sqlalchemy import update

                stmt = (
                    update(UserSession)
                    .where(UserSession.session_id == session_id)
                    .values(title=new_title, last_active_at=datetime.utcnow())
                )
                await session.execute(stmt)
                await session.commit()
                logger.info(f"Renamed session {session_id} to: {new_title}")
                st.success(f"Session renamed to: {new_title}")
        except Exception as e:
            logger.error(f"Failed to rename session {session_id}: {e}", exc_info=True)
            st.error(f"Failed to rename session: {e}")

    async def _archive_session(self, session_id: str) -> None:
        """
        Archive a session (set status to 'archived').

        Args:
            session_id: Session ID to archive
        """
        try:
            async with get_async_session() as session:
                from sqlalchemy import update

                stmt = (
                    update(UserSession)
                    .where(UserSession.session_id == session_id)
                    .values(status="archived", archived_at=datetime.utcnow())
                )
                await session.execute(stmt)
                await session.commit()
                logger.info(f"Archived session: {session_id}")
                st.success(f"Session {session_id[:16]} archived successfully!")
        except Exception as e:
            logger.error(f"Failed to archive session {session_id}: {e}", exc_info=True)
            st.error(f"Failed to archive session: {e}")

    async def _delete_session(self, session_id: str) -> None:
        """
        Permanently delete a session and all associated messages.

        Args:
            session_id: Session ID to delete
        """
        try:
            async with get_async_session() as session:
                from sqlalchemy import delete, text

                # Delete associated messages first (foreign key constraint)
                msg_stmt = delete(SessionMessage).where(
                    SessionMessage.session_id == session_id
                )
                await session.execute(msg_stmt)

                # Delete associated checkpoints (LangGraph state data)
                # NOTE: checkpoints table uses thread_id, not session_id
                checkpoint_stmt = text("DELETE FROM checkpoints WHERE thread_id = :thread_id")
                await session.execute(checkpoint_stmt, {"thread_id": session_id})

                # Delete the session
                sess_stmt = delete(UserSession).where(
                    UserSession.session_id == session_id
                )
                await session.execute(sess_stmt)

                await session.commit()
                logger.info(f"Deleted session: {session_id}")
                st.success(f"Session {session_id[:16]} deleted permanently!")
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}", exc_info=True)
            st.error(f"Failed to delete session: {e}")

    async def _bulk_archive_sessions(self, session_ids: List[str]) -> None:
        """
        Archive multiple sessions (set status to 'archived').

        Args:
            session_ids: List of session IDs to archive
        """
        success_count = 0
        failure_count = 0

        try:
            async with get_async_session() as session:
                from sqlalchemy import update

                stmt = (
                    update(UserSession)
                    .where(UserSession.session_id.in_(session_ids))
                    .values(status="archived", archived_at=datetime.utcnow())
                )
                result = await session.execute(stmt)
                await session.commit()

                success_count = result.rowcount
                logger.info(f"Bulk archived {success_count} sessions")

                if success_count > 0:
                    st.success(f"✅ Successfully archived {success_count} session(s)!")
                if success_count < len(session_ids):
                    failure_count = len(session_ids) - success_count
                    st.warning(
                        f"⚠️ Failed to archive {failure_count} session(s) (may not exist)"
                    )
        except Exception as e:
            logger.error(f"Failed to bulk archive sessions: {e}", exc_info=True)
            st.error(f"❌ Failed to archive sessions: {e}")

    async def _bulk_delete_sessions(self, session_ids: List[str]) -> None:
        """
        Permanently delete multiple sessions and all associated messages.

        Args:
            session_ids: List of session IDs to delete
        """
        success_count = 0
        failure_count = 0

        try:
            async with get_async_session() as session:
                from sqlalchemy import delete, text

                # Delete associated messages first (foreign key constraint)
                msg_stmt = delete(SessionMessage).where(
                    SessionMessage.session_id.in_(session_ids)
                )
                await session.execute(msg_stmt)

                # Delete associated checkpoints (LangGraph state data)
                # NOTE: checkpoints table uses thread_id, not session_id
                for sid in session_ids:
                    checkpoint_stmt = text("DELETE FROM checkpoints WHERE thread_id = :thread_id")
                    await session.execute(checkpoint_stmt, {"thread_id": sid})

                # Delete the sessions
                sess_stmt = delete(UserSession).where(
                    UserSession.session_id.in_(session_ids)
                )
                result = await session.execute(sess_stmt)
                await session.commit()

                success_count = result.rowcount
                logger.info(f"Bulk deleted {success_count} sessions")

                if success_count > 0:
                    st.success(
                        f"✅ Successfully deleted {success_count} session(s) permanently!"
                    )
                if success_count < len(session_ids):
                    failure_count = len(session_ids) - success_count
                    st.warning(
                        f"⚠️ Failed to delete {failure_count} session(s) (may not exist)"
                    )
        except Exception as e:
            logger.error(f"Failed to bulk delete sessions: {e}", exc_info=True)
            st.error(f"❌ Failed to delete sessions: {e}")

    async def _load_session_messages(self, session_id: str) -> List[Dict]:
        """
        Load all messages for a session from database.

        Args:
            session_id: Session identifier

        Returns:
            List of message dictionaries with 'role', 'content', 'timestamp' keys,
            ordered by message_index ASC
        """
        try:
            async with get_async_session() as db_session:
                stmt = (
                    select(SessionMessage)
                    .where(SessionMessage.session_id == session_id)
                    .order_by(SessionMessage.message_index.asc())
                )
                result = await db_session.execute(stmt)
                messages = result.scalars().all()

                logger.info(f"Loaded {len(messages)} messages for session {session_id}")

                # Convert to dictionary format with timestamp preservation
                return [
                    {
                        "role": msg.message_role,
                        "content": msg.message_content or "",
                        "timestamp": msg.created_at.isoformat() if msg.created_at else None
                    }
                    for msg in messages
                ]
        except Exception as e:
            logger.error(f"Failed to load messages for session {session_id}: {e}")
            return []

    async def _load_session_into_state(self, session_id: str):
        """
        Load session messages and metadata into Streamlit session state for Chat page.

        Args:
            session_id: Session identifier to load

        Updates:
            - st.session_state.conversation_history: List of messages
            - st.session_state.response_session_id: Loaded session ID
            - st.session_state.session_title: Session title/name (Session 43 fix)

        This allows users to continue conversations from previous sessions.

        Session 43 Fix: Now loads session title from database so Chat.py session
        info panel displays correct label immediately on first load.
        """
        try:
            # Load session messages
            messages = await self._load_session_messages(session_id)
            if not messages:
                st.warning("This session has no messages.")
                return

            # Load session metadata (Session 43: fetch title for Chat.py label)
            async with get_async_session() as db_session:
                stmt = select(UserSession).where(UserSession.session_id == session_id)
                result = await db_session.execute(stmt)
                user_session = result.scalar_one_or_none()

                if user_session:
                    session_title = user_session.title or session_id[:16]
                    logger.info(
                        f"Loaded session metadata: title='{session_title}', "
                        f"status={user_session.status}, tokens={user_session.total_tokens}"
                    )
                else:
                    session_title = session_id[:16]
                    logger.warning(
                        f"Session {session_id} not found in user_sessions table, "
                        f"using fallback title"
                    )

            # Update Streamlit session state to load conversation into Chat page
            st.session_state.conversation_history = messages
            st.session_state.response_session_id = session_id
            st.session_state.session_title = session_title  # Session 43: Set title

            logger.info(
                f"Loaded session {session_id} into Streamlit state "
                f"({len(messages)} messages, title='{session_title}')"
            )
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            st.error("Failed to load session. Please try again.")
