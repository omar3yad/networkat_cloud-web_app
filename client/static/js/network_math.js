/**
 * Networkat SD-WAN Global Mathematical IPv4 Subnet Validation & Normalization Engine
 */
(function () {
    'use strict';

    function parseAndValidateIPv4(input, options = {}) {
        const {
            requireMask = false,
            allowMask = true,
            normalizeSubnet = true
        } = options;

        if (!input || typeof input !== 'string') {
            return { valid: false, error: 'Required' };
        }

        const trimmed = input.trim();
        if (!trimmed) {
            return { valid: false, error: 'Required' };
        }

        if (trimmed.includes(':')) {
            return { valid: false, error: 'Only IPv4 supported' };
        }

        const slashCount = (trimmed.match(/\//g) || []).length;
        if (slashCount > 1) {
            return { valid: false, error: 'Invalid format (multiple /)' };
        }

        let ipStr = trimmed;
        let maskStr = undefined;

        if (slashCount === 1) {
            if (!allowMask) {
                return { valid: false, error: 'Subnet mask not allowed here' };
            }
            const parts = trimmed.split('/');
            ipStr = parts[0];
            maskStr = parts[1];
        } else if (requireMask) {
            return { valid: false, error: 'Subnet mask required (e.g. /24)' };
        }

        // Validate IP part
        const octets = ipStr.split('.');
        if (octets.length !== 4) {
            return { valid: false, error: 'Must contain 4 octets (x.x.x.x)' };
        }

        const parsedNums = [];
        for (let i = 0; i < 4; i++) {
            const octet = octets[i];
            if (!octet || !/^\d+$/.test(octet)) {
                return { valid: false, error: `Octet ${i + 1} (${octet || 'empty'}) is invalid` };
            }
            if (octet.length > 1 && octet.startsWith('0')) {
                return { valid: false, error: `Octet ${i + 1} (${octet}) has invalid leading zero` };
            }
            const num = parseInt(octet, 10);
            if (num < 0 || num > 255) {
                return { valid: false, error: `Octet ${i + 1} (${octet}) must be 0-255` };
            }
            parsedNums.push(num);
        }

        // Validate Mask part if present
        let prefix = null;
        if (maskStr !== undefined) {
            if (!maskStr || !/^\d+$/.test(maskStr)) {
                return { valid: false, error: `Invalid subnet mask /${maskStr || ''}` };
            }
            if (maskStr.length > 1 && maskStr.startsWith('0')) {
                return { valid: false, error: `Subnet mask /${maskStr} has invalid leading zero` };
            }
            prefix = parseInt(maskStr, 10);
            if (prefix < 0 || prefix > 32) {
                return { valid: false, error: `Subnet mask /${maskStr} must be 0-32` };
            }
        }

        // Calculate unsigned 32-bit integer for IP
        const ip32 = ((parsedNums[0] << 24) >>> 0) +
                     ((parsedNums[1] << 16) >>> 0) +
                     ((parsedNums[2] << 8) >>> 0) +
                     (parsedNums[3] >>> 0);

        let networkIp = ipStr;
        let wasAdjusted = false;

        if (prefix !== null && normalizeSubnet) {
            let netmask32 = 0;
            if (prefix === 0) {
                netmask32 = 0;
            } else {
                netmask32 = (0xFFFFFFFF << (32 - prefix)) >>> 0;
            }

            const net32 = (ip32 & netmask32) >>> 0;
            const net0 = (net32 >>> 24) & 255;
            const net1 = (net32 >>> 16) & 255;
            const net2 = (net32 >>> 8) & 255;
            const net3 = net32 & 255;
            networkIp = `${net0}.${net1}.${net2}.${net3}`;
            wasAdjusted = (networkIp !== ipStr);
        }

        const normalized = (prefix !== null) ? `${networkIp}/${prefix}` : ipStr;

        return {
            valid: true,
            raw: trimmed,
            ip: ipStr,
            prefix: prefix,
            hasMask: prefix !== null,
            networkIp: networkIp,
            normalized: normalized,
            wasAdjusted: wasAdjusted
        };
    }

    // Expose globally
    window.parseAndValidateIPv4 = parseAndValidateIPv4;
    window.validateAndNormalizeIPv4 = parseAndValidateIPv4;
})();
