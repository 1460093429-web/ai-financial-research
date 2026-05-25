import chromadb
from datetime import datetime

# Initialize ChromaDB
client = chromadb.PersistentClient(path="./memory_db")
collection = client.get_or_create_collection("financial_reports")

def save_report(company, data, analysis):
    """Save analysis report to long-term memory."""
    doc_id = f"{company}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    document = f"""
Company: {company}
Date: {datetime.now().strftime('%Y-%m-%d')}
Revenue: ${data['Revenue']/1e9:.1f}B
Net Income: ${data['NetIncome']/1e9:.1f}B
Net Margin: {data['Margin']*100:.1f}%
Analysis: {analysis}
"""
    
    collection.add(
        documents=[document],
        ids=[doc_id],
        metadatas=[{"company": company, "date": datetime.now().strftime('%Y-%m-%d')}]
    )
    print(f"Saved to memory: {doc_id}")

def get_history(company, n_results=3):
    """Retrieve past reports for a company."""
    results = collection.query(
        query_texts=[f"{company} financial analysis"],
        n_results=n_results
    )
    
    if results["documents"][0]:
        return "\n---\n".join(results["documents"][0])
    return "No history found."

def analyze_with_memory(financial_data, analyze_fn):
    """Run analysis with historical context."""
    from openai import OpenAI
    from config import OPENAI_API_KEY
    
    client_ai = OpenAI(api_key=OPENAI_API_KEY)
    
    for company, data in financial_data.items():
        # Get history
        history = get_history(company)
        
        # Current data
        summary = f"""
Current Data ({datetime.now().strftime('%Y-%m-%d')}):
Revenue: ${data['Revenue']/1e9:.1f}B
Net Income: ${data['NetIncome']/1e9:.1f}B
Net Margin: {data['Margin']*100:.1f}%

Historical Context:
{history}
"""
        
        prompt = f"""
You are a professional US stock analyst with memory of past reports.

{summary}

Based on current data AND historical context, analyze:
1. How has this company's performance changed over time?
2. What trends do you see?
3. Updated investment recommendation?

Be concise and professional.
"""
        
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        
        analysis = response.choices[0].message.content
        print(f"\n=== {company} Analysis with Memory ===")
        print(analysis)
        
        # Save to memory
        save_report(company, data, analysis)
    
    return analysis

if __name__ == "__main__":
    from financials import get_financial_data
    from ai_analysis import analyze_financials
    
    print("Running analysis with long-term memory...")
    data = get_financial_data()
    analyze_with_memory(data, analyze_financials)