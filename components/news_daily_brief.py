"""Streamlit presentation for dynamic technology and semiconductor highlights."""

import streamlit as st

from services.news_daily_brief import sanitize_news_url


def _citation_is_incomplete(citation, safe_url):
    source = str(citation.get("source") or "").strip().lower()
    return any((
        not citation.get("title"),
        source in ("", "unknown", "unavailable"),
        not citation.get("publisher"),
        not citation.get("published_at"),
        not safe_url,
    ))


def _render_daily_brief_citations(citations, *, labels, item_index):
    st.markdown(f"**{labels['citation_news']}**")
    if not citations:
        st.info(labels["no_verified_citations"])
        return
    for citation_index, citation in enumerate(citations[:4], start=1):
        citation = citation if isinstance(citation, dict) else {}
        title = citation.get("title") or labels["unavailable"]
        source = citation.get("source") or labels["source_unknown"]
        publisher = citation.get("publisher")
        published_at = citation.get("published_at") or labels["published_unknown"]
        safe_url = sanitize_news_url(citation.get("url"))
        st.markdown(f"**{citation_index}. {title}**")
        source_text = str(source)
        if publisher and str(publisher) != source_text:
            source_text = f"{source_text} / {publisher}"
        st.caption(f"{source_text} | {published_at}")
        if citation.get("is_fallback"):
            st.caption(f"⚠️ {labels['fallback_data']}")
        if _citation_is_incomplete(citation, safe_url):
            st.caption(labels["citation_incomplete"])
        if safe_url:
            st.link_button(
                labels["open_article"],
                safe_url,
                key=f"daily_brief_citation_{item_index}_{citation_index}",
            )


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
                st.markdown(f"**{labels['why_important']}：**" if str(language or "").lower() in ("zh", "中文", "chinese") else f"**{labels['why_important']}:**")
                if item.get("importance_reason"):
                    st.write(item["importance_reason"])
                else:
                    st.caption(labels["unavailable"])
                related = ", ".join(str(value) for value in item.get("related_tickers") or [])
                sources = ", ".join(str(value) for value in item.get("sources") or [])
                has_citations = isinstance(item.get("citations"), list)
                citations = item.get("citations")[:4] if has_citations else []
                article_count = len(citations) if has_citations else item.get("article_count", 0)
                st.caption(
                    f"{labels['related_tickers']}: {related or labels['unavailable']} | "
                    f"{labels['sources']}: {sources or labels['unavailable']} | "
                    f"{labels['article_count']}: {article_count}"
                )
                with st.expander(f"{labels['view_citations']} ({len(citations)})", expanded=False):
                    _render_daily_brief_citations(citations, labels=labels, item_index=index)
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
