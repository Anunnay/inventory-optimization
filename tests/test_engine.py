import numpy as np
import pytest
from src.engine import calculate_eoq, calculate_safety_stock, calculate_rop

def test_calculate_eoq():
    # Standard optimal order calculation
    assert calculate_eoq(annual_demand=1000, ordering_cost=10, holding_cost_rate=0.2, unit_cost=10) == 100
    
    # Edge case: Zero demand should result in zero EOQ
    assert calculate_eoq(annual_demand=0, ordering_cost=10, holding_cost_rate=0.2, unit_cost=10) == 0.0
    
    # Edge case: Missing cost data
    assert calculate_eoq(annual_demand=1000, ordering_cost=10, holding_cost_rate=0, unit_cost=10) == 0.0

def test_calculate_safety_stock():
    # A 95% service level has a Z-score of approx 1.645
    # Standard Dev = 2, Lead Time = 9 days
    # Math: 1.645 * (2 * sqrt(9)) = 1.645 * 6 = 9.87 (rounds to 10)
    assert calculate_safety_stock(std_daily_demand=2, lead_time=9, service_level=0.95) == 10

def test_calculate_rop():
    # Avg Demand = 5, Lead Time = 4, Safety Stock = 10
    # Math: (5 * 4) + 10 = 30
    assert calculate_rop(avg_daily_demand=5, lead_time=4, safety_stock=10) == 30