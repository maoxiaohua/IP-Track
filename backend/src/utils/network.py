"""
Network utilities for ping and connectivity checks
"""
import asyncio
import platform
from typing import Dict, Optional


async def ping_host(host: str, timeout: int = 2, count: int = 1) -> Dict[str, any]:
    """
    Ping a host to check if it's reachable

    Args:
        host: IP address or hostname to ping
        timeout: Timeout in seconds
        count: Number of ping packets to send

    Returns:
        Dict with status, response_time, and packet_loss
    """
    # Determine ping command based on OS
    system = platform.system().lower()

    if system == "windows":
        ping_cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
    else:  # Linux, macOS, etc.
        ping_cmd = ["ping", "-c", str(count), "-W", str(timeout), host]

    try:
        # Run ping command
        process = await asyncio.create_subprocess_exec(
            *ping_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout + 1
        )

        # Check if ping was successful
        if process.returncode == 0:
            output = stdout.decode()

            # Parse response time (basic parsing)
            response_time = None
            if system == "windows":
                # Windows format: "Average = 1ms"
                if "Average" in output:
                    try:
                        avg_line = [line for line in output.split('\n') if 'Average' in line][0]
                        response_time = float(avg_line.split('=')[1].strip().replace('ms', ''))
                    except:
                        pass
            else:
                # Linux/macOS format: "min/avg/max/stddev = 0.123/0.456/0.789/0.012 ms"
                if "min/avg/max" in output or "rtt min/avg/max" in output:
                    try:
                        stats_line = [line for line in output.split('\n') if 'min/avg/max' in line or 'rtt min/avg/max' in line][0]
                        avg_time = stats_line.split('=')[1].strip().split('/')[1]
                        response_time = float(avg_time)
                    except:
                        pass

            return {
                "reachable": True,
                "response_time_ms": response_time,
                "packet_loss": 0
            }
        else:
            return {
                "reachable": False,
                "response_time_ms": None,
                "packet_loss": 100
            }

    except asyncio.TimeoutError:
        return {
            "reachable": False,
            "response_time_ms": None,
            "packet_loss": 100
        }
    except Exception as e:
        return {
            "reachable": False,
            "response_time_ms": None,
            "packet_loss": 100,
            "error": str(e)
        }


async def ping_multiple_hosts(hosts: list, timeout: int = 2) -> Dict[str, Dict]:
    """
    Ping multiple hosts concurrently

    Args:
        hosts: List of IP addresses or hostnames
        timeout: Timeout in seconds for each ping

    Returns:
        Dict mapping host to ping result
    """
    tasks = [ping_host(host, timeout) for host in hosts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return {
        host: result if not isinstance(result, Exception) else {
            "reachable": False,
            "response_time_ms": None,
            "packet_loss": 100,
            "error": str(result)
        }
        for host, result in zip(hosts, results)
    }
