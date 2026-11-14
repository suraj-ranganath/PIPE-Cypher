from pipecypher.config import RunConfig
from pipecypher.limit_ties import (
    NO_TIE,
    NOT_APPLICABLE,
    TIE,
    UNRESOLVED,
    UNSUPPORTED,
    check_limit_tie,
    plan_tie_check,
)
from pipecypher.models import ExecutionResult


def _runner(rows):
    seen = []

    def run(query):
        seen.append(query)
        return ExecutionResult(success=True, rows=rows)

    return run, seen


def test_final_order_by_limit_tie_detected_and_limit_rewritten():
    query = (
        "MATCH (a:Account)<-[:TRANSFER_TO]-(b:Account) RETURN DISTINCT a.accountId AS accountId, "
        "COUNT(DISTINCT b) AS numAccounts ORDER BY numAccounts DESC LIMIT 1"
    )
    run, seen = _runner([{"accountId": "1", "numAccounts": 5}, {"accountId": "2", "numAccounts": 5}])
    result = check_limit_tie(query, run)
    assert result.status == TIE
    assert seen == [query.replace("LIMIT 1", "LIMIT 2")]
    run, _ = _runner([{"accountId": "1", "numAccounts": 5}, {"accountId": "2", "numAccounts": 4}])
    assert check_limit_tie(query, run).status == NO_TIE


def test_with_clause_limit_is_checked_and_rows_are_sorted_locally():
    query = (
        "MATCH (a:Account)<-[w:WITHDRAW_TO]-(:Account) WITH a, COUNT(DISTINCT w) AS incomingCount "
        "ORDER BY incomingCount DESC LIMIT 2 RETURN DISTINCT a.accountId AS accountId, incomingCount"
    )
    rows = [
        {"accountId": "x", "incomingCount": 3},
        {"accountId": "y", "incomingCount": 9},
        {"accountId": "z", "incomingCount": 3},
    ]
    run, _ = _runner(rows)
    assert check_limit_tie(query, run).status == TIE
    run, _ = _runner([{"accountId": "x", "incomingCount": 3}, {"accountId": "y", "incomingCount": 9}])
    assert check_limit_tie(query, run).status == NO_TIE


def test_expression_order_key_maps_to_alias_and_secondary_key_breaks_tie():
    query = (
        "MATCH (c:Company)-[al:APPLY_LOAN]->(l:Loan) RETURN DISTINCT l.loanId AS loanId, "
        "al.loanAmount AS applyLoanAmount ORDER BY al.loanAmount DESC, loanId ASC LIMIT 1"
    )
    rows = [{"loanId": "b", "applyLoanAmount": 10}, {"loanId": "a", "applyLoanAmount": 10}]
    run, _ = _runner(rows)
    result = check_limit_tie(query, run)
    assert result.status == NO_TIE
    assert result.order_columns == ("applyLoanAmount", "loanId")


def test_conservative_statuses():
    assert plan_tie_check("MATCH (a:Account) RETURN a.accountId AS id")[1].status == NOT_APPLICABLE
    assert plan_tie_check(
        "MATCH (a:Account) RETURN a.accountId AS id ORDER BY a.balance DESC LIMIT 3"
    )[1].status == UNRESOLVED
    assert plan_tie_check(
        "MATCH (a:Account) RETURN a.accountId AS id ORDER BY id SKIP 2 LIMIT 3"
    )[1].status == UNSUPPORTED
    assert plan_tie_check(
        "MATCH (a:Account) WITH a ORDER BY a.balance WITH a MATCH (a)-[:TRANSFER_TO]->(b) "
        "RETURN b.accountId AS id LIMIT 3"
    )[1].status == UNSUPPORTED
    assert plan_tie_check(
        "MATCH (a:Account) WITH a ORDER BY a.balance DESC LIMIT 3 MATCH (a)-[:TRANSFER_TO]->(b) "
        "RETURN b.accountId AS id"
    )[1].status == UNSUPPORTED


def test_string_literals_are_never_rewritten():
    query = (
        "MATCH (p:Person {name: 'ORDER BY x LIMIT 4'}) RETURN p.id AS id, p.age AS age "
        "ORDER BY age DESC LIMIT 2"
    )
    rewritten, plan = plan_tie_check(query)
    assert plan.limit == 2
    assert rewritten == query.replace("LIMIT 2", "LIMIT 3")
    assert "'ORDER BY x LIMIT 4'" in rewritten


def test_all_candidates_under_limit_is_not_a_tie():
    query = "MATCH (a:Account) RETURN a.accountId AS id, a.balance AS bal ORDER BY bal LIMIT 3"
    run, _ = _runner([{"id": 1, "bal": 1}, {"id": 2, "bal": 1}])
    assert check_limit_tie(query, run).status == NO_TIE


def test_config_flag_defaults_off():
    assert RunConfig().generation.reject_limit_boundary_ties is False
