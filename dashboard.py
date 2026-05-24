import streamlit as st
from financials import get_financial_data
from ai_analysis import analyze_financials

st.title("AI Financial Research System")
st.subheader("US Stock AI Analysis Platform")

if st.button("Run Analysis"):
    with st.spinner("Fetching financial data..."):
        data = get_financial_data()
    
    st.success("Data loaded successfully!")
    
    st.subheader("Financial Data")
    for company, info in data.items():
        col1, col2, col3 = st.columns(3)
        col1.metric(f"{company} Revenue", f"${info['Revenue']/1e9:.1f}B")
        col2.metric(f"{company} Net Income", f"${info['NetIncome']/1e9:.1f}B")
        col3.metric(f"{company} Net Margin", f"{info['Margin']*100:.1f}%")
    
    st.subheader("AI Analysis Report")
    with st.spinner("AI is analyzing..."):
        analysis = analyze_financials(data)
    
    st.write(analysis)