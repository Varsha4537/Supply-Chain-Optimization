import streamlit as st
import pandas as pd
import numpy as np
import networkx as nx
import plotly.graph_objects as go

# =========================================
# 1. LOAD MASTER NETWORK DATA ONCE
# =========================================

@st.cache_data
def load_master_data():
    xls = pd.ExcelFile("Supply chain logisitcs problem.xlsx")
    df_dict = {name: xls.parse(name) for name in xls.sheet_names}

    order_list         = df_dict['OrderList']
    freight_rates      = df_dict['FreightRates']
    wh_costs           = df_dict['WhCosts']
    wh_capacity        = df_dict['WhCapacities']
    products_per_plant = df_dict['ProductsPerPlant']
    plant_ports        = df_dict['PlantPorts']

    # Normalization helper
    def _norm_ids(series):
        return series.astype(str).str.strip().str.upper()

    # Normalize order_list (for historical mapping)
    order_list['Customer']         = _norm_ids(order_list['Customer'])
    order_list['Plant Code']       = _norm_ids(order_list['Plant Code'])
    order_list['Origin Port']      = _norm_ids(order_list['Origin Port'])
    order_list['Destination Port'] = _norm_ids(order_list['Destination Port'])
    order_list['Service Level']    = order_list['Service Level'].astype(str).str.strip().str.upper()

    # Normalize freight rates
    freight_rates['orig_port_cd']  = _norm_ids(freight_rates['orig_port_cd'])
    freight_rates['dest_port_cd']  = _norm_ids(freight_rates['dest_port_cd'])

    # Normalize WH costs
    wh_costs['WH'] = _norm_ids(wh_costs['WH'])
    wh_costs.columns = [c.strip() for c in wh_costs.columns]

    # Normalize products per plant
    products_per_plant['Plant Code'] = _norm_ids(products_per_plant['Plant Code'])
    products_per_plant['Product ID'] = products_per_plant['Product ID'].astype(str).str.strip()

    # Normalize plant ports
    plant_ports['Plant Code'] = _norm_ids(plant_ports['Plant Code'])
    plant_ports['Port']       = _norm_ids(plant_ports['Port'])

    # Handling cost per unit at each plant/warehouse
    wh_cost_per_unit = wh_costs.set_index('WH')['Cost/unit'].to_dict()

    # Products each plant can make
    plant_products = (
        products_per_plant
        .groupby('Plant Code')['Product ID']
        .apply(set)
        .to_dict()
    )

    # Ports available for each plant
    plant_to_ports = (
        plant_ports
        .groupby('Plant Code')['Port']
        .apply(list)
        .to_dict()
    )

    # Customer → Destination Port mapping (from historical orders)
    cust_dest_port = (
        order_list
        .groupby('Customer')['Destination Port']
        .first()
        .to_dict()
    )

    # Average weight per UNIT per product (for new orders)
    wl = order_list.copy()
    wl['Product ID'] = wl['Product ID'].astype(str).str.strip()
    weight_per_unit = (
        wl.groupby('Product ID')[['Weight', 'Unit quantity']]
        .sum()
        .assign(avg_wgt_per_unit=lambda d: d['Weight'] / d['Unit quantity'].replace(0, np.nan))
        ['avg_wgt_per_unit']
        .to_dict()
    )

    return {
        "order_list": order_list,
        "freight_rates": freight_rates,
        "wh_cost_per_unit": wh_cost_per_unit,
        "plant_products": plant_products,
        "plant_to_ports": plant_to_ports,
        "cust_dest_port": cust_dest_port,
        "weight_per_unit": weight_per_unit,
    }

master = load_master_data()

freight_rates      = master["freight_rates"]
wh_cost_per_unit   = master["wh_cost_per_unit"]
plant_products     = master["plant_products"]
plant_to_ports     = master["plant_to_ports"]
cust_dest_port     = master["cust_dest_port"]
weight_per_unit    = master["weight_per_unit"]

# Normalization helper reused for uploaded file
def _norm_ids(series):
    return series.astype(str).str.strip().str.upper()


# =========================================
# 2. FREIGHT COST FUNCTION (REUSED)
# =========================================

def compute_freight_cost(plant, dest_port, weight):
    """
    Compute total transport cost for one shipment:
    - Try all origin ports for this plant (from plant_to_ports)
    - Use FreightRates brackets for each lane
    - Return minimum cost across ports
    """
    if weight <= 0:
        return 0.0

    possible_ports = plant_to_ports.get(plant, [])
    if not possible_ports:
        return np.inf

    best_total_cost = np.inf

    for oport in possible_ports:
        sub = freight_rates[
            (freight_rates['orig_port_cd'] == oport) &
            (freight_rates['dest_port_cd'] == dest_port)
        ]

        if sub.empty:
            continue

        # rows whose bracket covers this shipment's weight
        in_bracket = sub[
            (sub['minm_wgh_qty'] <= weight) &
            (sub['max_wgh_qty'] >= weight)
        ]

        if in_bracket.empty:
            # fallback: use the row with largest max weight
            row = sub.loc[sub['max_wgh_qty'].idxmax()]
            total_cost = max(row['minimum cost'], row['rate'] * weight)
        else:
            tmp = in_bracket.copy()
            tmp['total_cost'] = np.maximum(tmp['minimum cost'], tmp['rate'] * weight)
            row = tmp.sort_values('total_cost').iloc[0]
            total_cost = row['total_cost']

        if total_cost < best_total_cost:
            best_total_cost = total_cost

    return best_total_cost


def best_plant_for_order(customer_id, product_id, units):
    """
    For a given order (customer, product, units):
    - Find destination port from cust_dest_port
    - Estimate weight from weight_per_unit
    - For each plant that can make the product:
        - compute freight + WH handling cost
    - Return plant, origin port, costs
    """
    cust = str(customer_id).strip().upper()
    prod = str(product_id).strip()

    dest_port = cust_dest_port.get(cust, None)
    if dest_port is None:
        return None  # unknown destination port

    # Estimate weight
    avg_wgt = weight_per_unit.get(prod, None)
    if avg_wgt is None:
        # fallback: assume 1 weight per unit if unknown
        avg_wgt = 1.0
    weight = units * avg_wgt

    best = None

    for plant, prods in plant_products.items():
        if prod not in prods:
            continue

        # freight cost via best port for this plant
        freight = compute_freight_cost(plant, dest_port, weight)
        if not np.isfinite(freight):
            continue

        # WH handling cost
        whc_per_unit = wh_cost_per_unit.get(plant, 0.0)
        wh_cost = whc_per_unit * units

        total_cost = freight + wh_cost

        if (best is None) or (total_cost < best["total_cost"]):
            best = {
                "plant": plant,
                "dest_port": dest_port,
                "weight": weight,
                "freight_cost": freight,
                "wh_cost": wh_cost,
                "total_cost": total_cost,
            }

    return best


def visualize_network(result_df):
    """
    Creates a simplified supply chain network graph showing ONLY:
    - Plants used in result_df
    - Destination ports used in result_df
    - Customers from result_df
    - Edges: Plant → Port → Customer (actual routes only)
    """

    G = nx.DiGraph()

    # --- 1. Collect only used nodes ---
    used_plants = set(result_df['AssignedPlant'].dropna().unique())
    used_ports = set(result_df['DestPort'].dropna().unique())
    used_customers = set(result_df['CustomerID'].dropna().unique())

    # --- 2. Add nodes with type ---
    for p in used_plants:
        G.add_node(p, type='PLANT')

    for port in used_ports:
        G.add_node(port, type='PORT')

    for cust in used_customers:
        G.add_node(cust, type='CUSTOMER')

    # --- 3. Add edges for real assignments ---
    def find_best_origin_port(plant, dest_port, weight):
        sub = freight_rates[
            (freight_rates['dest_port_cd'] == dest_port)
        ]

        best_port = None
        best_cost = np.inf

        for oport in plant_to_ports.get(plant, []):
            lane = sub[sub['orig_port_cd'] == oport]
            if lane.empty:
                continue

            # find rows matching weight bracket
            match = lane[
                (lane['minm_wgh_qty'] <= weight) &
                (lane['max_wgh_qty'] >= weight)
            ]

            # if multiple rows match → compute cost for each
            if not match.empty:
                match = match.copy()
                match["calc_cost"] = match.apply(
                    lambda r: max(r["minimum cost"], r["rate"] * weight),
                    axis=1
                )
                best_row = match.loc[match["calc_cost"].idxmin()]
            else:
                # fallback: largest bracket
                largest = lane.loc[lane['max_wgh_qty'].idxmax()]
                best_row = largest

            total_cost = max(best_row["minimum cost"], best_row["rate"] * weight)

            if total_cost < best_cost:
                best_cost = total_cost
                best_port = oport

        return best_port


    for _, row in result_df.iterrows():
        plant = row['AssignedPlant']
        dest_port = row['DestPort']
        cust = row['CustomerID']
        weight = row['EstWeight']

        if pd.isna(plant) or pd.isna(dest_port):
            continue

        # Determine best origin port based on freight calculation
        origin_port = find_best_origin_port(plant, dest_port, weight)
        if origin_port:
            G.add_node(origin_port, type='PORT')
            used_ports.add(origin_port)

            # Plant → Origin Port
            G.add_edge(plant, origin_port, mode="ORIGIN")

            # Origin Port → Destination Port
            G.add_edge(origin_port, dest_port, mode="TRANSIT")

        # Destination Port → Customer
        if cust:
            G.add_edge(dest_port, cust, mode="DELIVERY")

    # --- 4. Remove isolated nodes ---
    isolated_nodes = [node for node in G.nodes() if G.degree(node) == 0]
    G.remove_nodes_from(isolated_nodes)

    # --- 5. Graph layout ---
    pos = nx.spring_layout(G, seed=42, k=0.8)

    # --- 6. Build Plotly figure ---
    node_types = ['PLANT', 'PORT', 'CUSTOMER']
    colors = {'PLANT': 'blue', 'PORT': 'orange', 'CUSTOMER': 'green'}
    traces = []

    for t in node_types:
        xs, ys, labels = [], [], []
        for node, data in G.nodes(data=True):
            if data['type'] == t:
                x, y = pos[node]
                xs.append(x); ys.append(y)
                labels.append(node)

        traces.append(
            go.Scatter(
                x=xs, y=ys,
                mode='markers+text',
                text=labels,
                textposition='top center',
                marker=dict(size=14, color=colors[t]),
                name=t
            )
        )

    # Edges
    edge_x, edge_y = [], []
    for u, v in G.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        mode='lines',
        line=dict(width=2, color="gray"),
        hoverinfo='none'
    )

    fig = go.Figure(data=[edge_trace] + traces)
    fig.update_layout(
        title="Optimized Supply Chain Route (Minimal Used Network)",
        showlegend=True,
        height=700,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False)
    )

    return fig



# =========================================
# 3. STREAMLIT APP UI
# =========================================

st.title("Supply Chain Cost Estimator")
st.write("Upload an Excel file with orders and get the optimal plant, port, and cost per order.")

st.markdown("""
**Expected columns in upload:**
- `OrderID`
- `CustomerID`
- `ProductID`
- `Units`
""")

uploaded_file = st.file_uploader("Upload orders Excel", type=["xlsx", "xls"])

if uploaded_file is not None:
    # Read uploaded file
    try:
        new_orders = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"Error reading file: {e}")
        st.stop()

    st.subheader("Uploaded Orders (raw)")
    st.dataframe(new_orders.head())

    # Try to standardize column names
    cols = {c.lower().strip(): c for c in new_orders.columns}

    def get_col(possible_names):
        for name in possible_names:
            if name.lower() in cols:
                return cols[name.lower()]
        return None

    col_order   = get_col(["orderid", "order id"])
    col_cust    = get_col(["customerid", "customer id"])
    col_prod    = get_col(["productid", "product id"])
    col_units   = get_col(["units", "unit quantity", "qty", "quantity"])

    missing = [name for name, col in [
        ("OrderID", col_order),
        ("CustomerID", col_cust),
        ("ProductID", col_prod),
        ("Units", col_units),
    ] if col is None]

    if missing:
        st.error(f"Missing required columns in upload: {', '.join(missing)}")
        st.stop()

    # Normalize IDs and prepare
    df = pd.DataFrame({
        "OrderID": new_orders[col_order],
        "CustomerID": new_orders[col_cust].astype(str).str.strip().str.upper(),
        "ProductID": new_orders[col_prod].astype(str).str.strip(),
        "Units": new_orders[col_units].astype(float),
    })

    # Compute best plant/port/cost for each order
    results = []
    for _, row in df.iterrows():
        best = best_plant_for_order(row["CustomerID"], row["ProductID"], row["Units"])
        if best is None:
            results.append({
                "OrderID": row["OrderID"],
                "CustomerID": row["CustomerID"],
                "ProductID": row["ProductID"],
                "Units": row["Units"],
                "AssignedPlant": None,
                "DestPort": None,
                "EstWeight": None,
                "FreightCost": None,
                "WHCost": None,
                "TotalCost": None,
            })
        else:
            results.append({
                "OrderID": row["OrderID"],
                "CustomerID": row["CustomerID"],
                "ProductID": row["ProductID"],
                "Units": row["Units"],
                "AssignedPlant": best["plant"],
                "DestPort": best["dest_port"],
                "EstWeight": best["weight"],
                "FreightCost": best["freight_cost"],
                "WHCost": best["wh_cost"],
                "TotalCost": best["total_cost"],
            })

    result_df = pd.DataFrame(results)

    st.subheader("Optimization Results per Order")
    st.dataframe(result_df)

    # Summary: cost by plant
    st.subheader("Cost Summary by Plant")
    plant_summary = (
        result_df
        .dropna(subset=["AssignedPlant"])
        .groupby("AssignedPlant")
        .agg(
            Total_Units=("Units", "sum"),
            Total_Weight=("EstWeight", "sum"),
            Total_Freight=("FreightCost", "sum"),
            Total_WH=("WHCost", "sum"),
            Total_Cost=("TotalCost", "sum"),
            Num_Orders=("OrderID", "count"),
        )
        .sort_values("Total_Cost", ascending=False)
    )
    st.dataframe(plant_summary)

    st.subheader("Supply Chain Network Visualization")

    fig = visualize_network(result_df)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Total Cost by Plant (Bar Chart)")
    if not plant_summary.empty:
        st.bar_chart(plant_summary["Total_Cost"])

    st.subheader("Total Freight vs WH Cost (Overall)")
    total_freight = result_df["FreightCost"].sum(skipna=True)
    total_wh = result_df["WHCost"].sum(skipna=True)

    st.metric("Total Freight Cost", f"{total_freight:,.0f}")
    st.metric("Total Warehouse Cost", f"{total_wh:,.0f}")

