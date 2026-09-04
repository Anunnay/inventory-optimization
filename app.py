import streamlit as st
import pandas as pd
import plotly.express as px
import os
from src.engine import generate_replenishment_plan, simulate_inventory_history

# --- Page Config ---
st.set_page_config(page_title="Inventory Replenishment Engine", layout="wide")

# --- Data Loading ---
@st.cache_data
def load_data():
    try:
        summary = pd.read_parquet(os.path.join("data", "m5_store_sku_summary.parquet"))
        history = pd.read_parquet(os.path.join("data", "m5_daily_history.parquet"))
        return summary, history
    except FileNotFoundError:
        st.error("Data not found. Please run scripts/preprocess_m5.py first.")
        st.stop()

df_summary, df_history = load_data()

# --- Sidebar Controls & Assumptions ---
st.sidebar.title("Navigation & Parameters")
page = st.sidebar.radio("Go to:", [
    "Executive Overview", 
    "SKU / Store Analysis", 
    "Replenishment Recommendations",
    "What-If / Scenario Analysis"
])

st.sidebar.markdown("---")
st.sidebar.header("Global Assumptions")
st.sidebar.caption("These parameters are missing from M5 data and are modeled dynamically.")

service_level = st.sidebar.selectbox("Target Service Level", [0.90, 0.95, 0.975, 0.99], index=1)
lead_time = st.sidebar.slider("Supplier Lead Time (Days)", 1, 30, 7)
holding_cost_rate = st.sidebar.slider("Annual Holding Cost Rate (%)", 5, 50, 20) / 100.0
ordering_cost = st.sidebar.number_input("Cost per Order ($)", min_value=1.0, max_value=500.0, value=50.0)

assumptions = {
    'service_level': service_level,
    'lead_time': lead_time,
    'holding_cost_rate': holding_cost_rate,
    'ordering_cost': ordering_cost
}

# Generate operational state based on assumptions
@st.cache_data
def get_current_plan(summary_data, current_assumptions):
    return generate_replenishment_plan(summary_data, current_assumptions)

df_plan = get_current_plan(df_summary, assumptions)

# --- Page 1: Executive Overview ---
if page == "Executive Overview":
    st.title("Executive Overview")
    st.markdown("Supply-chain decision support analyzing observed M5 retail demand against modeled inventory policies.")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Active SKUs", f"{df_plan['item_id'].nunique():,}")
    col2.metric("Total Modeled Inventory Units", f"{df_plan['modeled_on_hand'].sum():,.0f}")
    col3.metric("SKUs Requiring Replenishment", f"{df_plan['requires_replenishment'].sum():,}")
    col4.metric("High-Risk Stockout SKUs", f"{len(df_plan[df_plan['stockout_risk'] == 'HIGH']):,}")
    
    st.markdown("---")
    colA, colB = st.columns(2)
    
    with colA:
        st.subheader("Inventory Status Distribution")
        fig_status = px.pie(df_plan, names='action', hole=0.4, color='action',
                            color_discrete_map={'ORDER NOW': 'red', 'MONITOR': 'green', 'EXCESS': 'orange'})
        st.plotly_chart(fig_status, use_container_width=True)
        
    with colB:
        st.subheader("Estimated Inventory Value by Category")
        df_plan['inventory_value'] = df_plan['modeled_on_hand'] * df_plan['unit_cost_proxy']
        val_by_cat = df_plan.groupby('cat_id')['inventory_value'].sum().reset_index()
        fig_val = px.bar(val_by_cat, x='cat_id', y='inventory_value', text_auto='.2s')
        st.plotly_chart(fig_val, use_container_width=True)

# --- Page 2: SKU / Store Analysis ---
elif page == "SKU / Store Analysis":
    st.title("SKU / Store Deep Dive")
    
    col1, col2 = st.columns(2)
    with col1:
        selected_store = st.selectbox("Select Store", df_plan['store_id'].unique())
    with col2:
        store_items = df_plan[df_plan['store_id'] == selected_store]['item_id'].unique()
        selected_sku = st.selectbox("Select SKU", store_items)
        
    sku_data = df_plan[(df_plan['store_id'] == selected_store) & (df_plan['item_id'] == selected_sku)].iloc[0]
    
    st.subheader(f"Inventory Policy & Current State: {selected_sku} at {selected_store}")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Modeled On Hand", sku_data['modeled_on_hand'])
    c2.metric("Reorder Point (ROP)", sku_data['rop'])
    c3.metric("Safety Stock", sku_data['safety_stock'])
    c4.metric("EOQ", sku_data['eoq'])
    c5.metric("Action", sku_data['action'])
    
    st.markdown("### Historical Demand & Inventory Simulation")
    history_sku = df_history[(df_history['store_id'] == selected_store) & (df_history['item_id'] == selected_sku)].sort_values('date')
    history_sku.set_index('date', inplace=True)
    
    sim_df = simulate_inventory_history(
        history_sku['demand'], 
        initial_inventory=sku_data['rop'] + sku_data['eoq'],
        rop=sku_data['rop'], 
        eoq=sku_data['eoq'], 
        lead_time=assumptions['lead_time']
    )
    
    fig_sim = px.line(sim_df, y=['on_hand', 'demand'], title="Modeled Inventory Behavior Based on Historical Demand")
    fig_sim.add_hline(y=sku_data['rop'], line_dash="dash", line_color="red", annotation_text="Reorder Point")
    fig_sim.add_hline(y=sku_data['safety_stock'], line_dash="dash", line_color="orange", annotation_text="Safety Stock")
    st.plotly_chart(fig_sim, use_container_width=True)

# --- Page 3: Replenishment Recommendations ---
elif page == "Replenishment Recommendations":
    st.title("Actionable Replenishment Recommendations")
    st.markdown("Prioritized list of items requiring immediate review based on modeled inventory constraints.")
    
    view_df = df_plan[['store_id', 'item_id', 'cat_id', 'avg_daily_demand', 'modeled_on_hand', 
                       'inventory_position', 'rop', 'eoq', 'recommended_order_qty', 'days_until_stockout', 
                       'stockout_risk', 'action']].copy()
                       
    view_df = view_df.sort_values(by=['stockout_risk', 'days_until_stockout'], ascending=[True, True])
    
    def style_risk(val):
        color = 'red' if val == 'HIGH' else 'orange' if val == 'MEDIUM' else 'green'
        return f'color: {color}; font-weight: bold'

    st.dataframe(view_df.style.map(style_risk, subset=['stockout_risk']), use_container_width=True)

# --- Page 4: What-If / Scenario Analysis ---
elif page == "What-If / Scenario Analysis":
    st.title("Scenario Analysis: Lead Time & Service Level Shocks")
    st.markdown("Adjust parameters below to see the impact on total safety stock requirements and estimated costs.")
    
    col1, col2 = st.columns(2)
    with col1:
        new_sl = st.slider("Simulated Service Level", 0.85, 0.999, 0.95, 0.01)
    with col2:
        new_lt = st.slider("Simulated Lead Time", 1, 30, 14)
        
    alt_assumptions = assumptions.copy()
    alt_assumptions['service_level'] = new_sl
    alt_assumptions['lead_time'] = new_lt
    
    df_alt = get_current_plan(df_summary, alt_assumptions)
    
    c1, c2, c3 = st.columns(3)
    
    base_ss = df_plan['safety_stock'].sum()
    alt_ss = df_alt['safety_stock'].sum()
    c1.metric("Total Safety Stock Units", f"{alt_ss:,.0f}", f"{alt_ss - base_ss:,.0f} units")
    
    base_rop = df_plan['rop'].sum()
    alt_rop = df_alt['rop'].sum()
    c2.metric("Total ROP Level", f"{alt_rop:,.0f}", f"{alt_rop - base_rop:,.0f} units")
    
    base_risk = len(df_plan[df_plan['stockout_risk'] == 'HIGH'])
    alt_risk = len(df_alt[df_alt['stockout_risk'] == 'HIGH'])
    c3.metric("High Risk SKUs", f"{alt_risk:,}", f"{alt_risk - base_risk:,} items", delta_color="inverse")