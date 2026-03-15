"""
Switch Command Template Model

Stores command templates for different switch vendors/models.
Allows dynamic configuration without code changes.
"""

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from core.database import Base


class SwitchCommandTemplate(Base):
    """Command template for switch data collection"""

    __tablename__ = 'switch_command_templates'

    id = Column(Integer, primary_key=True, index=True)

    # Identification
    vendor = Column(String(50), nullable=False, index=True)
    model_pattern = Column(String(100), nullable=False)  # Can contain wildcards like "7220*"
    name_pattern = Column(String(100))  # Optional: match by switch name pattern

    # Device Type (for netmiko)
    device_type = Column(String(50), nullable=False)  # e.g., 'nokia_srl', 'dell_os10'

    # ARP Collection
    arp_command = Column(Text)  # CLI command to get ARP table
    arp_parser_type = Column(String(50))  # Parser to use: 'nokia_7220', 'dell_os10', 'cisco_ios', 'generic'
    arp_enabled = Column(Boolean, default=True)

    # MAC Collection
    mac_command = Column(Text)  # CLI command to get MAC table
    mac_parser_type = Column(String(50))  # Parser to use
    mac_enabled = Column(Boolean, default=True)

    # Priority (higher number = higher priority when multiple templates match)
    priority = Column(Integer, default=100)

    # Metadata
    description = Column(Text)
    is_builtin = Column(Boolean, default=False)  # Built-in templates can't be deleted
    enabled = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<SwitchCommandTemplate {self.vendor} {self.model_pattern}>"
