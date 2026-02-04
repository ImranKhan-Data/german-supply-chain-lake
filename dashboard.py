import streamlit as st
import boto3
import pandas as pd
import time
import os
from dotenv import load_dotenv

# --- CONFIG ---
load_dotenv()
AWS_REGION = os.getenv("AWS_DEFAULT_REGION")
DATABASE = os.getenv("ATHENA_DATABASE")
TABLE = os.getenv("ATHENA_TABLE")
S3_OUTPUT = os.getenv("S3_OUTPUT_BUCKET")

# --- CONNECT ---
session = boto3.Session(
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=AWS_REGION
)
athena_client = session.client('athena')
s3_client = session.client('s3')

st.set_page_config(page_title="Supply Chain Monitor", layout="wide", page_icon="🚛")
st.title("🚛 German Supply Chain Risk Monitor")

# --- SIDEBAR CONTROLS ---
st.sidebar.header("🕹️ User Controls")

# 1. THE CITY SELECTOR (Giving user authority)
selected_city = st.sidebar.selectbox(
    "Select Logistics Hub:",
    ["hamburg", "frankfurt", "berlin", "munich"],
    index=0
)

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()

# --- QUERY FUNCTION ---
def run_query(city):
    # SQL Query: Dynamically filter by the user's selected city
    # Note: We check if 'city_name' exists (it might be null for old data)
    query = f"""
    SELECT 
        ingestion_time,
        city_name,
        "current"."temperature_2m" as temp, 
        "current"."wind_speed_10m" as wind
    FROM "{TABLE}" 
    WHERE city_name = '{city}'
    ORDER BY ingestion_time DESC 
    LIMIT 50;
    """
    
    # ... (Standard Athena Boilerplate) ...
    response = athena_client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': DATABASE},
        ResultConfiguration={'OutputLocation': S3_OUTPUT}
    )
    query_id = response['QueryExecutionId']
    
    with st.spinner(f'📡 Fetching data for {city.upper()}...'):
        while True:
            stats = athena_client.get_query_execution(QueryExecutionId=query_id)
            status = stats['QueryExecution']['Status']['State']
            if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']: break
            time.sleep(0.5)
            
    if status == 'FAILED':
        st.error(f"Error: {stats['QueryExecution']['Status']['StateChangeReason']}")
        return pd.DataFrame()
        
    path = stats['QueryExecution']['ResultConfiguration']['OutputLocation']
    bucket = path.split('/')[2]
    key = '/'.join(path.split('/')[3:])
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    return pd.read_csv(obj['Body'])

# --- MAIN APP ---
df = run_query(selected_city)

if not df.empty:
    # ---------------------------------------------------------
    # 🛠️ TIMEZONE FIX: Convert UTC to Germany Time
    # ---------------------------------------------------------
    # 1. Convert the text column to a real Datetime object
    df['ingestion_time'] = pd.to_datetime(df['ingestion_time'])
    
    # 2. Tell Python: "This data is currently in UTC"
    df['ingestion_time'] = df['ingestion_time'].dt.tz_localize('UTC')
    
    # 3. Convert it to: "Europe/Berlin" (Automatically handles +1 or +2)
    df['ingestion_time'] = df['ingestion_time'].dt.tz_convert('Europe/Berlin')
    
    # ---------------------------------------------------------

    latest = df.iloc[0]
    
    # Dynamic Title
    st.markdown(f"### 📍 Real-time Status: **{selected_city.capitalize()}**")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🌡️ Temperature", f"{latest['temp']} °C")
    
    wind_val = latest['wind']
    c2.metric("🌬️ Wind Speed", f"{wind_val} km/h", 
              delta="High Risk" if wind_val > 20 else "Normal", 
              delta_color="inverse")
    
    c3.metric("📦 Data Points", len(df))
    
    # Display the formatted local time
    local_time_str = latest['ingestion_time'].strftime('%Y-%m-%d %H:%M:%S')
    c4.metric("🕒 Last Update (DE)", local_time_str)
    
    st.divider()
    
    st.subheader(f"📉 {selected_city.capitalize()} Weather Trend (Last 24h)")
    chart_data = df.set_index('ingestion_time').iloc[::-1]
    st.line_chart(chart_data[['temp', 'wind']])
    
else:
    st.warning(f"No data found for {selected_city} yet.")