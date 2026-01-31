from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from api.deps import get_db
from models.query_history import QueryHistory
from schemas.history import QueryHistoryResponse, QueryHistoryListResponse
from utils.logger import logger

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=QueryHistoryListResponse)
async def get_query_history(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get paginated query history

    Returns a list of all IP lookup queries with their results
    """
    try:
        # Calculate offset
        offset = (page - 1) * page_size

        # Get total count
        count_result = await db.execute(
            select(func.count()).select_from(QueryHistory)
        )
        total = count_result.scalar()

        # Get paginated results
        result = await db.execute(
            select(QueryHistory)
            .order_by(QueryHistory.queried_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = result.scalars().all()

        return QueryHistoryListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[QueryHistoryResponse.model_validate(item) for item in items]
        )

    except Exception as e:
        logger.error(f"Error getting query history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get query history: {str(e)}"
        )


@router.get("/{history_id}", response_model=QueryHistoryResponse)
async def get_query_history_item(
    history_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific query history item by ID"""
    try:
        result = await db.execute(
            select(QueryHistory).where(QueryHistory.id == history_id)
        )
        item = result.scalar_one_or_none()

        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Query history item with ID {history_id} not found"
            )

        return QueryHistoryResponse.model_validate(item)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting query history item: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get query history item: {str(e)}"
        )
