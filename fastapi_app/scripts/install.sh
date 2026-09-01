#!/usr/bin/env bash
set -e

# الألوان للتنسيق البصري
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}      Networkat SD-WAN Installer        ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

echo -e "${YELLOW}[*] Testing script execution...${NC}"
sleep 1

echo -e "${GREEN}[✓] Connection established successfully!${NC}"
echo -e "[i] Hostname : $(hostname)"
echo -e "[i] OS Kernel: $(uname -s -r)"
echo -e "[i] Current User: $(whoami)"
echo -e "[i] Date     : $(date)"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}      Installer Test Passed (OK)        ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""