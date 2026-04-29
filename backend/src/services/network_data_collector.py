"""
Network Data Collector

Orchestrates the collection of ARP and MAC table data from all switches,
performs port analysis, and updates IP location mappings.

This is the main service that ties everything together.
"""

from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, cast, Text, delete, not_
from sqlalchemy.dialects.postgresql import insert
from utils.logger import logger

from models.switch import Switch
from models.arp_table import ARPTable
from models.mac_table import MACTable
from models.optical_module import OpticalModule
from models.port_analysis import PortAnalysis
from models.ip_location import IPLocation
from models.switch_command_template import SwitchCommandTemplate
from models.alarm import AlarmSeverity, AlarmSourceType

from services.snmp_service import snmp_service
from services.cli_service import cli_service
from services.port_analysis_service import port_analysis_service
from services.ip_location_engine import ip_location_engine
from services.alarm_service import alarm_service


class NetworkDataCollector:
    """Orchestrates network data collection and analysis"""

    def __init__(self):
        self.collection_running = False
        self._command_templates_cache: Optional[List[Dict]] = None
        self._command_templates_cache_expires_at: Optional[datetime] = None

    async def _clear_port_analysis_for_switch(self, db: AsyncSession, switch_id: int) -> int:
        """Remove stale port analysis rows for a switch."""
        result = await db.execute(
            delete(PortAnalysis).where(PortAnalysis.switch_id == switch_id)
        )
        deleted_count = result.rowcount or 0
        if deleted_count:
            logger.info(f"Cleared {deleted_count} stale port analysis rows for switch {switch_id}")
        return deleted_count

    async def _prune_port_analysis_for_switch(
        self,
        db: AsyncSession,
        switch_id: int,
        active_port_names: set[str]
    ) -> int:
        """Remove port-analysis rows that are no longer present in the latest successful MAC snapshot."""
        stmt = delete(PortAnalysis).where(PortAnalysis.switch_id == switch_id)
        if active_port_names:
            stmt = stmt.where(not_(PortAnalysis.port_name.in_(active_port_names)))

        result = await db.execute(stmt)
        deleted_count = result.rowcount or 0
        if deleted_count:
            logger.info(
                f"Pruned {deleted_count} outdated port analysis rows for switch {switch_id}"
            )
        return deleted_count

    async def refresh_port_analysis_for_switch(
        self,
        db: AsyncSession,
        switch: Switch
    ) -> Dict[str, int]:
        """
        Refresh port-analysis rows for a single switch from the latest stored MAC table.

        This keeps the switch detail "port policy" view aligned with the most recent
        MAC snapshot collected by the worker pool.
        """
        result = await db.execute(
            select(MACTable).where(MACTable.switch_id == switch.id)
        )
        mac_entries = result.scalars().all()

        if not mac_entries:
            logger.warning(
                f"Skipping port analysis refresh for {switch.name} (ID: {switch.id}) "
                f"because no MAC entries are currently stored"
            )
            return {
                'ports_analyzed': 0,
                'ports_created': 0,
                'ports_updated': 0,
                'ports_deleted': 0,
            }

        mac_dicts = [
            {
                'mac_address': m.mac_address,
                'port_name': m.port_name,
                'vlan_id': m.vlan_id
            }
            for m in mac_entries
        ]

        port_results = port_analysis_service.analyze_port_statistics(mac_dicts)
        current_port_names = set(port_results.keys())
        deleted_count = await self._prune_port_analysis_for_switch(db, switch.id, current_port_names)

        analyzed_at = datetime.utcnow()
        ports_created = 0
        ports_updated = 0

        for port_name, analysis in port_results.items():
            result = await db.execute(
                select(PortAnalysis).where(
                    and_(
                        PortAnalysis.switch_id == switch.id,
                        PortAnalysis.port_name == port_name
                    )
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.mac_count = analysis['mac_count']
                existing.unique_vlans = analysis['unique_vlans']
                existing.port_type = analysis['port_type']
                existing.confidence_score = analysis['confidence_score']
                existing.is_trunk_by_name = analysis['is_trunk_by_name']
                existing.is_access_by_name = analysis['is_access_by_name']
                existing.analyzed_at = analyzed_at
                ports_updated += 1
            else:
                db.add(PortAnalysis(
                    switch_id=switch.id,
                    port_name=port_name,
                    mac_count=analysis['mac_count'],
                    unique_vlans=analysis['unique_vlans'],
                    port_type=analysis['port_type'],
                    confidence_score=analysis['confidence_score'],
                    is_trunk_by_name=analysis['is_trunk_by_name'],
                    is_access_by_name=analysis['is_access_by_name'],
                    analyzed_at=analyzed_at
                ))
                ports_created += 1

        logger.info(
            f"Refreshed port analysis for {switch.name}: "
            f"{ports_created} created, {ports_updated} updated, {deleted_count} deleted"
        )

        return {
            'ports_analyzed': len(port_results),
            'ports_created': ports_created,
            'ports_updated': ports_updated,
            'ports_deleted': deleted_count,
        }

    def _build_collection_failure_message(
        self,
        switch: Switch,
        mac_detail: str,
        arp_detail: str
    ) -> str:
        """Build a user-facing failure message for switch collection."""
        status_prefix = (
            "Device is offline according to the status checker. "
            if switch.is_reachable is False else
            ""
        )
        return (
            f"{status_prefix}No usable ARP or MAC data collected under the current global collection policy. "
            f"MAC result: {mac_detail}; ARP result: {arp_detail}."
        )

    async def _mark_switch_collection_failed(
        self,
        db: AsyncSession,
        switch: Switch,
        reason: str,
        collected_at: Optional[datetime] = None,
        clear_port_analysis: bool = False
    ) -> None:
        """Persist failed collection state while preserving the last successful topology snapshot."""
        if collected_at:
            switch.last_arp_collection_at = collected_at
            switch.last_mac_collection_at = collected_at

        switch.last_collection_status = 'failed'
        switch.last_collection_message = reason
        db.add(switch)

        if clear_port_analysis:
            await self._clear_port_analysis_for_switch(db, switch.id)

    def _get_snmp_config(self, switch: Switch) -> Dict:
        """Build SNMP configuration dictionary for a switch"""
        return {
            'snmp_username': switch.snmp_username,
            'snmp_auth_protocol': switch.snmp_auth_protocol,
            'snmp_auth_password_encrypted': switch.snmp_auth_password_encrypted,
            'snmp_priv_protocol': switch.snmp_priv_protocol,
            'snmp_priv_password_encrypted': switch.snmp_priv_password_encrypted,
            'snmp_port': switch.snmp_port
        }

    def _build_cli_config(self, switch: Switch) -> Dict:
        """Build CLI configuration dictionary for a switch"""
        return {
            'username': switch.username,
            'password_encrypted': switch.password_encrypted,
            'vendor': switch.vendor,
            'model': switch.model,
            'name': switch.name,
            'cli_transport': switch.cli_transport,
            'ssh_port': switch.ssh_port,
            'connection_timeout': switch.connection_timeout,
            'enable_password_encrypted': switch.enable_password_encrypted
        }

    def _set_optical_collection_state(
        self,
        switch: Switch,
        *,
        collected_at: datetime,
        status: str,
        message: str,
        modules_count: Optional[int] = None,
        mark_success: bool = False
    ) -> None:
        """Persist switch-level optical collection metadata."""
        switch.last_optical_collection_at = collected_at
        switch.last_optical_collection_status = status
        switch.last_optical_collection_message = message
        switch.last_optical_modules_count = modules_count

        if mark_success:
            switch.last_optical_success_at = collected_at

    def _optical_identity_tuple(self, module_data: Dict) -> tuple:
        """Build a stable identity tuple to detect replacement on the same port."""
        return (
            (module_data.get('module_type') or module_data.get('type') or '').strip(),
            (module_data.get('model') or '').strip(),
            (module_data.get('part_number') or '').strip(),
            (module_data.get('serial_number') or '').strip(),
            (module_data.get('vendor') or '').strip(),
            module_data.get('speed_gbps'),
        )

    async def _store_optical_modules_snapshot(
        self,
        db: AsyncSession,
        switch: Switch,
        optical_modules: List[Dict],
        collected_at: datetime
    ) -> int:
        """
        Upsert the latest optical snapshot without deleting historical rows for ports
        that were not seen in the newest successful collection.
        """
        result = await db.execute(
            select(OpticalModule).where(OpticalModule.switch_id == switch.id)
        )
        existing_rows = result.scalars().all()
        existing_by_port = {row.port_name: row for row in existing_rows}

        normalized_modules: dict[str, Dict] = {}
        for module_data in optical_modules:
            port_name = module_data.get('port_name') or module_data.get('port')
            if not port_name:
                continue
            normalized_modules[str(port_name).strip()] = module_data

        for port_name, module_data in normalized_modules.items():
            existing = existing_by_port.get(port_name)
            new_identity = self._optical_identity_tuple(module_data)

            if existing:
                old_identity = (
                    (existing.module_type or '').strip(),
                    (existing.model or '').strip(),
                    (existing.part_number or '').strip(),
                    (existing.serial_number or '').strip(),
                    (existing.vendor or '').strip(),
                    existing.speed_gbps,
                )

                if old_identity != new_identity:
                    existing.first_seen = collected_at

                existing.switch_name = switch.name
                existing.switch_ip = str(switch.ip_address)
                existing.port_name = port_name
                existing.module_type = module_data.get('module_type') or module_data.get('type')
                existing.model = module_data.get('model')
                existing.part_number = module_data.get('part_number')
                existing.serial_number = module_data.get('serial_number')
                existing.vendor = module_data.get('vendor')
                existing.speed_gbps = module_data.get('speed_gbps')
                existing.collected_at = collected_at
                existing.last_seen = collected_at
            else:
                db.add(OpticalModule(
                    switch_id=switch.id,
                    switch_name=switch.name,
                    switch_ip=str(switch.ip_address),
                    port_name=port_name,
                    module_type=module_data.get('module_type') or module_data.get('type'),
                    model=module_data.get('model'),
                    part_number=module_data.get('part_number'),
                    serial_number=module_data.get('serial_number'),
                    vendor=module_data.get('vendor'),
                    speed_gbps=module_data.get('speed_gbps'),
                    collected_at=collected_at,
                    first_seen=collected_at,
                    last_seen=collected_at
                ))

        return len(normalized_modules)

    async def _load_command_templates(self, db: AsyncSession) -> List[Dict]:
        """Load CLI command templates from database"""
        from models.switch_command_template import SwitchCommandTemplate
        from sqlalchemy import select

        now = datetime.utcnow()
        if (
            self._command_templates_cache is not None and
            self._command_templates_cache_expires_at is not None and
            self._command_templates_cache_expires_at > now
        ):
            return [dict(template) for template in self._command_templates_cache]

        stmt = select(SwitchCommandTemplate).where(
            SwitchCommandTemplate.enabled == True
        ).order_by(
            SwitchCommandTemplate.priority.desc(),
            SwitchCommandTemplate.vendor
        )

        result = await db.execute(stmt)
        templates = result.scalars().all()

        template_dicts = [
            {
                'vendor': t.vendor,
                'model_pattern': t.model_pattern,
                'device_type': t.device_type,
                'arp_command': t.arp_command,
                'arp_parser_type': t.arp_parser_type,
                'arp_enabled': t.arp_enabled,
                'mac_command': t.mac_command,
                'mac_parser_type': t.mac_parser_type,
                'mac_enabled': t.mac_enabled,
                'priority': t.priority,
                'enabled': t.enabled
            }
            for t in templates
        ]

        self._command_templates_cache = template_dicts
        self._command_templates_cache_expires_at = now + timedelta(minutes=5)
        return [dict(template) for template in template_dicts]

    def _create_batches(self, switches: List[Switch], batch_size: int = 10) -> List[List[Switch]]:
        """
        Split switches into batches of specified size.

        Args:
            switches: List of all switches
            batch_size: Number of switches per batch (default: 10)

        Returns:
            List of batches, where each batch is a list of switches
        """
        batches = []
        for i in range(0, len(switches), batch_size):
            batches.append(switches[i:i + batch_size])
        return batches

    async def _process_batch_with_retry(
        self,
        db: AsyncSession,
        batch: List[Switch],
        batch_idx: int,
        template_dicts: List[Dict],
        max_retries: int = 3,
        is_final_retry: bool = False
    ) -> bool:
        """
        Process a batch of switches with retry mechanism and exponential backoff.

        Args:
            db: Database session
            batch: List of switches in this batch
            batch_idx: Batch index (for logging)
            template_dicts: Command templates
            max_retries: Maximum number of retry attempts (default: 3)
            is_final_retry: If True, this is the final retry after all batches completed

        Returns:
            True if batch succeeded, False if failed after all retries
        """
        batch_switch_names = [s.name for s in batch]

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    backoff_delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                    logger.info(
                        f"  Retrying batch {batch_idx} (attempt {attempt + 1}/{max_retries}) "
                        f"after {backoff_delay}s delay..."
                    )
                    await asyncio.sleep(backoff_delay)

                    # Create INFO-level alarm for batch retry
                    if not is_final_retry:
                        await alarm_service.create_alarm(
                            db=db,
                            severity=AlarmSeverity.INFO,
                            title=f"Batch {batch_idx} retry attempt {attempt + 1}",
                            message=f"Retrying collection for batch {batch_idx} with {len(batch)} switches",
                            source_type=AlarmSourceType.BATCH,
                            source_id=batch_idx,
                            source_name=f"Batch {batch_idx}",
                            details={
                                'attempt': attempt + 1,
                                'max_retries': max_retries,
                                'switch_count': len(batch),
                                'switch_names': batch_switch_names
                            }
                        )

                # Process the batch
                success = await self._process_batch(db, batch, batch_idx, template_dicts)

                if success:
                    if attempt > 0:
                        logger.info(
                            f"  ✅ Batch {batch_idx} succeeded on retry attempt {attempt + 1}"
                        )
                        # Auto-resolve ALL batch alarms (INFO, WARNING, CRITICAL) for this batch
                        await alarm_service.auto_resolve_alarms(
                            db=db,
                            source_type=AlarmSourceType.BATCH,
                            source_id=batch_idx
                        )
                    return True

            except Exception as e:
                logger.error(
                    f"  ❌ Batch {batch_idx} attempt {attempt + 1} failed: {str(e)}"
                )
                if attempt == max_retries - 1:
                    # Final attempt failed
                    logger.error(
                        f"  ❌ Batch {batch_idx} failed after {max_retries} attempts"
                    )
                    return False

        return False

    async def _process_batch(
        self,
        db: AsyncSession,
        batch: List[Switch],
        batch_idx: int,
        template_dicts: List[Dict],
        timeout_per_switch: int = 300
    ) -> bool:
        """
        Process a single batch of switches with timeout protection and concurrent processing.

        Args:
            db: Database session
            batch: List of switches in this batch
            batch_idx: Batch index (for logging)
            template_dicts: Command templates
            timeout_per_switch: Timeout in seconds for each switch (default: 300)

        Returns:
            True if all switches in batch succeeded, False otherwise
        """
        logger.info(f"Processing batch {batch_idx} with {len(batch)} switches (concurrent mode)...")

        batch_success = 0
        batch_failed = 0
        failed_switches = []

        # Process switches concurrently within the batch
        # IMPORTANT: Each switch gets its own database session to avoid concurrent access errors
        async def process_single_switch(switch: Switch):
            """Process a single switch with timeout protection and independent database session"""
            # Import here to avoid circular dependency issues
            from core.database import AsyncSessionLocal

            # Create independent database session for this switch
            # This prevents "This session is provisioning a new connection; concurrent operations
            # are not permitted" errors when processing switches concurrently
            async with AsyncSessionLocal() as switch_db:
                try:
                    # Add timeout protection to prevent stuck operations
                    async with asyncio.timeout(timeout_per_switch):
                        arp_count, mac_count = await self._collect_from_switch(
                            switch_db, switch, template_dicts
                        )

                        # Auto-resolve any existing alarms for this switch
                        await alarm_service.auto_resolve_alarms(
                            db=switch_db,
                            source_type=AlarmSourceType.SWITCH,
                            source_id=switch.id
                        )

                        # Commit this switch's changes in its own transaction
                        await switch_db.commit()

                        return {'success': True, 'switch': switch}

                except asyncio.TimeoutError:
                    await switch_db.rollback()
                    error_msg = f"Collection timeout ({timeout_per_switch}s exceeded)"
                    logger.error(f"  ❌ {switch.name}: {error_msg}")
                    return {
                        'success': False,
                        'switch': switch,
                        'error': error_msg,
                        'error_type': 'timeout'
                    }

                except Exception as e:
                    await switch_db.rollback()
                    error_msg = str(e)
                    error_type = type(e).__name__
                    logger.error(f"  ❌ {switch.name}: {error_msg}")
                    return {
                        'success': False,
                        'switch': switch,
                        'error': error_msg,
                        'error_type': error_type
                    }

        # Execute all switches concurrently
        results = await asyncio.gather(*[process_single_switch(switch) for switch in batch])

        # Process results
        for result in results:
            if result['success']:
                batch_success += 1
            else:
                batch_failed += 1
                failed_switches.append(result)

        logger.info(
            f"  Batch {batch_idx} completed: {batch_success}/{len(batch)} successful "
            f"(each switch commits independently)"
        )

        # If this batch had failures, create alarms for each failed switch
        if failed_switches:
            for failure_info in failed_switches:
                switch = failure_info['switch']
                try:
                    failure_message = failure_info['error']
                    if failure_info['error_type'].lower() == 'timeout':
                        failure_message = "Collection timeout exceeded"

                    await self._mark_switch_collection_failed(
                        db,
                        switch,
                        reason=failure_message,
                        collected_at=datetime.now()
                    )

                    # Determine severity based on error type
                    severity = AlarmSeverity.ERROR
                    if 'timeout' in failure_info['error_type'].lower():
                        severity = AlarmSeverity.WARNING
                    elif 'auth' in failure_info['error'].lower():
                        severity = AlarmSeverity.ERROR

                    await alarm_service.create_alarm(
                        db=db,
                        severity=severity,
                        title=f"Switch collection failed: {switch.name}",
                        message=failure_info['error'],
                        source_type=AlarmSourceType.SWITCH,
                        source_id=switch.id,
                        source_name=switch.name,
                        details={
                            'error_type': failure_info['error_type'],
                            'switch_ip': str(switch.ip_address),
                            'vendor': switch.vendor,
                            'model': switch.model
                        }
                    )
                    await db.commit()
                except Exception as e:
                    logger.error(f"  Failed to create alarm for {switch.name}: {str(e)}")
                    await db.rollback()

        # Batch succeeds if all switches succeeded
        return batch_failed == 0

    async def _store_arp_entries_bulk(
        self,
        db: AsyncSession,
        switch_id: int,
        entries: List[Dict],
        collected_at: datetime
    ):
        """
        Store ARP entries using REPLACE strategy (delete old, insert new).
        This prevents duplicate records from accumulating over time.

        Args:
            db: Database session
            switch_id: Switch ID
            entries: List of ARP entry dicts
            collected_at: Collection timestamp
        """
        # Step 1: Delete all existing ARP entries for this switch
        delete_result = await db.execute(
            delete(ARPTable).where(ARPTable.switch_id == switch_id)
        )
        deleted_count = delete_result.rowcount

        # Step 2: Bulk insert new entries
        if entries:
            to_insert = []
            for entry in entries:
                to_insert.append({
                    'switch_id': switch_id,
                    'ip_address': entry['ip_address'],
                    'mac_address': entry['mac_address'],
                    'vlan_id': entry.get('vlan_id'),
                    'interface': entry.get('interface'),
                    'age_seconds': entry.get('age_seconds'),
                    'collected_at': collected_at,
                    'last_seen': collected_at
                })

            await db.execute(
                insert(ARPTable),
                to_insert
            )

        logger.debug(
            f"  ARP REPLACE: deleted {deleted_count} old entries, inserted {len(entries)} new entries"
        )

    async def _store_mac_entries_bulk(
        self,
        db: AsyncSession,
        switch_id: int,
        entries: List[Dict],
        collected_at: datetime
    ):
        """
        Store MAC entries using REPLACE strategy (delete old, insert new).
        This prevents duplicate records from accumulating over time.

        Args:
            db: Database session
            switch_id: Switch ID
            entries: List of MAC entry dicts
            collected_at: Collection timestamp
        """
        # Step 1: Delete all existing MAC entries for this switch
        delete_result = await db.execute(
            delete(MACTable).where(MACTable.switch_id == switch_id)
        )
        deleted_count = delete_result.rowcount

        # Step 2: Bulk insert new entries
        if entries:
            to_insert = []
            for entry in entries:
                to_insert.append({
                    'switch_id': switch_id,
                    'mac_address': entry['mac_address'],
                    'port_name': entry['port_name'],
                    'vlan_id': entry.get('vlan_id'),
                    'is_dynamic': entry.get('is_dynamic', 1),
                    'collected_at': collected_at,
                    'last_seen': collected_at
                })

            await db.execute(
                insert(MACTable),
                to_insert
            )

        logger.debug(
            f"  MAC REPLACE: deleted {deleted_count} old entries, inserted {len(entries)} new entries"
        )

    async def collect_from_all_switches(
        self,
        db: AsyncSession
    ) -> Dict:
        """
        Collect ARP and MAC tables from all enabled switches

        Args:
            db: Database session

        Returns:
            Summary statistics
        """
        if self.collection_running:
            logger.warning("Collection already running, skipping")
            return {'status': 'skipped', 'reason': 'already_running'}

        try:
            self.collection_running = True
            start_time = datetime.now()

            logger.info("=" * 80)
            logger.info("Starting network data collection cycle")
            logger.info("=" * 80)

            # Step 1: Load command templates from database
            template_result = await db.execute(
                select(SwitchCommandTemplate).where(SwitchCommandTemplate.enabled == True)
            )
            templates = template_result.scalars().all()
            # Convert to dict format for CLI service
            template_dicts = [
                {
                    'vendor': t.vendor,
                    'model_pattern': t.model_pattern,
                    'name_pattern': t.name_pattern,
                    'device_type': t.device_type,
                    'arp_command': t.arp_command,
                    'arp_parser_type': t.arp_parser_type,
                    'arp_enabled': t.arp_enabled,
                    'mac_command': t.mac_command,
                    'mac_parser_type': t.mac_parser_type,
                    'mac_enabled': t.mac_enabled,
                    'priority': t.priority,
                    'enabled': t.enabled
                }
                for t in templates
            ]
            logger.info(f"Loaded {len(template_dicts)} command templates from database")

            # Step 2: Get all enabled switches that have CLI or SNMP configured
            from sqlalchemy import or_
            result = await db.execute(
                select(Switch).where(
                    and_(
                        Switch.enabled == True,
                        or_(
                            Switch.cli_enabled == True,
                            Switch.snmp_enabled == True
                        )
                    )
                )
            )
            switches = result.scalars().all()

            if not switches:
                logger.warning("No switches with CLI or SNMP configured found")
                return {
                    'status': 'completed',
                    'switches_processed': 0,
                    'message': 'No switches with CLI or SNMP configured'
                }

            logger.info(f"Found {len(switches)} switches to query (CLI or SNMP enabled)")

            # Step 2: Collect data from all switches using batch processing with retry
            logger.info("=" * 80)
            logger.info("BATCH COLLECTION WITH RETRY")
            logger.info("=" * 80)

            # Create batches of 5 switches (reduced for better concurrency)
            batches = self._create_batches(switches, batch_size=5)
            logger.info(f"Split {len(switches)} switches into {len(batches)} batches of 5 (concurrent processing)")

            switch_success = 0
            switch_failed = 0
            failed_batches = []

            # Process each batch with retry
            for batch_idx, batch in enumerate(batches):
                logger.info(f"\n--- Batch {batch_idx + 1}/{len(batches)} ---")

                success = await self._process_batch_with_retry(
                    db=db,
                    batch=batch,
                    batch_idx=batch_idx,
                    template_dicts=template_dicts,
                    max_retries=3
                )

                if not success:
                    logger.warning(f"  Batch {batch_idx} failed after retries, will retry later")
                    failed_batches.append((batch_idx, batch))

            # Final retry for all failed batches
            if failed_batches:
                logger.info("\n" + "=" * 80)
                logger.info(f"FINAL RETRY FOR {len(failed_batches)} FAILED BATCHES")
                logger.info("=" * 80)

                for batch_idx, batch in failed_batches:
                    logger.info(f"\n--- Final retry for batch {batch_idx + 1} ---")

                    success = await self._process_batch_with_retry(
                        db=db,
                        batch=batch,
                        batch_idx=batch_idx,
                        template_dicts=template_dicts,
                        max_retries=1,
                        is_final_retry=True
                    )

                    if success:
                        logger.info(f"  ✅ Batch {batch_idx} succeeded on final retry")
                    else:
                        logger.error(f"  ❌ Batch {batch_idx} failed on final retry")

                        # Clean up intermediate INFO alarms (no longer needed)
                        try:
                            await alarm_service.auto_resolve_alarms(
                                db=db,
                                source_type=AlarmSourceType.BATCH,
                                source_id=batch_idx,
                                severity=AlarmSeverity.INFO
                            )
                        except Exception as e:
                            logger.error(f"  Failed to auto-resolve INFO alarms: {str(e)}")

                        # Create batch-level failure alarm
                        try:
                            await alarm_service.create_alarm(
                                db=db,
                                severity=AlarmSeverity.CRITICAL,
                                title=f"Batch collection failed after all retries: Batch {batch_idx}",
                                message=f"Batch {batch_idx} with {len(batch)} switches failed after all retry attempts",
                                source_type=AlarmSourceType.BATCH,
                                source_id=batch_idx,
                                source_name=f"Batch {batch_idx}",
                                details={
                                    'switch_count': len(batch),
                                    'switch_names': [s.name for s in batch],
                                    'batch_index': batch_idx
                                }
                            )
                            await db.commit()
                        except Exception as e:
                            logger.error(f"  Failed to create batch alarm: {str(e)}")
                            await db.rollback()

            # Count final successes and failures by checking switch status
            for switch in switches:
                if switch.last_collection_status == 'success':
                    switch_success += 1
                else:
                    switch_failed += 1

            await db.commit()

            # Step 3: Analyze ports
            logger.info("Starting port analysis...")
            port_count = await self._analyze_all_ports(db)

            # Commit port analysis separately to ensure it's persisted
            await db.commit()
            logger.info(f"  ✅ Port analysis committed: {port_count} ports analyzed")

            # Step 4: Match IPs to locations
            logger.info("Starting IP location matching...")
            try:
                ip_count = await self._match_ip_locations(db)
                await db.commit()
                logger.info(f"  ✅ IP location matching committed: {ip_count} IPs located")
            except Exception as e:
                logger.error(f"  ❌ IP location matching failed: {str(e)}")
                await db.rollback()
                ip_count = 0
                # Continue with cleanup even if IP matching fails

            # Step 5: Cleanup old data (keep last 7 days)
            logger.info("Cleaning up old data...")
            try:
                await self._cleanup_old_data(db, days_to_keep=7)
                await db.commit()
                logger.info("  ✅ Cleanup completed")
            except Exception as e:
                logger.error(f"  ❌ Cleanup failed: {str(e)}")
                await db.rollback()

            elapsed = (datetime.now() - start_time).total_seconds()

            summary = {
                'status': 'completed',
                'started_at': start_time.isoformat(),
                'elapsed_seconds': round(elapsed, 2),
                'switches_total': len(switches),
                'switches_success': switch_success,
                'switches_failed': switch_failed,
                'ports_analyzed': port_count,
                'ips_located': ip_count
            }

            logger.info("=" * 80)
            logger.info(f"Collection completed in {elapsed:.1f}s")
            logger.info(f"  Switches: {switch_success}/{len(switches)} successful")
            logger.info(f"  Ports analyzed: {port_count}")
            logger.info(f"  IPs located: {ip_count}")
            logger.info("=" * 80)

            return summary

        finally:
            self.collection_running = False

    async def _collect_from_switch(
        self,
        db: AsyncSession,
        switch: Switch,
        templates: List[Dict] = None
    ) -> Tuple[int, int]:
        """
        Collect ARP and MAC tables from a single switch

        Args:
            templates: List of command templates from database

        Returns:
            (arp_count, mac_count)
        """
        logger.info(f"Collecting from switch: {switch.name} ({switch.ip_address})")

        collected_at = datetime.now()

        # If model is Unknown, try to get real device info via CLI
        if switch.model == 'Unknown' and switch.cli_enabled and switch.password_encrypted:
            logger.info(f"  Model is Unknown for {switch.name}, attempting to retrieve device info via CLI")
            try:
                # Determine device_type based on vendor
                device_type_map = {
                    'alcatel': 'nokia_sros',
                    'nokia': 'nokia_sros',
                    'dell': 'dell_os10',
                    'cisco': 'cisco_ios'
                }
                device_type = device_type_map.get(switch.vendor.lower(), 'generic')

                cli_config_temp = {
                    'username': switch.username,
                    'password_encrypted': switch.password_encrypted,
                    'vendor': switch.vendor,
                    'model': switch.model,
                    'name': switch.name,
                    'device_type': device_type,
                    'cli_transport': switch.cli_transport,
                    'ssh_port': switch.ssh_port,
                    'connection_timeout': switch.connection_timeout,
                    'enable_password_encrypted': switch.enable_password_encrypted
                }

                device_info = await asyncio.to_thread(
                    cli_service.get_device_info_cli,
                    str(switch.ip_address),
                    cli_config_temp
                )

                if device_info:
                    # Update switch information
                    updated = False

                    # Validate and update hostname
                    new_hostname = device_info.get('hostname')
                    if (new_hostname and
                        new_hostname != switch.name and
                        len(new_hostname) >= 2 and
                        new_hostname.strip() not in [':', '-', '_', '.'] and
                        any(c.isalnum() for c in new_hostname) and
                        not any(ord(c) < 32 for c in new_hostname)):  # Reject control characters
                        logger.info(f"  Updating switch name: {switch.name} -> {new_hostname}")
                        switch.name = new_hostname
                        updated = True
                    elif new_hostname:
                        logger.warning(f"  Skipping invalid hostname update: '{repr(new_hostname)}' (too short, invalid, or contains control characters)")

                    if device_info.get('model'):
                        logger.info(f"  Updating switch model: {switch.model} -> {device_info['model']}")
                        switch.model = device_info['model']
                        updated = True

                    # Note: software_version field doesn't exist in switches table
                    # if device_info.get('version'):
                    #     logger.info(f"  Software version: {device_info['version']}")

                    if updated:
                        # Mark object as modified (will be committed at batch end)
                        db.add(switch)
                        logger.info(f"  ✅ Device info updated successfully for {switch.name}")
                else:
                    logger.warning(f"  Could not retrieve device info for {switch.name}")

            except Exception as e:
                logger.warning(f"  Failed to get device info for {switch.name}: {str(e)}")

        cli_config = {
            'username': switch.username,
            'password_encrypted': switch.password_encrypted,
            'vendor': switch.vendor,
            'model': switch.model,
            'name': switch.name,
            'cli_transport': switch.cli_transport,
            'ssh_port': switch.ssh_port,
            'connection_timeout': switch.connection_timeout,
            'enable_password_encrypted': switch.enable_password_encrypted
        }

        from config.collection_strategy import CollectionStrategy

        global_l2_method = CollectionStrategy.get_l2_table_primary_method()

        # Collect ARP table using the global L2 CLI-only policy
        arp_entries = []
        arp_result_detail = "No ARP method attempted"

        logger.info(f"  Using global ARP/MAC collection strategy for {switch.name}: {global_l2_method}")
        if switch.cli_enabled and switch.password_encrypted:
            logger.info(f"  Collecting ARP via CLI (global policy) for {switch.name}")
            try:
                arp_entries = await asyncio.to_thread(
                    cli_service.collect_arp_table_cli,
                    str(switch.ip_address),
                    cli_config,
                    templates
                )
                if len(arp_entries) > 0:
                    logger.info(f"  ✅ CLI ARP collection successful: {len(arp_entries)} entries")
                    arp_result_detail = f"CLI succeeded with {len(arp_entries)} ARP entries"
                else:
                    logger.info(f"  CLI returned 0 ARP entries for {switch.name}")
                    arp_result_detail = "CLI returned 0 ARP entries"
            except Exception as e:
                logger.warning(f"  CLI ARP collection failed for {switch.name}: {str(e)}")
                arp_result_detail = f"CLI failed for ARP collection: {str(e)}"
        else:
            arp_result_detail = "CLI credentials are not configured"
            logger.warning(f"  CLI ARP collection skipped for {switch.name}: {arp_result_detail}")

        # Store ARP entries using bulk operations
        await self._store_arp_entries_bulk(db, switch.id, arp_entries, collected_at)

        # Collect MAC table using the same global L2 CLI-only policy
        mac_entries = []
        mac_result_detail = "No MAC method attempted"

        if switch.cli_enabled and switch.password_encrypted:
            logger.info(f"  Collecting MAC via CLI (global policy) for {switch.name}")
            try:
                mac_entries = await asyncio.to_thread(
                    cli_service.collect_mac_table_cli,
                    str(switch.ip_address),
                    cli_config,
                    templates
                )
                if len(mac_entries) > 0:
                    logger.info(f"  ✅ CLI MAC collection successful: {len(mac_entries)} entries")
                    mac_result_detail = f"CLI succeeded with {len(mac_entries)} MAC entries"
                else:
                    logger.info(f"  CLI returned 0 MAC entries for {switch.name}")
                    mac_result_detail = "CLI returned 0 MAC entries"
            except Exception as e:
                logger.warning(f"  CLI MAC collection failed for {switch.name}: {str(e)}")
                mac_result_detail = f"CLI failed for MAC collection: {str(e)}"
        else:
            mac_result_detail = "CLI credentials are not configured"
            logger.warning(f"  CLI MAC collection skipped for {switch.name}: {mac_result_detail}")


        # Store MAC entries using bulk operations
        await self._store_mac_entries_bulk(db, switch.id, mac_entries, collected_at)

        logger.info(f"  Collected {len(arp_entries)} ARP, {len(mac_entries)} MAC entries from {switch.name}")

        # Diagnostic logging for zero MAC entries (port analysis will be skipped)
        if len(mac_entries) == 0:
            logger.warning(
                f"  ⚠️  ZERO MAC entries from {switch.name} (ID: {switch.id}, IP: {switch.ip_address}). "
                f"CLI: {switch.cli_enabled}, SNMP: {switch.snmp_enabled}. "
                f"Port analysis will be SKIPPED for this switch."
            )

        if len(arp_entries) == 0 and len(mac_entries) == 0:
            failure_message = self._build_collection_failure_message(
                switch,
                mac_result_detail,
                arp_result_detail
            )
            await self._mark_switch_collection_failed(
                db,
                switch,
                reason=failure_message,
                collected_at=collected_at
            )
            raise RuntimeError(failure_message)

        # Update switch's last collection timestamp and status.
        switch.last_arp_collection_at = collected_at
        switch.last_mac_collection_at = collected_at
        switch.last_collection_status = 'success'
        switch.last_collection_message = (
            f"ARP: {len(arp_entries)} 条, MAC: {len(mac_entries)} 条"
        )

        return (len(arp_entries), len(mac_entries))

    async def _analyze_all_ports(self, db: AsyncSession) -> int:
        """
        Analyze all ports based on MAC table data

        Returns:
            Number of ports analyzed
        """
        # Get all switches
        result = await db.execute(select(Switch))
        switches = result.scalars().all()

        total_ports = 0

        for switch in switches:
            summary = await self.refresh_port_analysis_for_switch(db, switch)
            total_ports += summary['ports_analyzed']

        return total_ports

    async def _match_ip_locations(self, db: AsyncSession) -> int:
        """
        Match all IPs to switch ports

        Returns:
            Number of IPs located
        """
        # Get recent ARP and MAC data
        cutoff_time = datetime.now() - timedelta(hours=24)

        # Get ARP records
        result = await db.execute(
            select(ARPTable).where(ARPTable.last_seen >= cutoff_time)
        )
        arp_records = result.scalars().all()

        # Get MAC records
        result = await db.execute(
            select(MACTable).where(MACTable.last_seen >= cutoff_time)
        )
        mac_records = result.scalars().all()

        # Get port analysis
        result = await db.execute(select(PortAnalysis))
        port_analysis_records = result.scalars().all()

        # Convert to dict formats
        arp_dicts = [
            {
                'ip_address': str(a.ip_address),
                'mac_address': a.mac_address,
                'switch_id': a.switch_id,
                'vlan_id': a.vlan_id,
                'age_seconds': a.age_seconds,
                'collected_at': a.collected_at
            }
            for a in arp_records
        ]

        mac_dicts = [
            {
                'mac_address': m.mac_address,
                'port_name': port_analysis_service.normalize_port_name(m.port_name),
                'switch_id': m.switch_id,
                'vlan_id': m.vlan_id
            }
            for m in mac_records
        ]

        port_analysis_dict = {
            (p.switch_id, port_analysis_service.normalize_port_name(p.port_name)): {
                'port_type': p.port_type,
                'mac_count': p.mac_count,
                'confidence_score': p.confidence_score,
                'lookup_policy_override': p.lookup_policy_override
            }
            for p in port_analysis_records
        }

        # Match IPs
        matches = ip_location_engine.match_all_ips(
            arp_dicts,
            mac_dicts,
            port_analysis_dict
        )

        # Deduplicate matches by IP (keep highest confidence)
        unique_matches = {}
        for match in matches:
            ip = match['ip_address']
            if ip not in unique_matches or match['confidence_score'] > unique_matches[ip]['confidence_score']:
                unique_matches[ip] = match

        logger.info(f"  Matched {len(matches)} total, {len(unique_matches)} unique IPs")

        # Store matches
        stored_count = 0
        for match in unique_matches.values():
            try:
                result = await db.execute(
                    select(IPLocation).where(
                        cast(IPLocation.ip_address, Text) == match['ip_address']
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update if confidence is better or data is newer
                    if match['confidence_score'] >= existing.confidence_score:
                        existing.mac_address = match['mac_address']
                        existing.switch_id = match['switch_id']
                        existing.port_name = match['port_name']
                        existing.vlan_id = match['vlan_id']
                        existing.confidence_score = match['confidence_score']
                        existing.detection_method = match['detection_method']
                        existing.port_mac_count = match['port_mac_count']
                        existing.appears_on_switches = match['appears_on_switches']
                        existing.last_confirmed = datetime.now()
                        existing.last_arp_seen = datetime.now()
                        existing.last_mac_seen = datetime.now()
                        stored_count += 1
                else:
                    # Create new
                    location = IPLocation(
                        ip_address=match['ip_address'],
                        mac_address=match['mac_address'],
                        switch_id=match['switch_id'],
                        port_name=match['port_name'],
                        vlan_id=match['vlan_id'],
                        confidence_score=match['confidence_score'],
                        detection_method=match['detection_method'],
                        port_mac_count=match['port_mac_count'],
                        appears_on_switches=match['appears_on_switches'],
                        last_arp_seen=datetime.now(),
                        last_mac_seen=datetime.now()
                    )
                    db.add(location)
                    stored_count += 1
            except Exception as e:
                logger.warning(f"  Failed to store location for {match['ip_address']}: {str(e)}")
                continue

        return stored_count

    async def _cleanup_old_data(self, db: AsyncSession, days_to_keep: int = 7):
        """Remove old ARP and MAC table entries"""
        cutoff = datetime.now() - timedelta(days=days_to_keep)

        # Delete old ARP entries
        await db.execute(
            ARPTable.__table__.delete().where(ARPTable.last_seen < cutoff)
        )

        # Delete old MAC entries
        await db.execute(
            MACTable.__table__.delete().where(MACTable.last_seen < cutoff)
        )

        logger.info(f"Cleaned up data older than {days_to_keep} days")

    async def collect_optical_modules_from_all_switches(
        self,
        db: AsyncSession
    ) -> Dict:
        """
        Collect optical module information from all enabled switches.
        This runs on a separate schedule from ARP/MAC collection (recommended: every 12 hours).

        Args:
            db: Database session

        Returns:
            Summary statistics
        """
        start_time = datetime.now()

        logger.info("=" * 80)
        logger.info("Starting optical module collection cycle")
        logger.info("=" * 80)

        # Get all enabled switches that have CLI or SNMP configured
        from sqlalchemy import or_
        result = await db.execute(
            select(Switch).where(
                and_(
                    Switch.enabled == True,
                    or_(
                        Switch.cli_enabled == True,
                        Switch.snmp_enabled == True
                    )
                )
            )
        )
        switches = result.scalars().all()

        if not switches:
            logger.warning("No switches with CLI or SNMP configured found")
            return {
                'status': 'completed',
                'switches_processed': 0,
                'message': 'No switches with CLI or SNMP configured'
            }

        logger.info(f"Found {len(switches)} switches to query for optical modules")

        switches_success = 0
        switches_failed = 0
        total_modules_collected = 0

        # Process switches in smaller batches to avoid overwhelming the network
        batch_size = 3  # Smaller batches since optical module collection can take longer
        batches = self._create_batches(switches, batch_size=batch_size)

        for batch_idx, batch in enumerate(batches):
            logger.info(f"\n--- Processing batch {batch_idx + 1}/{len(batches)} ({len(batch)} switches) ---")

            # Process sequentially within the batch. Optical collection is network-heavy
            # and the shared session should not be used concurrently.
            for switch in batch:
                result = await self._collect_optical_modules_from_switch(db, switch)
                if isinstance(result, Exception):
                    logger.error(f"  ❌ {switch.name}: {str(result)}")
                    switches_failed += 1
                elif result:
                    modules_count = result.get('modules_count', 0)
                    total_modules_collected += modules_count
                    if result.get('status') in ['success', 'empty']:
                        switches_success += 1
                    else:
                        switches_failed += 1

                    if result.get('status') == 'success' and modules_count > 0:
                        logger.info(f"  ✅ {switch.name}: {modules_count} modules")
                    elif result.get('status') == 'empty':
                        logger.info(f"  ⚪ {switch.name}: No modules found, historical inventory preserved")
                    else:
                        logger.warning(f"  ❌ {switch.name}: {result.get('message') or 'Optical collection failed'}")
                else:
                    switches_failed += 1

            # Persist each batch so long-running full optical collection improves
            # the search page progressively instead of holding all updates until the end.
            await db.commit()

        elapsed = (datetime.now() - start_time).total_seconds()

        summary = {
            'status': 'completed',
            'started_at': start_time.isoformat(),
            'elapsed_seconds': round(elapsed, 2),
            'switches_total': len(switches),
            'switches_success': switches_success,
            'switches_failed': switches_failed,
            'total_modules': total_modules_collected
        }

        logger.info("=" * 80)
        logger.info(f"Optical module collection completed in {elapsed:.1f}s")
        logger.info(f"  Switches: {switches_success}/{len(switches)} successful")
        logger.info(f"  Total modules collected: {total_modules_collected}")
        logger.info("=" * 80)

        return summary

    async def _collect_optical_modules_from_switch(
        self,
        db: AsyncSession,
        switch: Switch
    ) -> Optional[Dict]:
        """
        Collect optical modules from a single switch.

        Args:
            db: Database session
            switch: Switch object

        Returns:
            Dictionary with collection results or None if failed
        """
        try:
            modules = await self.collect_optical_single_switch(db, switch)
            return {
                'modules_count': len(modules),
                'collection_method': switch.optical_collection_method,
                'status': switch.last_optical_collection_status or ('success' if modules else 'failed'),
                'message': switch.last_optical_collection_message,
            }

        except Exception as e:
            logger.error(f"Error collecting optical modules from {switch.name}: {str(e)}")
            return None

    async def collect_mac_single_switch(self, db: AsyncSession, switch: Switch) -> List[Dict]:
        """
        Collect MAC table from a single switch using the global CLI-only policy.
        """
        from services.cli_service import cli_service

        collected_at = datetime.utcnow()
        mac_entries = []
        method_used = None
        switch.mac_collection_method = 'cli'
        switch.mac_method_override = False

        if switch.cli_enabled and switch.password_encrypted:
            cli_start = datetime.utcnow()
            try:
                templates = await self._load_command_templates(db)
                # Close the read transaction before the SSH call blocks on network I/O.
                await db.commit()
                cli_config = self._build_cli_config(switch)

                mac_entries = await asyncio.to_thread(
                    cli_service.collect_mac_table_cli,
                    str(switch.ip_address),
                    cli_config,
                    templates
                )

                if len(mac_entries) > 0:
                    method_used = 'cli'
                    logger.info(f"✅ CLI MAC collection successful: {len(mac_entries)} entries from {switch.name}")
                    switch.mac_collection_success_count += 1

            except Exception as e:
                elapsed = (datetime.utcnow() - cli_start).total_seconds()
                logger.error(f"CLI MAC collection failed for {switch.name} after {elapsed:.1f}s: {str(e)}")
        else:
            logger.warning(f"CLI MAC collection skipped for {switch.name}: CLI credentials are not configured")

        # Handle failure case
        if len(mac_entries) == 0:
            switch.mac_collection_fail_count += 1
            logger.warning(f"⚠️  Zero MAC entries from {switch.name} under global CLI-only policy")
        else:
            # Store collected data
            await self._store_mac_entries_bulk(db, switch.id, mac_entries, collected_at)
            analysis_summary = await self.refresh_port_analysis_for_switch(db, switch)
            switch.last_mac_collection_at = collected_at
            switch.last_collection_status = 'success'
            switch.last_collection_message = (
                f"MAC: {len(mac_entries)} entries via {method_used}; "
                f"Port analysis: {analysis_summary['ports_analyzed']} ports"
            )
            return mac_entries

        # A zero-entry run is still a fresh collection attempt. Refresh the timestamp
        # so the UI reflects the latest attempt instead of showing stale "1 day ago" data.
        switch.last_mac_collection_at = collected_at
        switch.last_collection_status = 'partial'
        switch.last_collection_message = "MAC: 0 entries after trying all available methods"
        return mac_entries

    async def collect_arp_single_switch(self, db: AsyncSession, switch: Switch) -> List[Dict]:
        """
        Collect ARP table from a single switch using the global CLI-only policy.
        """
        from services.cli_service import cli_service

        collected_at = datetime.utcnow()
        arp_entries = []
        method_used = None
        switch.arp_collection_method = 'cli'
        switch.arp_method_override = False

        if switch.cli_enabled and switch.password_encrypted:
            cli_start = datetime.utcnow()
            try:
                templates = await self._load_command_templates(db)
                # Close the read transaction before the SSH call blocks on network I/O.
                await db.commit()
                cli_config = self._build_cli_config(switch)

                arp_entries = await asyncio.to_thread(
                    cli_service.collect_arp_table_cli,
                    str(switch.ip_address),
                    cli_config,
                    templates
                )

                if len(arp_entries) > 0:
                    method_used = 'cli'
                    logger.info(f"✅ CLI ARP collection successful: {len(arp_entries)} entries from {switch.name}")
                    switch.arp_collection_success_count += 1

            except Exception as e:
                elapsed = (datetime.utcnow() - cli_start).total_seconds()
                logger.error(f"CLI ARP collection failed for {switch.name} after {elapsed:.1f}s: {str(e)}")
        else:
            logger.warning(f"CLI ARP collection skipped for {switch.name}: CLI credentials are not configured")

        # Handle failure case
        if len(arp_entries) == 0:
            switch.arp_collection_fail_count += 1
            logger.warning(f"⚠️  Zero ARP entries from {switch.name} under global CLI-only policy")
        else:
            # Store collected data
            await self._store_arp_entries_bulk(db, switch.id, arp_entries, collected_at)
            switch.last_arp_collection_at = collected_at
            switch.last_collection_status = 'success'
            switch.last_collection_message = f"ARP: {len(arp_entries)} entries via {method_used}"
            return arp_entries

        # A zero-entry run is still a fresh collection attempt. Refresh the timestamp
        # so the UI reflects the latest attempt instead of showing stale "1 day ago" data.
        switch.last_arp_collection_at = collected_at
        switch.last_collection_status = 'partial'
        switch.last_collection_message = "ARP: 0 entries after trying all available methods"
        return arp_entries

    async def collect_optical_single_switch(self, db: AsyncSession, switch: Switch) -> List[Dict]:
        """
        Collect optical modules from a single switch using learned collection method.
        Returns list of optical module entries with capability detection and learning.
        """
        from services.snmp_service import snmp_service
        from services.cli_service import cli_service

        collected_at = datetime.utcnow()
        optical_modules = []
        method_used = None
        empty_collection_confirmed = False
        failure_reasons: List[str] = []

        # Determine collection method based on learned preference
        if switch.optical_method_override:
            # Manual override - use specified method only
            preferred_method = switch.optical_collection_method
            logger.info(f"Using manual override method '{preferred_method}' for optical on {switch.name}")
        elif switch.optical_collection_method == 'snmp':
            # Learned preference: SNMP works for this switch
            preferred_method = 'snmp'
            logger.debug(f"Using learned SNMP method for optical on {switch.name}")
        elif switch.optical_collection_method == 'cli':
            # Learned preference: CLI works for this switch
            preferred_method = 'cli'
            logger.debug(f"Using learned CLI method for optical on {switch.name}")
        else:
            # Auto mode: Try vendor-based default
            vendor_lower = switch.vendor.lower() if switch.vendor else ''
            preferred_method = 'snmp' if vendor_lower in ['cisco', 'dell'] else 'cli'
            logger.debug(f"Auto mode: trying {preferred_method} first for optical on {switch.name}")

        # Try preferred method first
        if preferred_method == 'snmp' and switch.snmp_enabled and switch.snmp_auth_password_encrypted:
            try:
                snmp_config = self._get_snmp_config(switch)
                optical_modules = await asyncio.wait_for(
                    snmp_service.collect_optical_modules(str(switch.ip_address), snmp_config),
                    timeout=60.0
                )

                if len(optical_modules) > 0:
                    method_used = 'snmp'
                    logger.info(f"✅ SNMP optical collection successful: {len(optical_modules)} modules from {switch.name}")

                    # Update success count and method preference
                    switch.optical_collection_success_count += 1
                    if switch.optical_collection_method != 'snmp' and not switch.optical_method_override:
                        switch.optical_collection_method = 'snmp'  # Learn preference
                        logger.info(f"Learned: {switch.name} prefers SNMP for optical collection")
                elif not (switch.cli_enabled and switch.password_encrypted) or (
                    preferred_method == 'snmp' and switch.optical_method_override
                ):
                    method_used = 'snmp'
                    empty_collection_confirmed = True

            except asyncio.TimeoutError:
                logger.warning(f"SNMP optical timeout for {switch.name} (60s)")
                failure_reasons.append("SNMP timeout")
            except Exception as e:
                logger.warning(f"SNMP optical failed for {switch.name}: {str(e)}")
                failure_reasons.append(f"SNMP failed: {str(e)}")

        # Fallback to CLI if SNMP failed/disabled or returned nothing
        if len(optical_modules) == 0 and not (preferred_method == 'cli' and switch.optical_method_override):
            if switch.cli_enabled and switch.password_encrypted:
                try:
                    cli_config = self._build_cli_config(switch)

                    # Vendor-specific timeout (Alcatel needs longer)
                    vendor_lower = switch.vendor.lower() if switch.vendor else ''
                    timeout = 300.0 if vendor_lower in ['alcatel', 'nokia'] else 90.0

                    optical_modules = await asyncio.wait_for(
                        asyncio.to_thread(
                            cli_service.collect_optical_modules_cli,
                            str(switch.ip_address),
                            cli_config,
                            switch.vendor,
                            switch.model
                        ),
                        timeout=timeout
                    )

                    if len(optical_modules) > 0:
                        method_used = 'cli'
                        logger.info(f"✅ CLI optical collection successful: {len(optical_modules)} modules from {switch.name}")

                        # Update success count and method preference
                        switch.optical_collection_success_count += 1
                        if switch.optical_collection_method != 'cli' and not switch.optical_method_override:
                            switch.optical_collection_method = 'cli'  # Learn preference
                            logger.info(f"Learned: {switch.name} prefers CLI for optical collection")
                    else:
                        method_used = 'cli'
                        empty_collection_confirmed = True

                except asyncio.TimeoutError:
                    logger.warning(f"CLI optical timeout for {switch.name}")
                    failure_reasons.append("CLI timeout")
                except Exception as e:
                    logger.error(f"CLI optical collection failed for {switch.name}: {str(e)}")
                    failure_reasons.append(f"CLI failed: {str(e)}")

        if len(optical_modules) > 0:
            stored_count = await self._store_optical_modules_snapshot(
                db, switch, optical_modules, collected_at
            )
            self._set_optical_collection_state(
                switch,
                collected_at=collected_at,
                status='success',
                message=f"Optical: {stored_count} modules via {method_used or 'unknown'}",
                modules_count=stored_count,
                mark_success=True
            )
            return optical_modules

        if empty_collection_confirmed:
            switch.optical_collection_success_count += 1
            if method_used and switch.optical_collection_method != method_used and not switch.optical_method_override:
                switch.optical_collection_method = method_used
            self._set_optical_collection_state(
                switch,
                collected_at=collected_at,
                status='empty',
                message=f"Optical: 0 modules via {method_used or 'completed query'}; historical inventory preserved",
                modules_count=0,
                mark_success=True
            )
            logger.info(f"Confirmed zero optical modules on {switch.name}; preserving historical inventory")
            return optical_modules

        switch.optical_collection_fail_count += 1
        failure_message = (
            "; ".join(failure_reasons)
            if failure_reasons else
            "Optical collection failed before any valid snapshot was produced"
        )
        if switch.is_reachable is False:
            failure_message = f"Switch currently offline. {failure_message}"

        self._set_optical_collection_state(
            switch,
            collected_at=collected_at,
            status='failed',
            message=failure_message,
            modules_count=None,
            mark_success=False
        )
        logger.warning(f"⚠️  Optical collection failed for {switch.name}: {failure_message}")

        return optical_modules


# Singleton instance
network_data_collector = NetworkDataCollector()
