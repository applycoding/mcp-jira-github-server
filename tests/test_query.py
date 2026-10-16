from jira_github_mcp.query import parse_query, to_jql


def test_parse_query_splits_filters_and_text() -> None:
    filters, text = parse_query('status:"In Progress" project:PLAT audit log')
    assert filters == {"status": "In Progress", "project": "PLAT"}
    assert text == "audit log"


def test_to_jql_wraps_free_text_and_scopes_projects() -> None:
    assert to_jql("login", ("PLAT",)) == 'project = PLAT AND text ~ "login" ORDER BY updated DESC'


def test_to_jql_quotes_status_filters() -> None:
    jql = to_jql('status:"In Progress" audit', ())
    assert jql == 'status = "In Progress" AND text ~ "audit" ORDER BY updated DESC'


def test_raw_jql_is_not_rewritten() -> None:
    raw = 'project = PLAT AND text ~ "login"'
    assert to_jql(raw, ("MOB",)) == raw
