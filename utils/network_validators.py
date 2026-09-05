import re
import ipaddress


def validate_address_spec(addr_str: str):
    """
    Validates a comma-separated list of IPv4 addresses/CIDRs or a single alias.
    Returns the parsed list of strings or None if input is empty.
    Raises ValueError on validation failure.
    """
    if not addr_str:
        return None

    parts = [p.strip() for p in addr_str.split(',') if p.strip()]
    if not parts:
        return None

    has_alias = any(p.startswith('@') for p in parts)

    if has_alias:
        if len(parts) > 1:
            raise ValueError("alias must be the only element (no mixing)")
        alias = parts[0]
        # Convert @om to @alias_om internally
        if alias.startswith('@') and not alias.startswith('@alias_'):
            alias = '@alias_' + alias[1:]
        # Check alias format
        if not re.match(r"^@alias_[a-zA-Z0-9_-]{1,64}$", alias):
            raise ValueError(f"Invalid alias format: {alias}")
        parts[0] = alias
    else:
        # Check that each part is a valid IPv4 network or address
        seen = set()
        for p in parts:
            if p in seen:
                raise ValueError(f"Duplicate address: {p}")
            seen.add(p)
            try:
                # Can be an address or network
                ipaddress.IPv4Network(p, strict=False)
            except ValueError:
                raise ValueError(f"Invalid IPv4 address or CIDR network: {p}")

    if len(parts) > 64:
        raise ValueError("Addresses list cannot exceed 64 elements")

    return parts


def validate_port_spec(port_val):
    """
    Validates a port specification string (e.g. '80,443,8000-8080').
    Returns the sanitized port string or None if empty.
    Raises ValueError on validation failure.
    """
    if not port_val:
        return None

    # If it is integer, convert to string
    if isinstance(port_val, int):
        port_val = str(port_val)

    if not isinstance(port_val, str):
        raise ValueError("Port must be a string or integer")

    # Check for whitespace, trailing/double commas
    if ' ' in port_val:
        raise ValueError("Whitespace is not allowed in port specification")
    if port_val.startswith(',') or port_val.endswith(',') or ',,' in port_val:
        raise ValueError("Malformed port specification with empty elements")

    parts = port_val.split(',')
    if len(parts) > 64:
        raise ValueError("Ports specification cannot exceed 64 elements")

    parsed_ranges = []
    seen_elements = set()

    for part in parts:
        if not part:
            raise ValueError("Malformed port specification with empty elements")
        if part in seen_elements:
            raise ValueError(f"Duplicate element: {part}")
        seen_elements.add(part)

        if '-' in part:
            # Range format lo-hi
            range_parts = part.split('-')
            if len(range_parts) != 2:
                raise ValueError(f"Invalid range format: {part}")
            lo_str, hi_str = range_parts
            if not lo_str.isdigit() or not hi_str.isdigit():
                raise ValueError(f"Port range values must be digits: {part}")
            lo, hi = int(lo_str), int(hi_str)
            if not (1 <= lo <= 65535) or not (1 <= hi <= 65535):
                raise ValueError(f"Port range out of bounds (1-65535): {part}")
            if lo >= hi:
                raise ValueError(f"Port range start must be less than its end: {part}")
            parsed_ranges.append((lo, hi))
        else:
            # Single port
            if not part.isdigit():
                raise ValueError(f"Invalid port value: {part}")
            port = int(part)
            if not (1 <= port <= 65535):
                raise ValueError(f"Port out of bounds (1-65535): {port}")
            parsed_ranges.append((port, port))

    # Check for overlaps between all ranges
    for i in range(len(parsed_ranges)):
        for j in range(i + 1, len(parsed_ranges)):
            r1 = parsed_ranges[i]
            r2 = parsed_ranges[j]
            if max(r1[0], r2[0]) <= min(r1[1], r2[1]):
                raise ValueError(f"Overlapping or duplicate elements: {parts[i]} and {parts[j]}")

    return port_val


def validate_route_network(arg1, target_peer_id: str, arg3=None, all_routes: list = None, active_route_overrides: dict = None):
    """
    Validates a network CIDR string and ensures it's not assigned to another peer of the same customer.
    Normalizes host addresses inside a subnet (strict=False).
    
    Supports two calling conventions:
    1. validate_route_network(customer, target_peer_id, network)
    2. validate_route_network(network, target_peer_id, allowed_peer_ids, all_routes, active_route_overrides)
    
    Returns (is_valid: bool, error_message: str, normalized_network: str).
    """
    # Detect signature mode
    if isinstance(arg1, str) and (isinstance(arg3, (set, list, tuple)) or all_routes is not None):
        # Pure functional mode: (network, target_peer_id, allowed_peer_ids, all_routes, active_route_overrides)
        network = arg1
        allowed_peer_ids = set(arg3) if arg3 else set()
        routes_list = all_routes or []
        route_overrides = active_route_overrides or {}
    else:
        # Customer entity mode: (customer, target_peer_id, network)
        customer = arg1
        network = arg3 if isinstance(arg3, str) else ""
        allowed_peer_ids = set()
        routes_list = []
        route_overrides = {}
        if customer:
            try:
                from services.netbird_service import (
                    get_cached_customer_peer_ids,
                    get_cached_all_netbird_routes,
                    get_api_base_url,
                    get_api_headers
                )
                from utils.cache_manager import get_active_route_overrides
                allowed_peer_ids = get_cached_customer_peer_ids(customer)
                routes_list = get_cached_all_netbird_routes(get_api_base_url(), get_api_headers())
                route_overrides = get_active_route_overrides()
            except Exception:
                pass

    if not network:
        return True, "", ""

    try:
        net_obj = ipaddress.ip_network(network.strip(), strict=False)
        if net_obj.version != 4:
            return False, "Only IPv4 supported", ""
        normalized_network = str(net_obj)
    except ValueError:
        return False, "Invalid subnet", ""

    for r in routes_list:
        r_peer = r.get("peer")
        if r_peer in allowed_peer_ids and r_peer != target_peer_id:
            r_net = route_overrides.get(r_peer) or r.get("network", "")
            if r_net:
                try:
                    r_obj = ipaddress.ip_network(r_net.strip(), strict=False)
                    if str(r_obj).lower() == normalized_network.lower():
                        return False, "Subnet already in use", ""
                except ValueError:
                    if r_net.strip().lower() == normalized_network.lower():
                        return False, "Subnet already in use", ""

    return True, "", normalized_network
