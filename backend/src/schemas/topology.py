"""
Topology Schemas
"""

from pydantic import BaseModel
from typing import List, Optional


class TopologyCollectRequest(BaseModel):
    """Trigger topology collection for switches (empty = all auto-collect switches)"""
    switch_ids: Optional[List[int]] = None
