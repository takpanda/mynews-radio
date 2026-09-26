"""テンプレートキーとファイル、入力変数の契約。"""

PROMPT_TEMPLATE_DEFINITIONS = {
    "generate_radio_script": {
        "file": "generate_radio_script.md",
        "required_variables": ["narrative_arc_section", "summaries_json"],
        "allowed_variables": ["narrative_arc_section", "summaries_json"],
    },
    "generate_commentary_script": {
        "file": "generate_commentary_script.md",
        "required_variables": [
            "article_id", "article_json", "article_title", "mc_gender", "section_details",
            "style", "suggested_lines_count",
        ],
        "allowed_variables": [
            "article_id", "article_json", "article_title", "mc_gender", "section_details",
            "style", "suggested_lines_count",
        ],
    },
    "generate_narrative_arc": {
        "file": "generate_narrative_arc.md",
        "required_variables": ["summaries_json"],
        "allowed_variables": ["summaries_json"],
    },
    "summarize_article": {
        "file": "summarize_article.md",
        "required_variables": ["published_at", "source", "text", "title", "url"],
        "allowed_variables": ["published_at", "source", "text", "title", "url"],
    },
    "review_beginner_director": {
        "file": "review_beginner_director.md",
        "required_variables": ["article_summaries_json", "script_json"],
        "allowed_variables": ["article_summaries_json", "script_json"],
    },
    "review_genius_director": {
        "file": "review_genius_director.md",
        "required_variables": ["article_summaries_json", "script_json"],
        "allowed_variables": ["article_summaries_json", "script_json"],
    },
    "review_positive_director": {
        "file": "review_positive_director.md",
        "required_variables": ["article_summaries_json", "script_json"],
        "allowed_variables": ["article_summaries_json", "script_json"],
    },
    "review_radio_director": {
        "file": "review_radio_director.md",
        "required_variables": [
            "article_summaries_json", "output_issue_example", "script_json", "style_guidance",
        ],
        "allowed_variables": [
            "article_summaries_json", "output_issue_example", "script_json", "style_guidance",
        ],
    },
    "review_worried_director": {
        "file": "review_worried_director.md",
        "required_variables": ["article_summaries_json", "script_json"],
        "allowed_variables": ["article_summaries_json", "script_json"],
    },
    "review_synthesize": {
        "file": "review_synthesize.md",
        "required_variables": [
            "article_summaries_json", "beginner_review", "genius_review", "mc_gender", "mode",
            "original_script_json", "positive_review", "radio_review", "worried_review",
        ],
        "allowed_variables": [
            "article_summaries_json", "beginner_review", "genius_review", "mc_gender", "mode",
            "original_script_json", "positive_review", "radio_review", "worried_review",
        ],
    },
    "category": {
        "file": "category.md",
        "required_variables": ["categories", "source"],
        "allowed_variables": ["categories", "source"],
    },
}
