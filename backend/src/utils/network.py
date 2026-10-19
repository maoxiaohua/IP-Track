"""
Network utilities for ping and connectivity checks
"""
import asyncio
import ipaddress
import platform
from typing import Any, Dict, Optional


# 这些字样说明收到的是中间设备回送的 ICMP 差错报文（TTL 超时/目标不可达），
# 只证明目标地址可路由，不能证明目标主机存活。
_ICMP_NON_ECHO_MARKERS = (
    "time to live exceeded",    # Linux: "From <router> icmp_seq=1 Time to live exceeded"
    "ttl expired in transit",   # Windows: "Reply from <router>: TTL expired in transit"
    "time exceeded",            # 其他 iputils/ping 版本的写法
    "unreachable",              # Destination host/net/port unreachable
    "request timed out",
)


def _is_echo_reply_from_host(output: str, host: str) -> bool:
    """回包必须来自目标本身（Echo Reply）才判定存活。

    只看退出码不够：Windows 的 ping 在收到中间路由器回送的
    "TTL expired in transit" 时，退出码仍然是 0。
    """
    text = (output or "").lower()
    if not text:
        return False
    if any(marker in text for marker in _ICMP_NON_ECHO_MARKERS):
        return False

    target = host.strip().lower()
    # 只看成功的回包行，避免被 "PING <ip> (<ip>)" 头部行误命中
    reply_lines = [
        line for line in text.splitlines()
        if "bytes from" in line or "reply from" in line
    ]
    # Linux: "64 bytes from 10.1.2.3: icmp_seq=1 ..."
    # Linux 反解主机名: "64 bytes from sw1.corp (10.1.2.3): ..."
    # Windows: "Reply from 10.1.2.3: bytes=32 ..."
    if any(f"from {target}" in line or f"({target})" in line for line in reply_lines):
        return True
    try:
        ipaddress.ip_address(target)
    except ValueError:
        # 目标是主机名时 ping 只回显解析后的地址，无法按字面比对，放宽为"确有回包即存活"
        return bool(reply_lines)
    return False


async def _terminate_process(process) -> None:
    """Kill a ping subprocess and reap it, so no orphan/zombie is left behind."""
    if process.returncode is not None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        return
    except Exception:
        pass
    try:
        await process.communicate()
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


async def ping_host(host: str, timeout: float = 2, count: int = 1) -> Dict[str, Any]:
    """
    Ping a host to check if it's reachable

    Args:
        host: IP address or hostname to ping
        timeout: Timeout in seconds (fractions allowed, e.g. 0.5)
        count: Number of ping packets to send

    Returns:
        Dict with status, response_time, and packet_loss
    """
    # Determine ping command based on OS
    system = platform.system().lower()

    if system == "windows":
        ping_cmd = ["ping", "-n", str(count), "-w", str(int(timeout * 1000)), host]
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
        output = stdout.decode()
        if process.returncode == 0 and _is_echo_reply_from_host(output, host):

            # Parse response time (basic parsing)
            response_time = None
            if system == "windows":
                # Windows format: "Average = 1ms"
                if "Average" in output:
                    try:
                        avg_line = [line for line in output.split('\n') if 'Average' in line][0]
                        response_time = float(avg_line.split('=')[1].strip().replace('ms', ''))
                    except Exception:
                        pass
            else:
                # Linux/macOS format: "min/avg/max/stddev = 0.123/0.456/0.789/0.012 ms"
                if "min/avg/max" in output or "rtt min/avg/max" in output:
                    try:
                        stats_line = [line for line in output.split('\n') if 'min/avg/max' in line or 'rtt min/avg/max' in line][0]
                        avg_time = stats_line.split('=')[1].strip().split('/')[1]
                        response_time = float(avg_time)
                    except Exception:
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
        await _terminate_process(process)
        return {
            "reachable": False,
            "response_time_ms": None,
            "packet_loss": 100
        }
    except asyncio.CancelledError:
        # Caller cancelled (e.g. scan aborted): never leave the ping child running
        await _terminate_process(process)
        raise
    except Exception as e:
        return {
            "reachable": False,
            "response_time_ms": None,
            "packet_loss": 100,
            "error": str(e)
        }


async def ping_multiple_hosts(
    hosts: list[str],
    timeout: float = 2,
    concurrency: int = 50
) -> Dict[str, Dict[str, Any]]:
    """
    Ping multiple hosts concurrently

    Args:
        hosts: List of IP addresses or hostnames
        timeout: Timeout in seconds for each ping

    Returns:
        Dict mapping host to ping result
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def ping_with_limit(host: str) -> Dict[str, Any]:
        async with semaphore:
            return await ping_host(host, timeout)

    tasks = [ping_with_limit(host) for host in hosts]
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
