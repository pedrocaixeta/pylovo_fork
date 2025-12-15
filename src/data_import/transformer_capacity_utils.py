#!/usr/bin/env python3
"""
Utility functions for transformer capacity management.

This module provides functions to work with transformer capacities
defined in the config_generation.yaml file.
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import CONFIG_GENERATION


def get_transformer_capacities() -> List[Dict[str, int]]:
    """
    Get available transformer capacities from config_generation.yaml.
    
    Returns:
        List[Dict[str, int]]: List of transformer capacity dictionaries with keys:
            - name: Equipment name (e.g., 'Tr_100')
            - s_max_kva: Maximum apparent power in kVA
            - cost_eur: Cost in EUR
            - typ: Equipment type (should be 'Transformer')
    """
    if not CONFIG_GENERATION or 'EQUIPMENT_DATA' not in CONFIG_GENERATION:
        return []
    
    transformer_capacities = []
    for equipment in CONFIG_GENERATION['EQUIPMENT_DATA']:
        if equipment.get('typ') == 'Transformer':
            transformer_capacities.append({
                'name': equipment['name'],
                's_max_kva': equipment['s_max_kva'],
                'cost_eur': equipment['cost_eur'],
                'typ': equipment['typ']
            })
    
    # Sort by capacity for consistent ordering
    transformer_capacities.sort(key=lambda x: x['s_max_kva'])
    return transformer_capacities


def get_transformer_capacity_options() -> List[Dict[str, str]]:
    """
    Get transformer capacity options formatted for UI dropdown.
    
    Returns:
        List[Dict[str, str]]: List of capacity options with keys:
            - value: Capacity value (kVA as string)
            - label: Display label (e.g., '100 kVA')
            - name: Equipment name (e.g., 'Tr_100')
    """
    capacities = get_transformer_capacities()
    options = []
    
    for capacity in capacities:
        options.append({
            'value': str(capacity['s_max_kva']),
            'label': f"{capacity['s_max_kva']} kVA ({capacity['name']})",
            'name': capacity['name']
        })
    
    return options


def get_transformer_capacity_by_name(name: str) -> Optional[Dict[str, int]]:
    """
    Get transformer capacity details by equipment name.
    
    Args:
        name (str): Equipment name (e.g., 'Tr_100')
        
    Returns:
        Optional[Dict[str, int]]: Transformer capacity dictionary or None if not found
    """
    capacities = get_transformer_capacities()
    for capacity in capacities:
        if capacity['name'] == name:
            return capacity
    return None


def get_transformer_capacity_by_kva(kva: int) -> Optional[Dict[str, int]]:
    """
    Get transformer capacity details by kVA rating.
    
    Args:
        kva (int): Transformer capacity in kVA
        
    Returns:
        Optional[Dict[str, int]]: Transformer capacity dictionary or None if not found
    """
    capacities = get_transformer_capacities()
    for capacity in capacities:
        if capacity['s_max_kva'] == kva:
            return capacity
    return None


def validate_transformer_capacity(capacity: int) -> bool:
    """
    Validate if a transformer capacity is available in the configuration.
    
    Args:
        capacity (int): Transformer capacity in kVA to validate
        
    Returns:
        bool: True if capacity is valid, False otherwise
    """
    capacities = get_transformer_capacities()
    valid_capacities = [c['s_max_kva'] for c in capacities]
    return capacity in valid_capacities


if __name__ == "__main__":
    # Test the functions
    print("Available transformer capacities:")
    capacities = get_transformer_capacities()
    for cap in capacities:
        print(f"  {cap['name']}: {cap['s_max_kva']} kVA (€{cap['cost_eur']})")
    
    print("\nUI options:")
    options = get_transformer_capacity_options()
    for opt in options:
        print(f"  {opt['value']}: {opt['label']}")
    
    print(f"\nValidation tests:")
    print(f"  100 kVA valid: {validate_transformer_capacity(100)}")
    print(f"  999 kVA valid: {validate_transformer_capacity(999)}")