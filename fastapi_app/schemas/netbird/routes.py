from pydantic import BaseModel, Field, model_validator
from typing import List, Optional

class NetBirdRouteCreateUpdate(BaseModel):
    description: str
    network_id: str = Field(
        min_length=1, 
        max_length=40, 
        description="Route network identifier, to group HA routes"
    )
    enabled: bool
    peer: Optional[str] = Field(None, description="Conflicts with peer_groups")
    peer_groups: Optional[List[str]] = Field(None, description="Conflicts with peer")
    network: Optional[str] = Field(None, description="Network range in CIDR format, Conflicts with domains")
    domains: Optional[List[str]] = Field(None, max_length=32, description="Conflicts with network")
    metric: int = Field(ge=1, le=9999, description="Lowest number has higher priority")
    masquerade: bool
    groups: List[str]
    keep_route: bool
    access_control_groups: Optional[List[str]] = None
    skip_auto_apply: Optional[bool] = None

    @model_validator(mode='after')
    def validate_conflicts(self):
        if self.peer and self.peer_groups:
            raise ValueError("You cannot set both 'peer' and 'peer_groups'. Please provide only one.")
        if self.network and self.domains:
            raise ValueError("You cannot set both 'network' and 'domains'. Please provide only one.")
        if not self.network and not self.domains:
            raise ValueError("You must provide either 'network' or 'domains'.")
        return self

class NetBirdRouteResponse(BaseModel):
    id: str
    network_type: Optional[str] = None
    description: str
    network_id: str
    enabled: bool
    peer: Optional[str] = None
    peer_groups: Optional[List[str]] = None
    network: Optional[str] = None
    domains: Optional[List[str]] = None
    metric: int
    masquerade: bool
    groups: List[str]
    keep_route: bool
    access_control_groups: Optional[List[str]] = None
    skip_auto_apply: Optional[bool] = None