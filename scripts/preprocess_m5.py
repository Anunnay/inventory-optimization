import pandas as pd
import numpy as np
import os
import sys

def preprocess_m5(data_dir="../data"):
    """
    Reads the raw M5 CSVs, transforms them into an analysis-friendly format, 
    aggregates demand metrics, and exports optimized Parquet files.
    """
    
    # 1. File path setup
    # If running from inside the 'scripts' folder, the data folder is one level up
    if not os.path.exists(data_dir):
        # Fallback in case they run it from the root directory instead of the scripts directory
        data_dir = "data" 
        
    sales_file = os.path.join(data_dir, "sales_train_validation.csv")
    calendar_file = os.path.join(data_dir, "calendar.csv")
    prices_file = os.path.join(data_dir, "sell_prices.csv")

    # 2. Validation check
    if not os.path.exists(sales_file):
        print(f"ERROR: Could not find {sales_file}.")
        print("Please ensure you downloaded the M5 files and placed them in the 'data' folder.")
        sys.exit(1)

    print("Loading raw M5 datasets (this may take a minute or two)...")
    sales = pd.read_csv(sales_file)
    calendar = pd.read_csv(calendar_file)
    prices = pd.read_csv(prices_file)

    # 3. Filtering to keep the project manageable on a standard laptop
    # The full dataset is 50M+ rows. We will sample 2 stores to demonstrate the logic.
    print("Filtering data to CA_1 and TX_1 stores for performance...")
    stores_to_keep = ['CA_1', 'TX_1']
    sales = sales[sales['store_id'].isin(stores_to_keep)].copy()
    
    # 4. Melting the data (Wide to Long)
    print("Melting sales data from wide to long format...")
    id_vars = ['id', 'item_id', 'dept_id', 'cat_id', 'store_id', 'state_id']
    sales_melted = pd.melt(sales, id_vars=id_vars, var_name='d', value_name='demand')

    # 5. Merging Calendar & Pricing
    print("Merging calendar and pricing information...")
    # Join calendar to get actual dates and the week ID (wm_yr_wk) for pricing
    sales_merged = pd.merge(sales_melted, calendar[['d', 'date', 'wm_yr_wk']], on='d', how='left')
    sales_merged['date'] = pd.to_datetime(sales_merged['date'])

    # Join prices based on store, item, and week
    sales_final = pd.merge(sales_merged, prices, on=['store_id', 'item_id', 'wm_yr_wk'], how='left')
    
    # Handle missing prices: fill with the median price of that specific item
    print("Handling missing prices...")
    sales_final['sell_price'] = sales_final.groupby('item_id')['sell_price'].transform(lambda x: x.fillna(x.median()))
    
    # Drop columns we no longer need to save memory
    sales_final.drop(columns=['wm_yr_wk', 'd', 'state_id'], inplace=True)
    
    # Drop rows where price is completely missing (item never sold)
    sales_final.dropna(subset=['sell_price'], inplace=True) 

    # 6. Aggregating Historical Metrics (Store x SKU Grain)
    print("Aggregating historical metrics for the Replenishment Engine...")
    summary = sales_final.groupby(['store_id', 'item_id', 'cat_id', 'dept_id']).agg(
        total_demand=('demand', 'sum'),
        avg_daily_demand=('demand', 'mean'),
        std_daily_demand=('demand', 'std'),
        max_daily_demand=('demand', 'max'),
        unit_cost_proxy=('sell_price', 'last'), # Using last observed selling price as the unit cost proxy
        active_days=('date', 'nunique')
    ).reset_index()

    # Calculate Annualized Demand for EOQ formula
    summary['annualized_demand'] = summary['avg_daily_demand'] * 365
    
    # Fill NA standard deviations (happens if an item only has 1 day of history)
    summary['std_daily_demand'] = summary['std_daily_demand'].fillna(0)

    # 7. Exporting to Parquet
    print("Saving processed files to Parquet (for instant Streamlit loading)...")
    history_path = os.path.join(data_dir, "m5_daily_history.parquet")
    summary_path = os.path.join(data_dir, "m5_store_sku_summary.parquet")
    
    sales_final.to_parquet(history_path, index=False)
    summary.to_parquet(summary_path, index=False)
    
    print("\n✅ Preprocessing complete!")
    print(f"Created: {history_path}")
    print(f"Created: {summary_path}")
    print("You can now run: streamlit run app.py")

if __name__ == "__main__":
    preprocess_m5()