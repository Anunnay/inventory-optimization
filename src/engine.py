import numpy as np
import pandas as pd
from scipy.stats import norm

# ---------------------------------------------------------
# Inventory Models
# ---------------------------------------------------------

def calculate_eoq(annual_demand: float, ordering_cost: float, holding_cost_rate: float, unit_cost: float) -> float:
    """Calculates Economic Order Quantity (EOQ)."""
    if annual_demand <= 0 or unit_cost <= 0 or holding_cost_rate <= 0:
        return 0.0
    h = unit_cost * holding_cost_rate
    eoq = np.sqrt((2 * annual_demand * ordering_cost) / h)
    return np.round(eoq, 0)

def calculate_safety_stock(std_daily_demand: float, lead_time: int, service_level: float) -> float:
    """Calculates Safety Stock using normal distribution assumption."""
    if std_daily_demand <= 0 or lead_time <= 0:
        return 0.0
    z_score = norm.ppf(service_level)
    std_lt = std_daily_demand * np.sqrt(lead_time)
    return np.round(z_score * std_lt, 0)

def calculate_rop(avg_daily_demand: float, lead_time: int, safety_stock: float) -> float:
    """Calculates Reorder Point (ROP)."""
    lead_time_demand = avg_daily_demand * lead_time
    return np.round(lead_time_demand + safety_stock, 0)

# ---------------------------------------------------------
# Replenishment Engine & Risk
# ---------------------------------------------------------

def generate_replenishment_plan(df_summary: pd.DataFrame, assumptions: dict) -> pd.DataFrame:
    """Applies models across the Store x SKU dataframe."""
    df = df_summary.copy()
    
    # Extract assumptions
    sl = assumptions['service_level']
    lt = assumptions['lead_time']
    hc_rate = assumptions['holding_cost_rate']
    order_cost = assumptions['ordering_cost']
    
    # 1. Derived Metrics
    df['safety_stock'] = df.apply(lambda x: calculate_safety_stock(x['std_daily_demand'], lt, sl), axis=1)
    df['rop'] = df.apply(lambda x: calculate_rop(x['avg_daily_demand'], lt, x['safety_stock']), axis=1)
    df['eoq'] = df.apply(lambda x: calculate_eoq(x['annualized_demand'], order_cost, hc_rate, x['unit_cost_proxy']), axis=1)
    
    # Handle zero EOQ (e.g., zero demand items)
    df['eoq'] = df['eoq'].replace(0, 1)

    # 2. Modeled Current Inventory (Since M5 lacks actual inventory state)
    np.random.seed(42) # For reproducibility
    df['modeled_on_hand'] = np.random.uniform(df['safety_stock'], df['rop'] + df['eoq']).round(0)
    df['modeled_on_order'] = 0 # Assumed 0 for snapshot
    df['inventory_position'] = df['modeled_on_hand'] + df['modeled_on_order']

    # 3. Replenishment Logic
    df['requires_replenishment'] = df['inventory_position'] <= df['rop']
    df['recommended_order_qty'] = np.where(
        df['requires_replenishment'], 
        np.maximum(df['eoq'], df['rop'] - df['inventory_position']), 
        0
    )
    
    # 4. Risk & Days of Supply
    df['days_of_supply'] = np.where(
        df['avg_daily_demand'] > 0, 
        df['modeled_on_hand'] / df['avg_daily_demand'], 
        999
    )
    df['days_until_stockout'] = df['days_of_supply'].round(1)
    
    # Risk Classification (Rule-based)
    conditions = [
        (df['days_until_stockout'] <= lt),
        (df['days_until_stockout'] <= lt + (df['safety_stock']/df['avg_daily_demand'].replace(0,1))),
        (df['days_until_stockout'] > lt)
    ]
    choices = ['HIGH', 'MEDIUM', 'LOW']
    df['stockout_risk'] = np.select(conditions, choices, default='LOW')
    
    # Action
    df['action'] = np.where(df['requires_replenishment'], 'ORDER NOW', 
                   np.where(df['modeled_on_hand'] > (df['rop'] + df['eoq'] * 1.5), 'EXCESS', 'MONITOR'))

    # 5. Cost Estimation
    df['est_holding_cost'] = df['modeled_on_hand'] * (df['unit_cost_proxy'] * hc_rate)
    df['est_orders_per_year'] = df['annualized_demand'] / df['eoq']
    df['est_ordering_cost'] = df['est_orders_per_year'] * order_cost
    df['est_total_relevant_cost'] = df['est_holding_cost'] + df['est_ordering_cost']

    return df

# ---------------------------------------------------------
# Inventory Historical Simulation
# ---------------------------------------------------------

def simulate_inventory_history(daily_demand: pd.Series, initial_inventory: float, rop: float, eoq: float, lead_time: int) -> pd.DataFrame:
    """Simulates daily inventory flow over historical data to validate policies."""
    n = len(daily_demand)
    on_hand = np.zeros(n)
    on_order = np.zeros(n)
    
    current_inventory = initial_inventory
    orders_pipeline = []
    
    for i in range(n):
        arrived_qty = sum(order['qty'] for order in orders_pipeline if order['arrive_day'] == i)
        current_inventory += arrived_qty
        orders_pipeline = [order for order in orders_pipeline if order['arrive_day'] > i]
        
        demand_today = daily_demand.iloc[i]
        current_inventory -= demand_today
        
        on_hand[i] = current_inventory
        on_order[i] = sum(order['qty'] for order in orders_pipeline)
        
        inv_position = current_inventory + on_order[i]
        if inv_position <= rop:
            orders_pipeline.append({'arrive_day': i + lead_time, 'qty': eoq})
            
    return pd.DataFrame({
        'demand': daily_demand.values,
        'on_hand': on_hand,
        'on_order': on_order
    }, index=daily_demand.index)