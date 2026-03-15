from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import get_db
from schemas.lookup import IPLookupRequest, IPLookupResponse, IPLookupResult
from services.ip_lookup import ip_lookup_service
from utils.logger import logger

router = APIRouter(prefix="/lookup", tags=["lookup"])


@router.post("/ip", response_model=IPLookupResponse)
async def lookup_ip_address(
    request: IPLookupRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Lookup an IP address to find which switch port it's connected to

    Query modes:
    - 'cache' (default): Fast query from database (~100ms). Data may be up to 10 minutes old.
    - 'realtime': Direct SSH query to switches (~20-30s). Most accurate but slow.
    - 'auto': Try cache first, fallback to realtime if not found.

    This endpoint:
    1. Queries cached ARP/MAC tables (if mode='cache' or 'auto')
    2. Falls back to live switch queries (if mode='realtime' or auto fallback)
    3. Returns switch name, port, VLAN, and data freshness information
    """
    try:
        logger.info(f"Received IP lookup request for {request.ip_address}, mode={request.mode}")

        # Perform the lookup with specified mode
        result = await ip_lookup_service.lookup_ip(db, str(request.ip_address), mode=request.mode)

        # Convert to response format
        if result['found']:
            lookup_result = IPLookupResult(**result)
            return IPLookupResponse(
                success=True,
                result=lookup_result,
                error=None
            )
        else:
            lookup_result = IPLookupResult(**result)
            return IPLookupResponse(
                success=False,
                result=lookup_result,
                error=result.get('message', 'IP address not found')
            )

    except Exception as e:
        logger.error(f"Error during IP lookup: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to lookup IP address: {str(e)}"
        )
