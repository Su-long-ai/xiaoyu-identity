#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dedicated loopback proxy for the independently frozen Halu stream-cap amendment."""
from __future__ import annotations
import research_api_proxy as base_proxy
from confirmatory_stream_cap_gateway_v1 import RecoveryCapBudget, install_authorized_amendment

def main():
    install_authorized_amendment()
    # Keep exact original HTTP parsing/error handling; replace only budget class.
    base_proxy.ResearchApiBudget=RecoveryCapBudget
    base_proxy.Handler.server_version="XiaoYuRecoveryCapProxy/1.0"
    base_proxy.main()

if __name__=="__main__":
    main()
