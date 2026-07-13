"""Streamlit presentation for dynamic technology and semiconductor highlights."""

import streamlit as st


def render_news_daily_brief(result, *, labels, language="zh") -> bool:
    """Render up to ten event cards and return whether generation was requested."""
    result = result if isinstance(result, dict) else {}
    status = result.get("status")
    items = result.get("items") if isinstance(result.get("items"), list) else []
    st.subheader(labels["title"])
    if status == "ok" and items:
        metadata = [
            f"{labels['articles_used']}: {result.get('articles_used', 0)}",
            f"{labels['sources']}: {', '.join(result.get('sources_used') or []) or labels['unavailable']}",
            f"{labels['generated_at']}: {result.get('generated_at') or labels['unavailable']}",
            f"{labels['data_date']}: {result.get('data_date') or labels['unavailable']}",
        ]
        st.caption(" | ".join(metadata))
        for index, item in enumerate(items[:10], start=1):
            item = item if isinstance(item, dict) else {}
            with st.container(border=True):
                st.markdown(f"#### {index}. {item.get('title') or labels['unavailable']}")
                if item.get("summary"):
                    st.write(item["summary"])
                related = ", ".join(str(value) for value in item.get("related_tickers") or [])
                sources = ", ".join(str(value) for value in item.get("sources") or [])
                st.caption(
                    f"{labels['related_tickers']}: {related or labels['unavailable']} | "
                    f"{labels['sources']}: {sources or labels['unavailable']} | "
                    f"{labels['article_count']}: {item.get('article_count', 0)}"
                )
    elif status == "missing_key":
        st.warning(labels["missing_key"])
    elif status == "empty":
        st.info(labels["empty"])
    elif status == "error":
        st.warning(labels["error"])
        titles = [str(title) for title in result.get("candidate_titles") or [] if title]
        if titles:
            st.caption(f"{labels['candidates']}: {' · '.join(titles[:5])}")
    else:
        st.caption(labels["idle"])
    button_label = labels["regenerate"] if status else labels["generate"]
    return st.button(
        button_label,
        key=f"technology_daily_brief_{str(language or 'zh').lower()}",
    )
