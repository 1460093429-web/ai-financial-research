"""Streamlit presentation for one combined technology daily brief."""

import streamlit as st


def render_news_daily_brief(result, *, labels, language="zh") -> bool:
    """Render one brief card and return whether generation was explicitly requested."""
    result = result if isinstance(result, dict) else {}
    status = result.get("status")
    with st.container(border=True):
        st.subheader(labels["title"])
        if status == "ok" and result.get("brief"):
            st.write(result["brief"])
            metadata = [
                f"{labels['articles_used']}: {result.get('articles_used', 0)}",
                f"{labels['sources']}: {', '.join(result.get('sources_used') or []) or labels['unavailable']}",
                f"{labels['generated_at']}: {result.get('generated_at') or labels['unavailable']}",
                f"{labels['data_date']}: {result.get('data_date') or labels['unavailable']}",
            ]
            st.caption(" | ".join(metadata))
        elif status == "missing_key":
            st.warning(labels["missing_key"])
        elif status == "empty":
            st.info(labels["empty"])
        elif status == "error":
            st.warning(labels["error"])
            titles = [str(title) for title in result.get("candidate_titles") or [] if title]
            if titles:
                st.caption(f"{labels['candidates']}: {' · '.join(titles[:3])}")
        else:
            st.caption(labels["idle"])
        button_label = labels["regenerate"] if status else labels["generate"]
        return st.button(
            button_label,
            key=f"technology_daily_brief_{str(language or 'zh').lower()}",
        )
