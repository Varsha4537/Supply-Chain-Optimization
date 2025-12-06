# 🚚 Supply Chain Optimization App  
A Streamlit-based decision support tool that optimizes product flow across a supply chain network — determining the **best plant**, **best origin port**, **transportation cost**, and **warehouse handling cost** for each order.

This project uses real operating constraints from:
- Plant production capability  
- Allowed plant–port connections  
- Freight cost tables (with weight brackets)  
- Warehouse per-unit handling cost  
- Customer destination ports  
- Product-level weight estimation  

The app allows users to **upload a simple order file** and instantly receive an optimized supply chain routing plan.

---

## 🌟 Features

### ✔ Upload Orders  
Upload an Excel file with:
- `OrderID`
- `CustomerID`
- `ProductID`
- `Units`

### ✔ Automatic Optimization  
For each uploaded order, the app:
1. Picks the **valid plants** that can produce the product  
2. Determines the **best origin port** for that plant  
3. Calculates:
   - Transportation cost (based on weight brackets)
   - Warehouse handling cost
   - Total landed cost  
4. Returns the **cheapest total combination**

### ✔ Visual Network Graph  
Shows a **clean supply chain network** containing only:
- Plants used  
- Ports used  
- Customers from the upload  
- Actual routes taken (Plant → Port → Customer)

### ✔ Summaries  
- Overall freight vs warehouse cost  
- Cost breakdown per plant  
- Orders table with assigned routes



---

## The app is hosted on 
https://supply-chain-optimization-final-project-varsha.streamlit.app/

## 🛠️ Installation & Running Locally

### Clone the repository

git clone https://github.com/Varsha4537/Supply-Chain-Optimization.git
cd Supply-Chain-Optimization 


### Create a virtual environment (recommended)
python3 -m venv sc_env
source sc_env/bin/activate   # Mac/Linux
# OR
sc_env\Scripts\activate      # Windows

### Install dependencies
pip install -r requirements.txt

### Run the app
streamlit run app.py

### Then open:
http://localhost:8501